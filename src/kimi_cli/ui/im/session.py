"""Per-user IM session management."""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING

from kosong.message import ImageURLPart, TextPart, ThinkPart

from kimi_cli.utils.logging import logger
from kimi_cli.wire.types import (
    ApprovalRequest,
    ContentPart,
    QuestionRequest,
    TurnEnd,
)

UserInput = str | list[ContentPart]

if TYPE_CHECKING:
    from kimi_cli.app import KimiCLI
    from kimi_cli.config import Config, IMConfig
    from kimi_cli.ui.im import IMServer

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif"}
_IMAGE_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/bmp",
    "image/tiff",
}
_URL_RE = re.compile(r"^https?://\S+$")

# Maximum characters per IM message before splitting
_MAX_MSG_CHARS = 4000


async def _maybe_convert_image_url(text: str) -> UserInput:
    """If the message is a bare image URL, return multimodal parts; otherwise return as-is."""
    url = text.strip()
    if not _URL_RE.match(url):
        return text
    # Extract actual image URL from Google imgres pages
    if "google.com/imgres" in url:
        from urllib.parse import parse_qs, urlparse

        qs = parse_qs(urlparse(url).query)
        imgurl = qs.get("imgurl", [None])[0]
        if imgurl:
            url = imgurl
    # Check extension first (fast path)
    path = url.split("?")[0].lower()
    ext = "." + path.rsplit(".", 1)[-1] if "." in path else ""
    if ext in _IMAGE_EXTENSIONS:
        return [
            TextPart(text="[用户发送了一张图片，请分析图片内容]"),
            ImageURLPart(image_url=ImageURLPart.ImageURL(url=url)),
        ]
    # Unknown extension: do a HEAD request to check Content-Type
    try:
        import httpx

        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(
            None, lambda: httpx.head(url, follow_redirects=True, timeout=5)
        )
        content_type = resp.headers.get("content-type", "").split(";")[0].strip()
        if content_type in _IMAGE_CONTENT_TYPES:
            return [
                TextPart(text="[用户发送了一张图片，请分析图片内容]"),
                ImageURLPart(image_url=ImageURLPart.ImageURL(url=url)),
            ]
    except Exception:
        pass
    return text


def _split_message(text: str, max_chars: int = _MAX_MSG_CHARS) -> list[str]:
    """Split a long message into chunks that fit within IM limits."""
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    while text:
        chunk = text[:max_chars]
        chunks.append(chunk)
        text = text[max_chars:]
    return chunks


