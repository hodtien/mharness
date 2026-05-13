"""Cron registry REST endpoints for the Web UI."""

from __future__ import annotations

from pathlib import Path

from croniter import croniter
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from openharness.config.settings import CronScheduleConfig, load_settings, save_settings
from openharness.services.cron import load_cron_jobs, preview_cron_next_runs
from openharness.services.cron_scheduler import is_scheduler_running
from openharness.webui.server.state import require_token

router = APIRouter(
    prefix="/api/cron",
    tags=["cron"],
    dependencies=[Depends(require_token)],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _describe_cron(expression: str) -> str:
    """Return a human-readable description of a cron expression."""
    try:
        # Simple heuristic: describe in terms of minutes/hours/days
        _, minute, hour, day, month, dow = croniter.expand(expression)
        desc_parts: list[str] = []

        if minute and all(m % 5 == 0 for m in minute) and len(minute) > 1:
            desc_parts.append(f"Every {minute[0]} minutes")
        elif minute and minute == list(range(min(minute), max(minute) + 1)) and len(minute) == 1:
            desc_parts.append(f"At minute {minute[0]}")
        elif minute and minute == list(range(0, 60, minute[0])) and len(minute) == 60 // minute[0]:
            desc_parts.append(f"Every {minute[0]} minutes")
        else:
            desc_parts.append(f"Minute {'/'.join(str(m) for m in sorted(minute))}")

        if hour:
            if hour == list(range(24)) or hour == list(range(0, 24, hour[0])):
                desc_parts.append("every hour")
            elif len(hour) == 1:
                desc_parts.append(f"at {hour[0]:02d}:00")
            else:
                desc_parts.append(f"at hours {','.join(str(h) for h in sorted(hour))}")

        if dow and dow != [0, 1, 2, 3, 4, 5, 6]:
            day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            desc_parts.append(f"on {','.join(day_names[d] for d in sorted(dow))}")

        return " ".join(desc_parts) if desc_parts else expression
    except Exception:
        return expression


# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------

class InstallResult(BaseModel):
    """Result of a cron installation attempt."""

    success: bool
    message: str = ""
    scan_installed: bool = False
    tick_installed: bool = False
    scan_line: str = ""
    tick_line: str = ""
    manual_commands: list[str] = Field(default_factory=list)


class CronConfigResponse(BaseModel):
    """Current cron schedule configuration."""

    enabled: bool
    scan_cron: str
    tick_cron: str
    timezone: str
    install_mode: str
    scheduler_running: bool = Field(description="Whether the cron scheduler daemon is running")
    scan_cron_description: str = Field(description="Human-readable description of scan_cron")
    tick_cron_description: str = Field(description="Human-readable description of tick_cron")
    next_scan_runs: list[str] = Field(
        default_factory=list,
        description="ISO-8601 timestamps for the next 3 scan runs. Empty when disabled.",
    )
    next_tick_runs: list[str] = Field(
        default_factory=list,
        description="ISO-8601 timestamps for the next 3 tick runs. Empty when disabled.",
    )
    install_result: InstallResult | None = Field(
        default=None,
        description="Result of the most recent install attempt. Only present after a PATCH.",
    )


class CronConfigPatch(BaseModel):
    """Body for PATCH /api/cron/config — all fields optional."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    scan_cron: str | None = None
    tick_cron: str | None = None
    timezone: str | None = Field(default=None, pattern=r"^[A-Za-z_/]+$")
    install_mode: str | None = Field(default=None, pattern=r"^(auto|manual)$")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/jobs")
def list_cron_jobs() -> dict[str, object]:
    """Return configured local cron-style jobs."""
    return {"jobs": load_cron_jobs()}


@router.get("/config", response_model=CronConfigResponse)
def get_cron_config() -> CronConfigResponse:
    """Return the current cron schedule configuration."""
    settings = load_settings()
    cfg = settings.cron_schedule
    return _build_cron_config_response(cfg)



@router.patch("/config", response_model=CronConfigResponse)
def patch_cron_config(payload: CronConfigPatch) -> CronConfigResponse:
    """Update cron schedule configuration fields.

    Raises HTTP 400 if any cron expression is invalid.
    When install_mode is "auto", also triggers cron job installation.
    """
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one field must be provided",
        )

    # Build proposed config and validate
    settings = load_settings()
    current = settings.cron_schedule
    proposed = CronScheduleConfig(
        enabled=updates.get("enabled", current.enabled),
        scan_cron=updates.get("scan_cron", current.scan_cron),
        tick_cron=updates.get("tick_cron", current.tick_cron),
        timezone=updates.get("timezone", current.timezone),
        install_mode=updates.get("install_mode", current.install_mode),
    )
    errors = proposed.validate_crons()
    if errors:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "Validation failed", "errors": errors},
        )

    # Persist
    settings = settings.model_copy(
        update={"cron_schedule": proposed}
    )
    save_settings(settings)

    # Trigger installation if in auto mode and cron is enabled
    install_result: InstallResult | None = None
    cwd = Path.cwd()
    if proposed.install_mode == "auto" and proposed.enabled:
        from openharness.services.cron import upsert_cron_job

        cwd = Path.cwd()
        scan_job = {
            "name": "autopilot.scan",
            "schedule": proposed.scan_cron,
            "command": f"oh autopilot scan all --cwd {cwd}",
            "cwd": str(cwd),
            "project_path": str(cwd),
        }
        tick_job = {
            "name": "autopilot.tick",
            "schedule": proposed.tick_cron,
            "command": f"oh autopilot tick --cwd {cwd}",
            "cwd": str(cwd),
            "project_path": str(cwd),
        }
        scan_line = f"{scan_job['schedule']} oh autopilot scan all --cwd {cwd}"
        tick_line = f"{tick_job['schedule']} oh autopilot tick --cwd {cwd}"

        scan_installed = False
        tick_installed = False
        errors: list[str] = []

        try:
            upsert_cron_job(scan_job)
            scan_installed = True
        except Exception as e:
            errors.append(f"Scan: {e}")

        try:
            upsert_cron_job(tick_job)
            tick_installed = True
        except Exception as e:
            errors.append(f"Tick: {e}")

        if scan_installed and tick_installed:
            install_result = InstallResult(
                success=True,
                message="Cron jobs installed successfully.",
                scan_installed=True,
                tick_installed=True,
                scan_line=scan_line,
                tick_line=tick_line,
            )
        else:
            install_result = InstallResult(
                success=False,
                message="; ".join(errors) if errors else "Installation partially failed.",
                scan_installed=scan_installed,
                tick_installed=tick_installed,
                scan_line=scan_line,
                tick_line=tick_line,
                manual_commands=_build_manual_commands(proposed.scan_cron, proposed.tick_cron, cwd),
            )

    return _build_cron_config_response(proposed, install_result=install_result)


def _build_manual_commands(scan_cron: str, tick_cron: str, cwd: Path) -> list[str]:
    """Build manual crontab installation commands."""
    return [
        f"(crontab -l 2>/dev/null | grep -v 'oh autopilot scan all'; echo \"{scan_cron} oh autopilot scan all --cwd {cwd}\") | crontab -",
        f"(crontab -l 2>/dev/null | grep -v 'oh autopilot tick'; echo \"{tick_cron} oh autopilot tick --cwd {cwd}\") | crontab -",
    ]


def _build_cron_config_response(
    cfg: CronScheduleConfig,
    install_result: InstallResult | None = None,
) -> CronConfigResponse:
    """Construct CronConfigResponse, including empty run lists when disabled."""
    if cfg.enabled:
        scan_runs = [dt.isoformat() for dt in preview_cron_next_runs(cfg.scan_cron, 3, tz_name=cfg.timezone)]
        tick_runs = [dt.isoformat() for dt in preview_cron_next_runs(cfg.tick_cron, 3, tz_name=cfg.timezone)]
    else:
        scan_runs = []
        tick_runs = []

    return CronConfigResponse(
        enabled=cfg.enabled,
        scan_cron=cfg.scan_cron,
        tick_cron=cfg.tick_cron,
        timezone=cfg.timezone,
        install_mode=cfg.install_mode,
        scheduler_running=is_scheduler_running(),
        scan_cron_description=_describe_cron(cfg.scan_cron),
        tick_cron_description=_describe_cron(cfg.tick_cron),
        next_scan_runs=scan_runs,
        next_tick_runs=tick_runs,
        install_result=install_result,
    )
