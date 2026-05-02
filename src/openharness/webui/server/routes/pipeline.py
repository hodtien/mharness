"""Pipeline (autopilot registry) REST endpoints for the Web UI."""

from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, ValidationError

from openharness.autopilot.service import RepoAutopilotStore
from openharness.autopilot.types import RepoAutopilotRegistry, RepoTaskStatus
from openharness.webui.server.state import WebUIState, get_state, require_token

router = APIRouter(
    prefix="/api/pipeline",
    tags=["pipeline"],
    dependencies=[Depends(require_token)],
)


class CreateManualCardRequest(BaseModel):
    """Payload for POST /api/pipeline/cards.

    ``title`` is required; ``body`` and ``labels`` are optional.
    """

    title: str = Field(..., min_length=1)
    body: str | None = None
    labels: list[str] | None = None


class CardActionRequest(BaseModel):
    """Payload for POST /api/pipeline/cards/{id}/action.

    ``action`` must be one of: ``accept``, ``reject``, ``retry``.
    """

    action: Literal["accept", "reject", "retry"]


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


@router.post("/cards", status_code=status.HTTP_201_CREATED)
def enqueue_manual_card(
    body: CreateManualCardRequest,
    state: WebUIState = Depends(get_state),
) -> dict:
    """Enqueue a manual idea card into the per-repo autopilot registry.

    Returns the freshly-created card (using the same minimal serialization as
    the list endpoint). Responds with HTTP 409 if a card with the same
    fingerprint already exists, matching the autopilot intake dedupe contract.
    """
    store = RepoAutopilotStore(state.cwd)
    card, created = store.enqueue_card(
        source_kind="manual_idea",
        title=body.title,
        body=body.body or "",
        labels=body.labels,
    )
    if not created:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "duplicate_card",
                "message": "A card with the same fingerprint already exists.",
                "card_id": card.id,
            },
        )
    return _serialize_card(card.model_dump(mode="json"))


_ACTION_TO_STATUS: dict[str, RepoTaskStatus] = {
    "accept": "accepted",
    "reject": "rejected",
    "retry": "queued",
}


@router.post("/cards/{card_id}/action")
def action_pipeline_card(
    card_id: str,
    body: CardActionRequest,
    state: WebUIState = Depends(get_state),
) -> dict:
    """Apply a manual lifecycle action to a pipeline card.

    Loads the per-repo registry, finds the card by ``id``, updates its
    ``status`` according to the action (accept→accepted, reject→rejected,
    retry→queued), persists the registry, and returns the updated card.
    Returns HTTP 404 if no card with the given id exists.
    """
    store = RepoAutopilotStore(state.cwd)
    if store.get_card(card_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "card_not_found", "card_id": card_id},
        )
    new_status = _ACTION_TO_STATUS[body.action]
    card = store.update_status(card_id, status=new_status)
    return _serialize_card(card.model_dump(mode="json"))