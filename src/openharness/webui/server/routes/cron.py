"""Cron registry REST endpoints for the Web UI."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from openharness.services.cron import load_cron_jobs
from openharness.webui.server.state import require_token

router = APIRouter(
    prefix="/api/cron",
    tags=["cron"],
    dependencies=[Depends(require_token)],
)


@router.get("/jobs")
def list_cron_jobs() -> dict[str, object]:
    """Return configured local cron-style jobs."""
    return {"jobs": load_cron_jobs()}
