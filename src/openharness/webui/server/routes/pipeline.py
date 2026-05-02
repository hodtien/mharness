"""Pipeline (autopilot registry) REST endpoints for the Web UI."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from pydantic import ValidationError

from openharness.autopilot.types import RepoAutopilotRegistry
from openharness.webui.server.state import WebUIState, get_state, require_token

router = APIRouter(
    prefix="/api/pipeline",
    tags=["pipeline"],
    dependencies=[Depends(require_token)],
)


def _serialize_card(card: dict) -> dict:
    """Return only the fields required by the GET /api/pipeline/cards contract."""
    return {
        "id": card["id"],
        "title": card["title"],
        "status": card["status"],
        "source_kind": card["source_kind"],
        "score": card["score"],
        "labels": card["labels"],
        "created_at": card["created_at"],
        "updated_at": card["updated_at"],
    }


@router.get("/cards")
def list_pipeline_cards(state: WebUIState = Depends(get_state)) -> dict:
    """Return the autopilot task card list from the per-repo registry.

    Reads ``.openharness/autopilot/registry.json``. Returns an empty card list
    if the file does not exist or is malformed, matching the behaviour of
    :meth:`openharness.autopilot.service.RepoAutopilotService._load_registry`.
    """
    registry_path = state.cwd / ".openharness" / "autopilot" / "registry.json"
    if not registry_path.is_file():
        return {"cards": [], "updated_at": 0.0}
    try:
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"cards": [], "updated_at": 0.0}
    try:
        registry = RepoAutopilotRegistry.model_validate(payload)
    except ValidationError:
        return {"cards": [], "updated_at": 0.0}
    return {
        "cards": [_serialize_card(card.model_dump(mode="json")) for card in registry.cards],
        "updated_at": registry.updated_at,
    }