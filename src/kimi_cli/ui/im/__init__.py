"""IM (Instant Messaging) UI for kimi-cli.

Supports Telegram bots with bidirectional communication:
- Users can chat with the AI agent via IM
- The agent can proactively send notifications via SendIMNotification tool
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Coroutine
from typing import TYPE_CHECKING, Any

from kimi_cli.utils.logging import logger

if TYPE_CHECKING:
    from kimi_cli.config import Config, IMConfig

# Module-level singleton: the currently running IMServer instance.
# Used by SendIMNotification tool to send messages.
_current_server: IMServer | None = None


def get_current_im_server() -> IMServer | None:
    """Get the currently running IMServer instance (if any)."""
    return _current_server


UserInput = Any  # str | list[ContentPart]
OnMessageCallback = Callable[[str, str, UserInput], Coroutine[Any, Any, None]]
"""Callback type: (chat_id, user_id, text_or_parts) -> None"""

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

    async def _dispatch_message(self, chat_id: str, user_id: str, text: UserInput) -> None:
        """Called by subclasses to dispatch an incoming message (text or multimodal parts)."""
        if self._on_message is not None:
            await self._on_message(chat_id, user_id, text)

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
        self._sessions: dict[str, Any] = {}  # chat_id -> IMSession

    def active_chat_ids(self) -> list[str]:
        """Return the list of currently active chat IDs."""
        return list(self._sessions.keys())

    async def send_to_chat(self, chat_id: str, text: str) -> int | None:
        """Send a message to a chat (SendIMNotification). Returns message_id if available."""
        return await self._adapter.send_message(chat_id, text)

    def register_callback_handler(self, message_id: int, handler: CallbackHandler) -> None:
        """Delegate to adapter."""
        self._adapter.register_callback_handler(message_id, handler)

    async def run(self) -> None:
        """Start the IM server and block until cancelled."""
        global _current_server
        _current_server = self
        try:
            self._adapter.set_on_message_callback(self._on_message)
            await self._adapter.start()
            logger.info(
                "IM server started (platform={platform})",
                platform=self._im_config.platform,
            )
            # Block until cancelled
            await asyncio.get_event_loop().create_future()
        except asyncio.CancelledError:
            logger.info("IM server stopping...")
        finally:
            _current_server = None
            await self._adapter.stop()
            logger.info("IM server stopped")

    async def _on_message(self, chat_id: str, user_id: str, text: UserInput) -> None:
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
        await session.handle_message(text)
