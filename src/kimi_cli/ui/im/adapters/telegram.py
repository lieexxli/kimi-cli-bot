"""Telegram Bot adapter using aiogram 3.x."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, override

from kimi_cli.ui.im import CallbackHandler, IMAdapter
from kimi_cli.utils.logging import logger

if TYPE_CHECKING:
    from kimi_cli.config import IMConfig


class TelegramAdapter(IMAdapter):
    """
    Telegram Bot adapter.

    Supports two modes:
    - Long polling (default): no server required, works behind NAT
    - Webhook: requires a publicly accessible HTTPS URL

    Requires: pip install kimi-cli[im-telegram]
    (installs aiogram>=3.0,<4.0)

    Configuration:
        token: Bot token from @BotFather (or TELEGRAM_BOT_TOKEN env var)
        webhook_url: Public HTTPS URL for webhook mode (optional)
        webhook_port: Local port for webhook server (default: 8443)
        allowed_chat_ids: Whitelist of chat/user IDs (empty = allow all)
    """

    def __init__(self, im_config: IMConfig) -> None:
        super().__init__()
        self._im_config = im_config
        self._bot = None
        self._dp = None
        self._callback_handlers: dict[int, CallbackHandler] = {}

    def _get_token(self) -> str:
        token = self._im_config.token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if not token:
            raise RuntimeError(
                "Telegram bot token not configured. "
                "Set --im-token or TELEGRAM_BOT_TOKEN environment variable."
            )
        return token

    @override
    def register_callback_handler(self, message_id: int, handler: CallbackHandler) -> None:
        """Register a one-shot handler for an inline keyboard button press."""
        self._callback_handlers[message_id] = handler

    @override
    async def start(self) -> None:
        try:
            from aiogram import Bot, Dispatcher
            from aiogram.filters import CommandStart
            from aiogram.types import CallbackQuery, Message
        except ImportError as e:
            raise RuntimeError(
                "aiogram is required for Telegram integration. "
                "Install with: pip install kimi-cli[im-telegram]"
            ) from e

        token = self._get_token()
        self._bot = Bot(token=token)
        self._dp = Dispatcher()

        from aiogram.filters import Command

        from kimi_cli.ui.im import get_current_im_server
        from kimi_cli.ui.im.commands import (
            handle_cancel,
            handle_start,
            handle_status,
        )

        # Register command handlers FIRST — aiogram matches in registration order,
        # so these must come before the catch-all @self._dp.message() handler.
        @self._dp.message(CommandStart())
        async def handle_start_cmd(message: Message) -> None:  # type: ignore[reportUnusedFunction]
            chat_id = str(message.chat.id)
            server = get_current_im_server()
            if server:
                await handle_start(chat_id, server)
            else:
                await message.answer("Hello! I'm Kimi Code AI assistant.")

        @self._dp.message(Command("cancel"))
        async def on_cancel(message: Message) -> None:  # type: ignore[reportUnusedFunction]
            chat_id = str(message.chat.id)
            server = get_current_im_server()
            if server:
                await handle_cancel(chat_id, server)

        @self._dp.message(Command("status"))
        async def on_status(message: Message) -> None:  # type: ignore[reportUnusedFunction]
            chat_id = str(message.chat.id)
            server = get_current_im_server()
            if server:
                await handle_status(chat_id, server)

        # Catch-all message handler — must be registered AFTER command handlers
        @self._dp.message()
        async def handle_message(message: Message) -> None:  # type: ignore[reportUnusedFunction]
            chat_id = str(message.chat.id)
            user_id = str(message.from_user.id) if message.from_user else chat_id

            if message.photo:
                # Highest resolution is last in the list
                photo = message.photo[-1]
                caption = message.caption or ""
                logger.debug(
                    "Telegram photo from chat={chat_id}: file_id={fid}",
                    chat_id=chat_id,
                    fid=photo.file_id,
                )
                await self._dispatch_photo(chat_id, user_id, photo.file_id, caption)
                return

            if message.text is None:
                return
            text = message.text
            logger.debug(
                "Telegram message from chat={chat_id} user={user_id}: {text}",
                chat_id=chat_id,
                user_id=user_id,
                text=text[:50],
            )
            await self._dispatch_message(chat_id, user_id, text, message.message_id)

        # Register callback_query handler
        @self._dp.callback_query()
        async def handle_callback_query(callback_query: CallbackQuery) -> None:  # type: ignore[reportUnusedFunction]
            if callback_query.message is None:
                await callback_query.answer()
                return
            message_id = callback_query.message.message_id
            handler = self._callback_handlers.pop(message_id, None)
            if handler is not None:
                await handler(callback_query.id, callback_query.data or "")
            else:
                await self.answer_callback_query(callback_query.id, "已过期，请重新操作")

        if self._im_config.webhook_url:
            # Webhook mode
            webhook_url = self._im_config.webhook_url
            port = self._im_config.webhook_port
            logger.info(
                "Starting Telegram webhook on port {port}, URL {url}",
                port=port,
                url=webhook_url,
            )
            from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
            from aiohttp import web

            app = web.Application()
            await self._bot.set_webhook(url=webhook_url)
            webhook_path = "/telegram/webhook"
            SimpleRequestHandler(dispatcher=self._dp, bot=self._bot).register(
                app, path=webhook_path
            )
            setup_application(app, self._dp, bot=self._bot)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "0.0.0.0", port)
            await site.start()
            self._runner = runner
        else:
            # Long polling mode
            logger.info("Starting Telegram long polling")
            # Start polling in background
            import asyncio

            self._polling_task = asyncio.create_task(
                self._dp.start_polling(self._bot, allowed_updates=["message", "callback_query"])  # type: ignore[reportUnknownMemberType]
            )

    async def _dispatch_photo(self, chat_id: str, user_id: str, file_id: str, caption: str) -> None:
        """Download a Telegram photo and dispatch it as a multimodal message."""
        import base64
        import io

        from kosong.message import ImageURLPart, TextPart

        try:
            assert self._bot is not None
            file = await self._bot.get_file(file_id)
            buf = io.BytesIO()
            file_path = file.file_path or ""
            await self._bot.download_file(file_path, buf)
            image_bytes = buf.getvalue()

            if image_bytes[:3] == b"\xff\xd8\xff":
                mime = "image/jpeg"
            elif image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
                mime = "image/png"
            elif image_bytes[:6] in (b"GIF87a", b"GIF89a"):
                mime = "image/gif"
            elif image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
                mime = "image/webp"
            else:
                mime = "image/jpeg"

            b64 = base64.b64encode(image_bytes).decode()
            data_uri = f"data:{mime};base64,{b64}"
            prompt = caption if caption else "[用户发送了一张图片，请分析图片内容]"
            parts = [
                TextPart(text=prompt),
                ImageURLPart(image_url=ImageURLPart.ImageURL(url=data_uri)),
            ]
            await self._dispatch_message(chat_id, user_id, parts)
        except Exception:
            logger.exception("Error dispatching Telegram photo")
            await self.send_message(chat_id, "[图片下载失败]")

    @override
    async def stop(self) -> None:
        if self._bot is None:
            return
        try:
            if self._im_config.webhook_url:
                if hasattr(self, "_runner"):
                    await self._runner.cleanup()
                await self._bot.delete_webhook()
            else:
                if hasattr(self, "_polling_task"):
                    self._polling_task.cancel()
                    import contextlib

                    with contextlib.suppress(Exception):
                        await self._polling_task
            await self._bot.session.close()
        except Exception:
            logger.exception("Error stopping Telegram adapter")

    @override
    async def send_message(self, chat_id: str, text: str) -> int | None:
        if self._bot is None:
            logger.warning("Cannot send Telegram message: bot not started")
            return None
        try:
            msg = await self._bot.send_message(chat_id=int(chat_id), text=text)
            return msg.message_id
        except Exception:
            logger.exception(
                "Failed to send Telegram message to chat_id={chat_id}", chat_id=chat_id
            )
            return None

    async def send_message_with_keyboard(
        self,
        chat_id: str,
        text: str,
        keyboard: list[list[tuple[str, str]]],
    ) -> int | None:
        """Send a message with InlineKeyboard. keyboard[row][col] = (label, callback_data)."""
        if self._bot is None:
            logger.warning("Cannot send Telegram message: bot not started")
            return None
        try:
            from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

            buttons = [
                [InlineKeyboardButton(text=label, callback_data=data) for label, data in row]
                for row in keyboard
            ]
            markup = InlineKeyboardMarkup(inline_keyboard=buttons)
            msg = await self._bot.send_message(chat_id=int(chat_id), text=text, reply_markup=markup)
            return msg.message_id
        except Exception:
            logger.exception(
                "Failed to send Telegram keyboard message to chat_id={chat_id}", chat_id=chat_id
            )
            return None

    @override
    async def edit_message(
        self, chat_id: str, message_id: int, text: str, remove_keyboard: bool = False
    ) -> None:
        if self._bot is None:
            return
        try:
            from aiogram.types import InlineKeyboardMarkup

            reply_markup = InlineKeyboardMarkup(inline_keyboard=[]) if remove_keyboard else None
            await self._bot.edit_message_text(
                chat_id=int(chat_id),
                message_id=message_id,
                text=text,
                reply_markup=reply_markup,
            )
        except Exception:
            logger.exception(
                "Failed to edit Telegram message {message_id} in chat_id={chat_id}",
                message_id=message_id,
                chat_id=chat_id,
            )

    @override
    async def send_chat_action(self, chat_id: str, action: str = "typing") -> None:
        if self._bot is None:
            return
        try:
            await self._bot.send_chat_action(chat_id=int(chat_id), action=action)  # type: ignore[arg-type]
        except Exception:
            logger.exception("Failed to send chat action to chat_id={chat_id}", chat_id=chat_id)

    @override
    async def answer_callback_query(self, callback_query_id: str, text: str = "") -> None:
        if self._bot is None:
            return
        try:
            await self._bot.answer_callback_query(
                callback_query_id=callback_query_id,
                text=text or None,
            )
        except Exception:
            logger.exception("Failed to answer callback_query {cqid}", cqid=callback_query_id)

    async def set_message_reaction(self, chat_id: str, message_id: int, emoji: str) -> None:
        """Set an emoji reaction on a message (Bot API 7.0+). Silently ignores errors."""
        if self._bot is None:
            return
        try:
            from aiogram.enums import ReactionTypeType
            from aiogram.types import ReactionTypeEmoji

            await self._bot.set_message_reaction(
                chat_id=int(chat_id),
                message_id=message_id,
                reaction=[ReactionTypeEmoji(type=ReactionTypeType.EMOJI, emoji=emoji)],
            )
        except Exception:
            logger.debug(
                "set_message_reaction failed for chat_id={chat_id} (may not be supported)",
                chat_id=chat_id,
            )
