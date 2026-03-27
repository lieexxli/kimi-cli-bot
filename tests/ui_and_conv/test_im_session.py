"""Tests for IMSession cancel_event promotion and loop detection."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from kimi_cli.ui.im.session import IMSession


def _make_session(loop_threshold: int = 5) -> IMSession:
    """Create a minimal IMSession for testing (no real KimiCLI/IMServer needed)."""
    im_config = MagicMock()
    im_config.work_dir = "."
    im_config.model_name = None
    im_config.default_mode = "suggest"
    im_config.admin_chat_ids = []
    im_config.ack_reaction = ""
    im_config.loop_detection_threshold = loop_threshold
    im_config.output_masking_enabled = False

    server = MagicMock()
    server.send_to_chat = AsyncMock(return_value=1)
    server.register_callback_handler = MagicMock()

    config = MagicMock()

    return IMSession(
        chat_id="test_chat",
        server=server,
        im_config=im_config,
        config=config,
    )


def test_cancel_event_is_none_initially():
    session = _make_session()
    assert session._current_cancel is None


@pytest.mark.asyncio
async def test_cancel_when_no_turn_running_sends_message():
    session = _make_session()
    await session.cancel_current_turn()
    session._server.send_to_chat.assert_called_once_with(  # type: ignore[union-attr]
        "test_chat", "当前没有正在运行的任务。"
    )


@pytest.mark.asyncio
async def test_cancel_during_turn_sets_event():
    session = _make_session()
    event = asyncio.Event()
    session._current_cancel = event
    await session.cancel_current_turn()
    assert event.is_set()


def test_loop_detection_not_triggered_below_threshold():
    session = _make_session(loop_threshold=3)
    assert session._check_and_update_loop_counter("bash") is False
    assert session._check_and_update_loop_counter("bash") is False


def test_loop_detection_triggered_at_threshold():
    session = _make_session(loop_threshold=3)
    session._check_and_update_loop_counter("bash")
    session._check_and_update_loop_counter("bash")
    assert session._check_and_update_loop_counter("bash") is True


def test_loop_detection_resets_on_different_tool():
    session = _make_session(loop_threshold=3)
    session._check_and_update_loop_counter("bash")
    session._check_and_update_loop_counter("bash")
    assert session._check_and_update_loop_counter("read_file") is False
    assert session._check_and_update_loop_counter("bash") is False


def test_loop_detection_counter_clears_after_turn():
    session = _make_session(loop_threshold=3)
    session._check_and_update_loop_counter("bash")
    session._check_and_update_loop_counter("bash")
    session._reset_loop_counter()
    assert session._check_and_update_loop_counter("bash") is False


# ---------------------------------------------------------------------------
# _split_message tests
# ---------------------------------------------------------------------------

from kimi_cli.ui.im.session import _split_message  # noqa: E402


def test_split_message_short_returns_single_chunk():
    text = "Hello, world!"
    assert _split_message(text, max_chars=100) == [text]


def test_split_message_exact_limit_returns_single_chunk():
    text = "a" * 100
    assert _split_message(text, max_chars=100) == [text]


def test_split_message_splits_on_newline():
    # Two lines, each under limit, but together over it
    line_a = "a" * 60 + "\n"
    line_b = "b" * 60 + "\n"
    chunks = _split_message(line_a + line_b, max_chars=100)
    assert len(chunks) == 2
    assert chunks[0] == line_a
    assert chunks[1] == line_b


def test_split_message_hard_splits_oversized_line():
    # Single line longer than max_chars — must be hard-split
    text = "x" * 250
    chunks = _split_message(text, max_chars=100)
    assert len(chunks) == 3
    assert all(len(c) <= 100 for c in chunks)
    assert "".join(chunks) == text


def test_split_message_preserves_content():
    text = "line1\nline2\nline3\n"
    chunks = _split_message(text, max_chars=8)
    assert "".join(chunks) == text


def test_split_message_unicode_not_truncated():
    # Chinese characters: each is 1 char but potentially multi-byte
    text = "你好世界\n" * 20
    chunks = _split_message(text, max_chars=20)
    assert "".join(chunks) == text
    assert all(len(c) <= 20 for c in chunks)
