from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from openharness.webui.server.app import create_app

AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))


def _client(tmp_path) -> TestClient:
    return TestClient(create_app(token="test-token", cwd=tmp_path, model="sonnet"))


# ---------------------------------------------------------------------------
# GET /api/pipeline/cards — list
# ---------------------------------------------------------------------------

def test_list_cards_empty_returns_empty_list(tmp_path) -> None:
    client = _client(tmp_path)

    response = client.get("/api/pipeline/cards", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["cards"] == []
    assert "updated_at" in body


def test_list_cards_returns_enqueued_cards(tmp_path) -> None:
    client = _client(tmp_path)

    # Enqueue two cards.
    r1 = client.post("/api/pipeline/cards", headers=AUTH, json={"title": "First card"})
    assert r1.status_code == 201
    r2 = client.post("/api/pipeline/cards", headers=AUTH, json={"title": "Second card"})
    assert r2.status_code == 201

    response = client.get("/api/pipeline/cards", headers=AUTH)

    assert response.status_code == 200
    cards = response.json()["cards"]
    assert len(cards) == 2
    titles = {c["title"] for c in cards}
    assert titles == {"First card", "Second card"}


def test_list_cards_includes_metadata_fields(tmp_path) -> None:
    """Cards must expose ``metadata.last_note`` / ``linked_pr_url`` for the blocker banner."""
    client = _client(tmp_path)

    r = client.post("/api/pipeline/cards", headers=AUTH, json={"title": "Metadata card"})
    assert r.status_code == 201

    response = client.get("/api/pipeline/cards", headers=AUTH)
    assert response.status_code == 200
    cards = response.json()["cards"]
    assert len(cards) == 1
    card = cards[0]
    assert "metadata" in card
    assert "last_note" in card["metadata"]
    assert "linked_pr_url" in card["metadata"]


# ---------------------------------------------------------------------------
# POST /api/pipeline/cards — enqueue
# ---------------------------------------------------------------------------

def test_enqueue_card_returns_201_with_serialized_card(tmp_path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/pipeline/cards",
        headers=AUTH,
        json={"title": "My idea", "body": "Detailed description", "labels": ["enhancement"]},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "My idea"
    assert body["status"] == "queued"
    assert body["source_kind"] == "manual_idea"
    assert "id" in body
    assert "score" in body
    assert "created_at" in body
    assert "updated_at" in body


def test_enqueue_duplicate_card_returns_409(tmp_path) -> None:
    client = _client(tmp_path)

    first = client.post("/api/pipeline/cards", headers=AUTH, json={"title": "Duplicate idea"})
    assert first.status_code == 201

    second = client.post("/api/pipeline/cards", headers=AUTH, json={"title": "Duplicate idea"})

    assert second.status_code == 409
    body = second.json()
    assert body["detail"]["error"] == "duplicate_card"
    assert "card_id" in body["detail"]


# ---------------------------------------------------------------------------
# POST /api/pipeline/cards/{card_id}/action
# ---------------------------------------------------------------------------

def test_action_accept_updates_card_status_to_accepted(tmp_path) -> None:
    client = _client(tmp_path)

    r = client.post("/api/pipeline/cards", headers=AUTH, json={"title": "Action test card"})
    assert r.status_code == 201
    card_id = r.json()["id"]

    response = client.post(
        f"/api/pipeline/cards/{card_id}/action",
        headers=AUTH,
        json={"action": "accept"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == card_id
    assert body["status"] == "accepted"


def test_action_reject_updates_card_status_to_rejected(tmp_path) -> None:
    client = _client(tmp_path)

    r = client.post("/api/pipeline/cards", headers=AUTH, json={"title": "Reject me"})
    assert r.status_code == 201
    card_id = r.json()["id"]

    response = client.post(
        f"/api/pipeline/cards/{card_id}/action",
        headers=AUTH,
        json={"action": "reject"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "rejected"


def test_action_retry_updates_card_status_to_queued(tmp_path) -> None:
    client = _client(tmp_path)

    r = client.post("/api/pipeline/cards", headers=AUTH, json={"title": "Retry me"})
    assert r.status_code == 201
    card_id = r.json()["id"]

    # First accept it.
    client.post(f"/api/pipeline/cards/{card_id}/action", headers=AUTH, json={"action": "accept"})

    # Retry should put it back to queued.
    response = client.post(
        f"/api/pipeline/cards/{card_id}/action",
        headers=AUTH,
        json={"action": "retry"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"


def test_action_on_unknown_card_returns_404(tmp_path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/pipeline/cards/nonexistent-id/action",
        headers=AUTH,
        json={"action": "accept"},
    )

    assert response.status_code == 404
    body = response.json()
    assert body["detail"]["error"] == "card_not_found"


# ---------------------------------------------------------------------------
# GET /api/pipeline/cards/{card_id} — detail
# ---------------------------------------------------------------------------


def test_get_card_detail_returns_full_card_with_model(tmp_path) -> None:
    client = _client(tmp_path)

    created = client.post(
        "/api/pipeline/cards",
        headers=AUTH,
        json={"title": "Detail card", "body": "Full body", "labels": ["ui"]},
    )
    assert created.status_code == 201
    card_id = created.json()["id"]

    response = client.get(f"/api/pipeline/cards/{card_id}", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == card_id
    assert body["title"] == "Detail card"
    assert body["body"] == "Full body"
    assert body["model"] is None
    assert "metadata" in body
    assert "linked_pr_url" in body
    assert body["attempt_count"] == 0
    assert "available_models" in body


# ---------------------------------------------------------------------------
# PATCH /api/pipeline/cards/{card_id}/model
# ---------------------------------------------------------------------------


def test_serialize_card_includes_model(tmp_path) -> None:
    client = _client(tmp_path)

    response = client.post("/api/pipeline/cards", headers=AUTH, json={"title": "Model field card"})

    assert response.status_code == 201
    assert "model" in response.json()


def test_patch_card_model(tmp_path) -> None:
    client = _client(tmp_path)
    created = client.post("/api/pipeline/cards", headers=AUTH, json={"title": "Model override card"})
    assert created.status_code == 201
    card_id = created.json()["id"]

    response = client.patch(
        f"/api/pipeline/cards/{card_id}/model",
        headers=AUTH,
        json={"model": "oc-medium"},
    )

    assert response.status_code == 200
    assert response.json()["id"] == card_id
    assert response.json()["model"] == "oc-medium"
    detail = client.get(f"/api/pipeline/cards/{card_id}", headers=AUTH)
    assert detail.status_code == 200
    assert detail.json()["model"] == "oc-medium"


def test_patch_card_model_null_resets(tmp_path) -> None:
    client = _client(tmp_path)
    created = client.post("/api/pipeline/cards", headers=AUTH, json={"title": "Reset model card"})
    assert created.status_code == 201
    card_id = created.json()["id"]
    set_response = client.patch(
        f"/api/pipeline/cards/{card_id}/model",
        headers=AUTH,
        json={"model": "oc-medium"},
    )
    assert set_response.status_code == 200

    response = client.patch(
        f"/api/pipeline/cards/{card_id}/model",
        headers=AUTH,
        json={"model": None},
    )

    assert response.status_code == 200
    assert response.json()["model"] is None


def test_patch_card_model_404(tmp_path) -> None:
    client = _client(tmp_path)

    response = client.patch(
        "/api/pipeline/cards/nonexistent-id/model",
        headers=AUTH,
        json={"model": "oc-medium"},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "card_not_found"


# ---------------------------------------------------------------------------
# GET /api/pipeline/journal
# ---------------------------------------------------------------------------

def test_journal_empty_returns_empty_entries(tmp_path) -> None:
    client = _client(tmp_path)

    response = client.get("/api/pipeline/journal", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["entries"] == []


def test_journal_returns_entries_after_card_enqueued(tmp_path) -> None:
    client = _client(tmp_path)

    # Create a card so a journal entry is appended.
    client.post("/api/pipeline/cards", headers=AUTH, json={"title": "Journal test card"})

    response = client.get("/api/pipeline/journal", headers=AUTH)

    assert response.status_code == 200
    entries = response.json()["entries"]
    assert len(entries) >= 1
    # Most recent entry first.
    assert entries[0]["kind"] in {"intake_added", "intake_refresh"}
    assert "timestamp" in entries[0]
    assert "summary" in entries[0]


def test_journal_filter_by_card_id(tmp_path) -> None:
    client = _client(tmp_path)

    # Create a card so a journal entry is appended.
    card = client.post("/api/pipeline/cards", headers=AUTH, json={"title": "Card filter test"})

    response = client.get(
        f"/api/pipeline/journal?card_id={card.json()['id']}&limit=20",
        headers=AUTH,
    )

    assert response.status_code == 200
    entries = response.json()["entries"]
    # The entry belongs to the newly created card.
    assert all(e["task_id"] == card.json()["id"] for e in entries)


# ---------------------------------------------------------------------------
# POST /api/pipeline/run-next
# ---------------------------------------------------------------------------


def test_run_next_returns_409_when_no_queued_cards(tmp_path) -> None:
    client = _client(tmp_path)

    response = client.post("/api/pipeline/run-next", headers=AUTH)

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "no_queued_cards"


def test_run_next_returns_409_when_already_running(tmp_path) -> None:
    import json

    reg_dir = tmp_path / ".openharness" / "autopilot"
    reg_dir.mkdir(parents=True)
    registry = {
        "updated_at": 0.0,
        "cards": [
            {
                "id": "ap-test-running",
                "fingerprint": "fp-running",
                "title": "In progress card",
                "status": "running",
                "source_kind": "manual_idea",
                "score": 0,
                "labels": [],
                "body": "",
                "created_at": 0.0,
                "updated_at": 0.0,
                "metadata": {},
            },
            {
                "id": "ap-test-queued",
                "fingerprint": "fp-queued",
                "title": "Waiting card",
                "status": "queued",
                "source_kind": "manual_idea",
                "score": 0,
                "labels": [],
                "body": "",
                "created_at": 1.0,
                "updated_at": 1.0,
                "metadata": {},
            },
        ],
    }
    (reg_dir / "registry.json").write_text(json.dumps(registry), encoding="utf-8")

    client = _client(tmp_path)
    response = client.post("/api/pipeline/run-next", headers=AUTH)

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "already_running"


def test_run_next_returns_202_and_task_id_when_queued_card_exists(tmp_path, monkeypatch) -> None:
    from unittest.mock import AsyncMock, MagicMock

    import openharness.webui.server.routes.pipeline as pipeline_routes

    fake_task = MagicMock()
    fake_task.id = "task-stub-001"
    mock_manager = MagicMock()
    mock_manager.create_shell_task = AsyncMock(return_value=fake_task)
    monkeypatch.setattr(pipeline_routes, "get_task_manager", lambda: mock_manager)

    client = _client(tmp_path)
    r = client.post("/api/pipeline/cards", headers=AUTH, json={"title": "Ready to run"})
    assert r.status_code == 201

    response = client.post("/api/pipeline/run-next", headers=AUTH)

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "accepted"
    assert "task_id" in body
    mock_manager.create_shell_task.assert_called_once()
