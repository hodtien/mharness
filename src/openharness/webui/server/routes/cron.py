"""Cron registry REST endpoints for the Web UI."""

from __future__ import annotations

from croniter import croniter
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from openharness.config.settings import CronScheduleConfig, load_settings, save_settings
from openharness.services.cron import load_cron_jobs, preview_cron_next_runs
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

class CronConfigResponse(BaseModel):
    """Current cron schedule configuration."""

    enabled: bool
    scan_cron: str
    tick_cron: str
    timezone: str
    install_mode: str
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

    return _build_cron_config_response(proposed)


def _build_cron_config_response(cfg: CronScheduleConfig) -> CronConfigResponse:
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
        scan_cron_description=_describe_cron(cfg.scan_cron),
        tick_cron_description=_describe_cron(cfg.tick_cron),
        next_scan_runs=scan_runs,
        next_tick_runs=tick_runs,
    )
