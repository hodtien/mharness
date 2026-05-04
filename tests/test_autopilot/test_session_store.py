"""Tests for the autopilot session checkpoint store."""

from __future__ import annotations

from pathlib import Path

from openharness.autopilot.session_store import (
    clear_checkpoints,
    load_latest_checkpoint,
    restore_messages,
    save_checkpoint,
)
from openharness.engine.messages import (
    ConversationMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)


def _make_messages() -> list[ConversationMessage]:
    return [
        ConversationMessage.from_user_text("implement the feature"),
        ConversationMessage(
            role="assistant",
            content=[
                TextBlock(text="On it."),
                ToolUseBlock(id="toolu_a", name="bash", input={"cmd": "ls"}),
            ],
        ),
        ConversationMessage(
            role="user",
            content=[ToolResultBlock(tool_use_id="toolu_a", content="ok", is_error=False)],
        ),
    ]


def test_save_and_load_latest_checkpoint(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    card_id = "card-ckpt-01"
    messages = _make_messages()

    save_checkpoint(
        runs_dir, card_id, phase="implement", attempt=1,
        model="claude-sonnet-4-6", permission_mode="full_auto",
        cwd="/tmp/repo", messages=messages, has_pending_continuation=True,
    )
    save_checkpoint(
        runs_dir, card_id, phase="implement", attempt=2,
        model="claude-sonnet-4-6", permission_mode="full_auto",
        cwd="/tmp/repo", messages=messages, has_pending_continuation=False,
    )

    ckpt = load_latest_checkpoint(runs_dir, card_id)
    assert ckpt is not None
    assert ckpt.attempt == 2
    assert ckpt.phase == "implement"
    assert ckpt.has_pending_continuation is False
    assert ckpt.model == "claude-sonnet-4-6"


def test_load_latest_checkpoint_returns_none_when_empty(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    assert load_latest_checkpoint(runs_dir, "nonexistent") is None


def test_clear_checkpoints_removes_all_files(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    card_id = "card-ckpt-02"
    messages = _make_messages()

    save_checkpoint(
        runs_dir, card_id, phase="implement", attempt=1,
        model=None, permission_mode="default",
        cwd="/tmp", messages=messages, has_pending_continuation=True,
    )
    save_checkpoint(
        runs_dir, card_id, phase="implement", attempt=2,
        model=None, permission_mode="default",
        cwd="/tmp", messages=messages, has_pending_continuation=True,
    )

    assert load_latest_checkpoint(runs_dir, card_id) is not None

    clear_checkpoints(runs_dir, card_id)

    assert load_latest_checkpoint(runs_dir, card_id) is None


def test_restore_messages_round_trips(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    card_id = "card-ckpt-03"
    original = _make_messages()

    save_checkpoint(
        runs_dir, card_id, phase="implement", attempt=1,
        model="claude-sonnet-4-6", permission_mode="full_auto",
        cwd="/tmp/repo", messages=original, has_pending_continuation=True,
    )

    ckpt = load_latest_checkpoint(runs_dir, card_id)
    assert ckpt is not None

    restored = restore_messages(ckpt)
    assert len(restored) == len(original)
    for orig, rest in zip(original, restored):
        assert orig.role == rest.role
        assert len(orig.content) == len(rest.content)
        for ob, rb in zip(orig.content, rest.content):
            assert type(ob) is type(rb)
            if isinstance(ob, TextBlock):
                assert ob.text == rb.text
            elif isinstance(ob, ToolUseBlock):
                assert ob.id == rb.id
                assert ob.name == rb.name
                assert ob.input == rb.input
            elif isinstance(ob, ToolResultBlock):
                assert ob.tool_use_id == rb.tool_use_id
                assert ob.content == rb.content
                assert ob.is_error == rb.is_error
