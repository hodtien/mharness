from __future__ import annotations

from fastapi.testclient import TestClient

from openharness.api.usage import UsageSnapshot
from openharness.engine.messages import ConversationMessage, ToolResultBlock, ToolUseBlock
from openharness.services.session_storage import save_session_snapshot
from openharness.webui.server.app import create_app

AUTH = {"Authorization": "Bearer test-token"}


def _client(tmp_path, *, token: str = "test-token") -> TestClient:
    return TestClient(create_app(token=token, cwd=tmp_path, model="sonnet"))


def test_get_history_detail_returns_messages_list(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))
    save_session_snapshot(
        cwd=tmp_path,
        model="sonnet",
        system_prompt="system",
        messages=[ConversationMessage.from_user_text("hello")],
        usage=UsageSnapshot(),
        session_id="sess-001",
    )
    client = _client(tmp_path)

    response = client.get("/api/history/sess-001", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == "sess-001"
    assert body["model"] == "sonnet"
    assert body["cwd"] == str(tmp_path.resolve())
    assert isinstance(body["messages"], list)
    assert body["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "hello"}]},
    ]


def test_get_history_detail_short_tool_result_not_truncated(tmp_path, monkeypatch) -> None:
    """tool_result content at or below the 500-char threshold is left intact."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))
    short_output = "x" * 500
    save_session_snapshot(
        cwd=tmp_path,
        model="sonnet",
        system_prompt="system",
        messages=[
            ConversationMessage.from_user_text("run"),
            ConversationMessage(
                role="assistant",
                content=[ToolUseBlock(id="toolu_1", name="bash", input={})],
            ),
            ConversationMessage.from_user_content(
                [ToolResultBlock(tool_use_id="toolu_1", content=short_output)]
            ),
        ],
        usage=UsageSnapshot(),
        session_id="sess-001",
    )
    client = _client(tmp_path)

    response = client.get("/api/history/sess-001", headers=AUTH)

    assert response.status_code == 200
    body = response.json()["messages"]
    blocks = [b for msg in body for b in msg["content"] if b.get("type") == "tool_result"]
    assert len(blocks) == 1
    assert blocks[0]["content"] == short_output
    assert "truncated" not in blocks[0]
    assert "original_length" not in blocks[0]


def test_get_history_detail_truncates_long_tool_results(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))
    long_output = "x" * 550
    save_session_snapshot(
        cwd=tmp_path,
        model="sonnet",
        system_prompt="system",
        messages=[
            ConversationMessage.from_user_text("run the command"),
            ConversationMessage(
                role="assistant",
                content=[ToolUseBlock(id="toolu_1", name="bash", input={"command": "echo hi"})],
            ),
            ConversationMessage.from_user_content(
                [ToolResultBlock(tool_use_id="toolu_1", content=long_output)]
            ),
        ],
        usage=UsageSnapshot(),
        session_id="sess-001",
    )
    client = _client(tmp_path)

    response = client.get("/api/history/sess-001", headers=AUTH)

    assert response.status_code == 200
    body = response.json()["messages"]
    # Find the message that contains the tool_result block
    tool_result_block = None
    for msg in body:
        for block in msg.get("content", []):
            if block.get("type") == "tool_result":
                tool_result_block = block
                break
        if tool_result_block:
            break
    assert tool_result_block is not None, f"No tool_result found in {body}"
    assert tool_result_block["content"] == f'{"x" * 500}… [truncated 50 chars]'
    assert tool_result_block["truncated"] is True
    assert tool_result_block["original_length"] == 550


def test_get_history_detail_unknown_id_returns_404(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))
    client = _client(tmp_path)

    response = client.get("/api/history/missing", headers=AUTH)

    assert response.status_code == 404
