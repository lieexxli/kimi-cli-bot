"""IM (Instant Messaging) UI for kimi-cli.

Supports Telegram bots with bidirectional communication:
- Users can chat with the AI agent via IM
- The agent can proactively send notifications via SendIMNotification tool
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Coroutine
from typing import TYPE_CHECKING

from kimi_cli.ui.im._utils import split_message as _split_message
from kimi_cli.utils.logging import logger

if TYPE_CHECKING:
    from kimi_cli.config import Config, IMConfig
    from kimi_cli.ui.im.session import IMSession

# Module-level singleton: the currently running IMServer instance.
# Used by SendIMNotification tool to send messages.
_current_server: IMServer | None = None


def get_current_im_server() -> IMServer | None:
    """Get the currently running IMServer instance (if any)."""
    return _current_server


UserInput = Any  # str | list[ContentPart]
OnMessageCallback = Callable[[str, str, UserInput, int | None], Coroutine[Any, Any, None]]
"""Callback type: (chat_id, user_id, text_or_parts, message_id) -> None"""

CallbackHandler = Callable[[str, str], Awaitable[None]]
"""Inline keyboard callback: (callback_query_id, callback_data) -> None"""


class IMAdapter(ABC):
    """Abstract base class for IM platform adapters."""

    def __init__(self) -> None:
        self._on_message: OnMessageCallback | None = None

    def set_on_message_callback(self, callback: OnMessageCallback) -> None:
        """Register the callback to be called when a message is received."""
        self._on_message = callback

    def register_callback_handler(self, message_id: int, handler: CallbackHandler) -> None:  # noqa: B027
        """Register a one-shot inline keyboard callback handler for the given message_id.
        Default implementation is a no-op; override in adapters that support inline keyboards.
        """

    def unregister_callback_handler(self, message_id: int) -> None:  # noqa: B027
        """Remove a pending callback handler without invoking it (e.g. after timeout).
        Default implementation is a no-op; override in adapters that support inline keyboards.
        """

    async def _dispatch_message(
        self, chat_id: str, user_id: str, text: UserInput, message_id: int | None = None
    ) -> None:
        """Called by subclasses to dispatch an incoming message."""
        if self._on_message is not None:
            await self._on_message(chat_id, user_id, text, message_id)

    @abstractmethod
    async def start(self) -> None:
        """Start listening for incoming messages."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop the adapter and clean up resources."""

    @abstractmethod
    async def send_message(self, chat_id: str, text: str) -> int | None:
        """Send a text message to the given chat/user. Returns message_id if available."""

    @abstractmethod
    async def edit_message(
        self, chat_id: str, message_id: int, text: str, remove_keyboard: bool = False
    ) -> None:
        """Edit a previously sent message (used for streaming output).
        remove_keyboard=True removes inline keyboard from the message.
        """

    @abstractmethod
    async def send_chat_action(self, chat_id: str, action: str = "typing") -> None:
        """Send a chat action indicator (e.g. typing...)."""

    @abstractmethod
    async def answer_callback_query(self, callback_query_id: str, text: str = "") -> None:
        """Acknowledge an inline keyboard button press (clears the loading spinner)."""