class IMSession:
    """
    Manages a single IM conversation session tied to one chat_id.

    Each session holds its own KimiCLI instance (separate AI context/history).
    Messages from the user are queued; one turn runs at a time.
    Approval/Question requests pause the turn and wait for the next user message.
    """

    def __init__(
        self,
        chat_id: str,
        server: IMServer,
        im_config: IMConfig,
        config: Config,
    ) -> None:
        self._chat_id = chat_id
        self._server = server
        self._im_config = im_config
        self._config = config
        self._kimi: KimiCLI | None = None
        # Queue of incoming user messages (str or multimodal list[ContentPart])
        self._message_queue: asyncio.Queue[UserInput] = asyncio.Queue()
        # Whether a turn is currently running
        self._turn_running = False

    async def handle_message(self, text: UserInput) -> None:
        """
        Called when the user sends a message.
        Queues the message and starts a turn if none is running.
        """
        await self._message_queue.put(text)
        if not self._turn_running:
            asyncio.create_task(self._run_next_turn())

    async def _run_next_turn(self) -> None:
        """Dequeue the next user message and run one AI turn."""
        self._turn_running = True
        try:
            text = await self._message_queue.get()
            await self._run_turn(text)  # type: ignore[arg-type]
        except Exception:
            logger.exception(
                "Unexpected error in IM session turn for chat_id={chat_id}",
                chat_id=self._chat_id,
            )
        finally:
            self._turn_running = False
            # If more messages are queued, process the next one
            if not self._message_queue.empty():
                asyncio.create_task(self._run_next_turn())

    async def _get_kimi(self) -> KimiCLI:
        """Lazily create or return the existing KimiCLI instance for this session."""
        if self._kimi is None:
            from pathlib import Path

            from kaos.path import KaosPath

            from kimi_cli.app import KimiCLI
            from kimi_cli.session import Session

            # Each chat_id gets its own subdirectory so histories stay isolated
            work_dir_path = (
                Path(self._im_config.work_dir).expanduser().resolve() / "sessions" / self._chat_id
            )
            work_dir_path.mkdir(parents=True, exist_ok=True)
            work_dir = KaosPath.unsafe_from_local_path(work_dir_path)

            # Continue previous session (auto-compaction handles long context)
            session = await Session.continue_(work_dir) or await Session.create(work_dir)
            logger.info(
                "IM session {chat_id}: using kimi session {session_id}",
                chat_id=self._chat_id,
                session_id=session.id,
            )
            # Persist last_session_id so continue_() works after bot restart
            from kimi_cli.metadata import load_metadata, save_metadata

            _meta = load_metadata()
            _wd_meta = _meta.get_work_dir_meta(work_dir)
            if _wd_meta is not None:
                _wd_meta.last_session_id = session.id
                save_metadata(_meta)
            self._kimi = await KimiCLI.create(
                session,
                config=self._config,
                model_name=self._im_config.model_name,
                yolo=True,  # IM mode: no interactive terminal for approvals
            )
        return self._kimi

    async def _run_turn(self, user_input: UserInput) -> None:
        """Run one AI turn and send the response back via IM."""
        # /new is an IM-friendly alias for /clear (text only)
        if isinstance(user_input, str) and user_input.strip().lower() in ("/new", "/new "):
            user_input = "/clear"
        # If the message is a bare URL pointing to an image, dispatch it as an image
        elif isinstance(user_input, str):
            user_input = await _maybe_convert_image_url(user_input)
        # Inject language instruction into every turn
        if isinstance(user_input, str) and not user_input.startswith("/"):
            user_input = f"[请用中文回复]\n{user_input}"
        elif isinstance(user_input, list):
            from kosong.message import TextPart as _TextPart

            user_input = [_TextPart(text="[请用中文回复]")] + list(user_input)
        try:
            kimi = await self._get_kimi()
        except Exception:
            logger.exception(
                "Failed to initialize KimiCLI for chat_id={chat_id}",
                chat_id=self._chat_id,
            )
            await self._send("Sorry, I encountered an error starting the AI session.")
            return

        cancel_event = asyncio.Event()
        text_buffer: list[str] = []

        try:
            async for msg in kimi.run(user_input, cancel_event, merge_wire_messages=True):  # type: ignore[arg-type]
                match msg:
                    case ContentPart() as cp:
                        # ContentPart is a union base; each instance IS a specific part type
                        if isinstance(cp, ThinkPart):
                            pass  # skip internal thinking
                        elif isinstance(cp, TextPart):
                            text_buffer.append(cp.text)

                    case TurnEnd():
                        # Flush accumulated text to IM
                        if text_buffer:
                            full_text = "".join(text_buffer)
                            for chunk in _split_message(full_text):
                                await self._send(chunk)
                            text_buffer.clear()

                    case ApprovalRequest() as req:
                        # Flush any buffered text first
                        if text_buffer:
                            await self._send("".join(text_buffer))
                            text_buffer.clear()
                        await self._handle_approval(req)

                    case QuestionRequest() as req:
                        # Flush any buffered text first
                        if text_buffer:
                            await self._send("".join(text_buffer))
                            text_buffer.clear()
                        await self._handle_question(req)

                    case _:
                        pass

        except asyncio.CancelledError:
            cancel_event.set()
            await self._send("[Cancelled]")
        except Exception as e:
            logger.exception("Error during IM AI turn for chat_id={chat_id}", chat_id=self._chat_id)
            # Flush whatever we have
            if text_buffer:
                await self._send("".join(text_buffer))
                text_buffer.clear()
            await self._send(f"[Error] {e}")

    async def _handle_approval(self, req: ApprovalRequest) -> None:
        """Forward an approval request to the user and wait for their response."""
        display_lines: list[str] = [
            "⚠️ Action requires approval",
            f"Tool: {req.sender}",
            f"Action: {req.action}",
        ]
        if req.description:
            display_lines.append(req.description)
        display_lines.append("\nReply 'yes' to approve or 'no' to reject.")
        await self._send("\n".join(display_lines))

        reply = await self._wait_for_user_reply(timeout=120.0)
        if reply is None:
            req.resolve("reject", feedback="Timed out waiting for approval.")
        elif reply.lower().strip() in ("yes", "y", "approve", "ok", "1"):
            req.resolve("approve")
        else:
            req.resolve("reject", feedback=reply.strip())

    async def _handle_question(self, req: QuestionRequest) -> None:
        """Forward a question request to the user and wait for their response."""
        lines: list[str] = []
        for item in req.questions:
            lines.append(f"❓ {item.question}")
            if item.body:
                lines.append(item.body)
            for idx, opt in enumerate(item.options, 1):
                desc = f" — {opt.description}" if opt.description else ""
                lines.append(f"  {idx}. {opt.label}{desc}")
        lines.append("\nReply with your choice (number or text).")
        await self._send("\n".join(lines))

        reply = await self._wait_for_user_reply(timeout=180.0)
        if reply is None:
            # Timeout: pick first option as default
            answers = {
                item.question: (item.options[0].label if item.options else "Other")
                for item in req.questions
            }
        else:
            # Try to parse a number, otherwise use raw text as "Other"
            answers: dict[str, str] = {}
            for item in req.questions:
                text = reply.strip()
                try:
                    idx = int(text) - 1
                    if 0 <= idx < len(item.options):
                        answers[item.question] = item.options[idx].label
                    else:
                        answers[item.question] = text
                except ValueError:
                    answers[item.question] = text
        req.resolve(answers)

    async def _wait_for_user_reply(self, timeout: float = 120.0) -> str | None:
        """Wait for the next message from the user queue, with a timeout."""
        try:
            result = await asyncio.wait_for(self._message_queue.get(), timeout=timeout)
        except TimeoutError:
            return None
        if isinstance(result, str):
            return result
        # List input (e.g. image parts): extract text content
        texts = [p.text for p in result if isinstance(p, TextPart)]
        return " ".join(texts) if texts else ""

    async def _send(self, text: str) -> None:
        """Send a message to the IM chat."""
        try:
            await self._server.send_to_chat(self._chat_id, text)
        except Exception:
            logger.exception(
                "Failed to send IM message to chat_id={chat_id}", chat_id=self._chat_id
            )
