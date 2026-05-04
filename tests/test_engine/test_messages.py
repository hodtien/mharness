from __future__ import annotations

from openharness.engine.messages import (
    ConversationMessage,
    ImageBlock,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    deserialize_content_block,
    deserialize_conversation_message,
    sanitize_conversation_messages,
    serialize_content_block,
    serialize_conversation_message,
)


def test_sanitize_conversation_messages_keeps_complete_tool_turn():
    messages = [
        ConversationMessage.from_user_text("edit the file"),
        ConversationMessage(
            role="assistant",
            content=[ToolUseBlock(id="write_file:234", name="write_file", input={"path": "x"})],
        ),
        ConversationMessage(
            role="user",
            content=[ToolResultBlock(tool_use_id="write_file:234", content="ok", is_error=False)],
        ),
    ]

    sanitized = sanitize_conversation_messages(messages)

    assert sanitized == messages


def test_sanitize_conversation_messages_drops_dangling_trailing_tool_use():
    messages = [
        ConversationMessage.from_user_text("edit the file"),
        ConversationMessage(
            role="assistant",
            content=[ToolUseBlock(id="write_file:234", name="write_file", input={"path": "x"})],
        ),
    ]

    sanitized = sanitize_conversation_messages(messages)

    assert sanitized == [ConversationMessage.from_user_text("edit the file")]


def test_sanitize_conversation_messages_drops_orphan_tool_results_but_keeps_user_text():
    messages = [
        ConversationMessage.from_user_text("hello"),
        ConversationMessage(
            role="user",
            content=[
                ToolResultBlock(tool_use_id="missing_call", content="stale", is_error=True),
                TextBlock(text="new prompt"),
            ],
        ),
    ]

    sanitized = sanitize_conversation_messages(messages)

    assert sanitized == [
        ConversationMessage.from_user_text("hello"),
        ConversationMessage(role="user", content=[TextBlock(text="new prompt")]),
    ]


def test_deserialize_round_trips_text_block():
    block = TextBlock(text="hello world")
    restored = deserialize_content_block(serialize_content_block(block))
    assert restored == block


def test_deserialize_round_trips_image_block():
    block = ImageBlock(media_type="image/png", data="aGVsbG8=", source_path="/tmp/foo.png")
    raw = serialize_content_block(block)
    restored = deserialize_content_block(raw)
    assert isinstance(restored, ImageBlock)
    assert restored.media_type == block.media_type
    assert restored.data == block.data


def test_deserialize_round_trips_tool_use_block():
    block = ToolUseBlock(id="toolu_abc", name="bash", input={"cmd": "ls", "n": 3})
    restored = deserialize_content_block(serialize_content_block(block))
    assert restored == block


def test_deserialize_round_trips_tool_result_block():
    block = ToolResultBlock(tool_use_id="toolu_abc", content="ok", is_error=False)
    restored = deserialize_content_block(serialize_content_block(block))
    assert restored == block


def test_deserialize_round_trips_full_conversation():
    messages = [
        ConversationMessage.from_user_text("please run ls"),
        ConversationMessage(
            role="assistant",
            content=[
                TextBlock(text="Running it now."),
                ToolUseBlock(id="toolu_1", name="bash", input={"cmd": "ls"}),
            ],
        ),
        ConversationMessage(
            role="user",
            content=[ToolResultBlock(tool_use_id="toolu_1", content="file.txt", is_error=False)],
        ),
    ]
    raw = [serialize_conversation_message(m) for m in messages]
    restored = [deserialize_conversation_message(r) for r in raw]
    assert restored == messages