class IMServer:
    """
    Manages IM bot sessions and routes messages between users and AI agent instances.

    Each unique chat_id gets its own KimiCLI instance (separate AI context).
    Uses the work_dir configuration to determine the working directory for sessions.
    """

    def __init__(
        self,
        adapter: IMAdapter,
        im_config: IMConfig,
        config: Config,
    ) -> None:
        self._adapter = adapter
        self._im_config = im_config
        self._config = config
        self._sessions: dict[str, IMSession] = {}

    @property
    def adapter(self) -> IMAdapter:
        """Return the underlying IM adapter."""
        return self._adapter

    @property
    def im_config(self) -> IMConfig:
        """Return the IM configuration."""
        return self._im_config

    @property
    def default_model(self) -> str:
        """Return the effective model name (IM override or global default)."""
        return self._im_config.model_name or self._config.default_model or "unknown"

    def get_session(self, chat_id: str) -> IMSession | None:
        """Return the IMSession for *chat_id*, or None if not active."""
        return self._sessions.get(chat_id)

    def active_chat_ids(self) -> list[str]:
        """Return chat IDs that currently have a turn in progress."""
        return [cid for cid, s in self._sessions.items() if s._turn_running]

    async def send_to_chat(self, chat_id: str, text: str) -> int | None:
        """Send a message to a chat (SendIMNotification). Returns message_id if available.

        Long messages are automatically split to stay within IM platform limits.
        """
        chunks = _split_message(text)
        last_id: int | None = None
        for chunk in chunks:
            last_id = await self._adapter.send_message(chat_id, chunk)
        return last_id

    def register_callback_handler(self, message_id: int, handler: CallbackHandler) -> None:
        """Delegate to adapter."""
        self._adapter.register_callback_handler(message_id, handler)

    def unregister_callback_handler(self, message_id: int) -> None:
        """Remove a pending callback handler (e.g. after approval timeout)."""
        self._adapter.unregister_callback_handler(message_id)

    async def edit_chat_message(
        self, chat_id: str, message_id: int, text: str, remove_keyboard: bool = False
    ) -> None:
        """Edit a previously sent message. Used for streaming output."""
        await self._adapter.edit_message(chat_id, message_id, text, remove_keyboard)

    async def run(self) -> None:
        """Start the IM server and block until cancelled."""
        global _current_server
        _current_server = self
        cleanup_task: asyncio.Task | None = None
        try:
            self._adapter.set_on_message_callback(self._on_message)
            await self._adapter.start()
            logger.info(
                "IM server started (platform={platform})",
                platform=self._im_config.platform,
            )
            if self._im_config.session_idle_timeout > 0:
                cleanup_task = asyncio.create_task(self._idle_cleanup_loop())
            # Block until cancelled
            await asyncio.get_running_loop().create_future()
        except asyncio.CancelledError:
            logger.info("IM server stopping...")
        finally:
            if cleanup_task is not None:
                cleanup_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await cleanup_task
            _current_server = None
            await self._adapter.stop()
            logger.info("IM server stopped")

    async def _idle_cleanup_loop(self) -> None:
        """Periodically evict sessions that have been idle too long.

        Evicted sessions are removed from memory only; their context.json persists on
        disk and will be reloaded automatically on the next incoming message.
        """
        timeout = self._im_config.session_idle_timeout
        while True:
            await asyncio.sleep(60)  # check every minute
            now = time.monotonic()
            idle_ids = [
                cid
                for cid, s in list(self._sessions.items())
                if not s._turn_running and (now - s._last_activity) > timeout
            ]
            for cid in idle_ids:
                del self._sessions[cid]
                logger.info(
                    "IM session {chat_id} evicted (idle > {timeout}s)",
                    chat_id=cid,
                    timeout=timeout,
                )

    async def _on_message(
        self, chat_id: str, user_id: str, text: UserInput, message_id: int | None = None
    ) -> None:
        """Dispatch an incoming IM message to the appropriate session."""
        allowed = self._im_config.allowed_chat_ids
        if allowed and chat_id not in allowed:
            logger.warning("Ignoring message from non-allowed chat_id={chat_id}", chat_id=chat_id)
            await self._adapter.send_message(
                chat_id, "Sorry, you are not authorized to use this bot."
            )
            return

        if chat_id not in self._sessions:
            from kimi_cli.ui.im.session import IMSession

            self._sessions[chat_id] = IMSession(
                chat_id=chat_id,
                server=self,
                im_config=self._im_config,
                config=self._config,
            )
        session = self._sessions[chat_id]
        await session.handle_message(text, message_id=message_id)
