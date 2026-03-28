"""Per-user IM session management."""

from __future__ import annotations

import asyncio
import contextlib
import re
import subprocess
import sys
import time
from typing import TYPE_CHECKING

from kosong.message import ImageURLPart, TextPart, ThinkPart

from kimi_cli.ui.im._utils import split_message as _split_message
from kimi_cli.ui.im.masking import mask_output_conditional
from kimi_cli.utils.logging import logger
from kimi_cli.wire.types import (
    ApprovalRequest,
    CompactionEnd,
    ContentPart,
    Notification,
    PlanDisplay,
    QuestionRequest,
    StatusUpdate,
    ToolCallRequest,
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

        resp = await asyncio.get_running_loop().run_in_executor(
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
        self._server: IMServer = server
        self._im_config = im_config
        self._config = config
        self._kimi: KimiCLI | None = None
        # Queue of incoming user messages (str or multimodal list[ContentPart])
        self._message_queue: asyncio.Queue[UserInput] = asyncio.Queue()
        # Whether a turn is currently running
        self._turn_running = False
        # Current turn's cancel event; None when no turn is running
        self._current_cancel: asyncio.Event | None = None
        # Keep a reference to the running turn task to prevent GC and surface exceptions
        self._current_task: asyncio.Task | None = None
        # Loop detection: tracks consecutive calls to the same tool
        self._loop_last_tool: str | None = None
        self._loop_consecutive: int = 0
        # Streaming state for current turn
        self._stream_msg_id: int | None = None
        self._stream_last_edit: float = 0.0
        self._stream_edit_interval: float = 0.5  # seconds between edits
        # Latest status snapshot (context tokens, usage, plan_mode, etc.)
        self._last_status: StatusUpdate | None = None
        # Timestamp of last user activity (for idle eviction)
        self._last_activity: float = time.monotonic()
        # Per-session model override (set via /model command)
        self._model_override: str | None = None

    async def handle_message(self, text: UserInput, *, message_id: int | None = None) -> None:
        """Called when the user sends a message.

        Enqueues the message and schedules a turn before any awaits to avoid
        a race where two concurrent callers both see _turn_running=False.
        Ack feedback is sent afterwards (order doesn't matter to the user).
        """
        # Enqueue and schedule BEFORE any await — keeps the check atomic in asyncio
        self._message_queue.put_nowait(text)
        self._last_activity = time.monotonic()
        if not self._turn_running:
            self._schedule_next_turn()

        # Ack feedback: typing indicator
        with contextlib.suppress(Exception):
            await self._server.adapter.send_chat_action(self._chat_id, "typing")

        # Ack feedback: emoji reaction (Telegram Bot API 7.0+, ignore errors)
        if message_id is not None and self._im_config.ack_reaction:
            from kimi_cli.ui.im.adapters.telegram import TelegramAdapter

            adapter = self._server.adapter
            if isinstance(adapter, TelegramAdapter):
                await adapter.set_message_reaction(
                    self._chat_id, message_id, self._im_config.ack_reaction
                )

    def _schedule_next_turn(self) -> None:
        """Create a task for _run_next_turn and keep a reference to surface exceptions."""
        task = asyncio.create_task(self._run_next_turn())
        self._current_task = task

        def _on_done(t: asyncio.Task) -> None:
            self._current_task = None
            if not t.cancelled() and (exc := t.exception()) is not None:
                logger.error(
                    "Unhandled exception in IM turn task for chat_id={chat_id}",
                    chat_id=self._chat_id,
                    exc_info=exc,
                )

        task.add_done_callback(_on_done)

    async def switch_model(self, model_name: str) -> None:
        """Switch the model for this session. Takes effect on the next turn."""
        self._model_override = model_name
        # Discard current kimi instance so it's recreated with the new model
        self._kimi = None
        await self._send(f"✅ 模型已切换为 `{model_name}`，下次对话生效。")

    async def cancel_current_turn(self) -> None:
        """Cancel the currently running turn, if any."""
        if self._current_cancel is None:
            await self._send("当前没有正在运行的任务。")
            return
        self._current_cancel.set()

    def _check_and_update_loop_counter(self, tool_name: str) -> bool:
        """Update the loop counter for tool_name.

        Returns True if the loop detection threshold has been reached.
        Resets the counter when a different tool is called.
        """
        if tool_name != self._loop_last_tool:
            self._loop_last_tool = tool_name
            self._loop_consecutive = 1
            return False
        self._loop_consecutive += 1
        threshold = self._im_config.loop_detection_threshold
        return self._loop_consecutive >= threshold

    def _reset_loop_counter(self) -> None:
        """Reset loop detection state (called at end of each turn)."""
        self._loop_last_tool = None
        self._loop_consecutive = 0

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
            self._current_task = None
            # If more messages are queued, process the next one
            if not self._message_queue.empty():
                self._schedule_next_turn()

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
            is_admin = self._chat_id in self._im_config.admin_chat_ids
            effective_mode = "full-auto" if is_admin else self._im_config.default_mode
            yolo = effective_mode == "full-auto"

            # Actions controlled by the IM mode config (not user-explicit approvals).
            _MODE_ACTIONS = {
                "read file",
                "edit file",
                "stop background task",
                "run command",
                "run background command",
            }
            if effective_mode == "auto":
                # Auto-approve everything except edits outside the working directory.
                session.state.approval.auto_approve_actions |= _MODE_ACTIONS
            else:
                # suggest / full-auto: clear any previously persisted mode-derived approvals.
                session.state.approval.auto_approve_actions -= _MODE_ACTIONS
            session.save_state()

            # Per-session PERSONA.md: inject into ${ROLE_ADDITIONAL} slot.
            # Only affects new sessions (existing sessions use stored system prompt).
            agent_file: Path | None = None
            persona_path = work_dir_path / "PERSONA.md"
            if persona_path.exists():
                persona_content = persona_path.read_text(encoding="utf-8").strip()
                if persona_content:
                    import yaml  # bundled with kimi-cli deps

                    agent_yaml_path = work_dir_path / "_agent.yaml"
                    agent_yaml_path.write_text(
                        yaml.dump(
                            {
                                "version": 1,
                                "agent": {
                                    "extend": "default",
                                    "system_prompt_args": {"ROLE_ADDITIONAL": persona_content},
                                },
                            },
                            allow_unicode=True,
                        ),
                        encoding="utf-8",
                    )
                    agent_file = agent_yaml_path

            self._kimi = await KimiCLI.create(
                session,
                config=self._config,
                model_name=self._model_override or self._im_config.model_name,
                yolo=yolo,
                agent_file=agent_file,
            )
        return self._kimi

    async def _run_turn(self, user_input: UserInput) -> None:
        """Run one AI turn and send the response back via IM."""
        # ! prefix or shell-like command: run directly, bypass AI
        if isinstance(user_input, str) and user_input.startswith("!"):
            await self._run_shell_passthrough(user_input[1:].strip())
            return
        # /new is an IM-friendly alias for /clear (text only)
        if isinstance(user_input, str) and user_input.strip().lower() == "/new":
            user_input = "/clear"
        # If the message is a bare URL pointing to an image, dispatch it as an image
        elif isinstance(user_input, str):
            user_input = await _maybe_convert_image_url(user_input)
        # Optionally inject a language instruction when response_language is configured
        lang = self._im_config.response_language
        if lang:
            if isinstance(user_input, str) and not user_input.startswith("/"):
                user_input = f"[请用{lang}回复]\n{user_input}"
            elif isinstance(user_input, list):
                from kosong.message import TextPart as _TextPart

                user_input = [_TextPart(text=f"[请用{lang}回复]")] + list(user_input)
        try:
            kimi = await self._get_kimi()
        except Exception:
            logger.exception(
                "Failed to initialize KimiCLI for chat_id={chat_id}",
                chat_id=self._chat_id,
            )
            await self._send("Sorry, I encountered an error starting the AI session.")
            return

        self._current_cancel = asyncio.Event()
        cancel_event = self._current_cancel
        text_buffer: list[str] = []

        try:
            async for msg in kimi.run(user_input, cancel_event, merge_wire_messages=False):  # type: ignore[arg-type]
                match msg:
                    case ContentPart() as cp:
                        if isinstance(cp, ThinkPart):
                            pass  # skip internal thinking
                        elif isinstance(cp, TextPart):
                            text_buffer.append(cp.text)
                            # Throttled live update
                            current_text = "".join(text_buffer)
                            masked = mask_output_conditional(
                                current_text, enabled=self._im_config.output_masking_enabled
                            )
                            await self._update_stream(masked)

                    case TurnEnd():
                        if text_buffer:
                            full_text = "".join(text_buffer)
                            masked = mask_output_conditional(
                                full_text, enabled=self._im_config.output_masking_enabled
                            )
                            if self._stream_msg_id is not None:
                                chunks = _split_message(masked)
                                if len(chunks) == 1:
                                    await self._update_stream(masked, force=True)
                                else:
                                    # First chunk goes into placeholder
                                    await self._update_stream(chunks[0] + " ▶", force=True)
                                    for i, chunk in enumerate(chunks[1:], 2):
                                        suffix = " ▶" if i < len(chunks) else ""
                                        await self._send(f"({i}/{len(chunks)}) {chunk}{suffix}")
                                self._stream_msg_id = None
                            else:
                                for chunk in _split_message(masked):
                                    await self._send(chunk)
                            text_buffer.clear()

                    case ApprovalRequest() as req:
                        if text_buffer:
                            full_text = "".join(text_buffer)
                            masked = mask_output_conditional(
                                full_text, enabled=self._im_config.output_masking_enabled
                            )
                            if self._stream_msg_id is not None:
                                await self._update_stream(masked, force=True)
                                self._stream_msg_id = None
                            else:
                                await self._send(masked)
                            text_buffer.clear()
                        await self._handle_approval(req)

                    case QuestionRequest() as req:
                        if text_buffer:
                            full_text = "".join(text_buffer)
                            masked = mask_output_conditional(
                                full_text, enabled=self._im_config.output_masking_enabled
                            )
                            if self._stream_msg_id is not None:
                                await self._update_stream(masked, force=True)
                                self._stream_msg_id = None
                            else:
                                await self._send(masked)
                            text_buffer.clear()
                        await self._handle_question(req)

                    case ToolCallRequest() as tool_call:
                        if self._check_and_update_loop_counter(tool_call.name):
                            await self._send(
                                f"⚠️ 循环检测：工具 {tool_call.name!r} 连续调用 "
                                f"{self._im_config.loop_detection_threshold} 次，已自动停止。"
                            )
                            cancel_event.set()

                    case StatusUpdate() as status:
                        # Merge into running snapshot; fields that are None mean "no change"
                        if self._last_status is None:
                            self._last_status = status
                        else:
                            merged = self._last_status.model_dump()
                            for k, v in status.model_dump().items():
                                if v is not None:
                                    merged[k] = v
                            self._last_status = StatusUpdate(**merged)

                    case CompactionEnd():
                        await self._send(
                            "📦 历史对话已自动压缩（保留最近内容）\n"
                            "如需完整上下文请用 /clear 开启新对话"
                        )

                    case PlanDisplay() as plan:
                        header = f"📋 **Plan** — `{plan.file_path}`"
                        body = plan.content
                        # Keep plan message separate from the streaming buffer
                        if self._stream_msg_id is not None and text_buffer:
                            full = mask_output_conditional(
                                "".join(text_buffer),
                                enabled=self._im_config.output_masking_enabled,
                            )
                            await self._update_stream(full, force=True)
                            self._stream_msg_id = None
                            text_buffer.clear()
                        for chunk in _split_message(f"{header}\n\n{body}"):
                            await self._send(chunk)

                    case Notification() as notif:
                        severity_prefix = {
                            "error": "🔴",
                            "warning": "🟡",
                            "info": "🔵",
                        }.get(notif.severity, "ℹ️")
                        msg_text = f"{severity_prefix} **{notif.title}**"
                        if notif.body:
                            msg_text += f"\n{notif.body}"
                        await self._send(msg_text)

                    case _:
                        pass

        except asyncio.CancelledError:
            cancel_event.set()
            await self._send("[已取消]")
        except Exception as e:
            logger.exception("Error during IM AI turn for chat_id={chat_id}", chat_id=self._chat_id)
            if text_buffer:
                masked = mask_output_conditional(
                    "".join(text_buffer), enabled=self._im_config.output_masking_enabled
                )
                await self._send(masked)
                text_buffer.clear()
            await self._send(f"[Error] {e}")
        finally:
            self._current_cancel = None
            self._stream_msg_id = None
            self._reset_loop_counter()

    async def _handle_approval(self, req: ApprovalRequest) -> None:
        """Forward an approval request to the user via InlineKeyboard buttons."""
        display_lines: list[str] = [
            "⚠️ 操作需要审批",
            f"工具: {req.sender}",
            f"操作: {req.action}",
        ]
        if req.description:
            display_lines.append(req.description)
        text = "\n".join(display_lines)

        # Try to use inline keyboard via TelegramAdapter
        from kimi_cli.ui.im.adapters.telegram import TelegramAdapter

        adapter = self._server.adapter
        msg_id: int | None = None

        if isinstance(adapter, TelegramAdapter):
            msg_id = await adapter.send_message_with_keyboard(
                self._chat_id,
                text,
                keyboard=[[("✅ 同意", "approve"), ("❌ 拒绝", "reject")]],
            )
        else:
            display_lines.append("\n回复 'yes' 同意，'no' 拒绝。")
            await self._send("\n".join(display_lines))

        if msg_id is not None:
            # Wait for button press via callback
            result_future: asyncio.Future[tuple[str, str]] = (
                asyncio.get_running_loop().create_future()
            )

            async def on_button(callback_query_id: str, data: str) -> None:
                if not result_future.done():
                    result_future.set_result((callback_query_id, data))

            self._server.register_callback_handler(msg_id, on_button)

            try:
                cq_id, data = await asyncio.wait_for(result_future, timeout=120.0)
                # Ack the button press (clears spinner)
                await adapter.answer_callback_query(cq_id)
                # Remove keyboard from message to prevent re-click
                if data == "approve":
                    await self._server.edit_chat_message(
                        self._chat_id, msg_id, text + "\n\n✅ 已同意", remove_keyboard=True
                    )
                    req.resolve("approve")
                else:
                    await self._server.edit_chat_message(
                        self._chat_id,
                        msg_id,
                        text + "\n\n❌ 已拒绝，请说明原因（或直接发消息跳过）",
                        remove_keyboard=True,
                    )
                    reason = await self._wait_for_user_reply(timeout=60.0)
                    req.resolve("reject", feedback=reason or "用户拒绝")
            except TimeoutError:
                self._server.unregister_callback_handler(msg_id)
                await self._server.edit_chat_message(
                    self._chat_id,
                    msg_id,
                    text + "\n\n⏰ 审批超时，已自动拒绝",
                    remove_keyboard=True,
                )
                req.resolve("reject", feedback="审批超时")
        else:
            # Fallback: text-based approval
            reply = await self._wait_for_user_reply(timeout=120.0)
            if reply is None:
                req.resolve("reject", feedback="审批超时")
            elif reply.lower().strip() in ("yes", "y", "approve", "ok", "1", "同意"):
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

    async def _send_placeholder(self, text: str) -> int | None:
        """Send a placeholder message and record its message_id for streaming."""
        try:
            msg_id = await self._server.send_to_chat(self._chat_id, text)
            self._stream_msg_id = msg_id
            self._stream_last_edit = time.monotonic()
            return msg_id
        except Exception:
            logger.exception(
                "Failed to send placeholder to chat_id={chat_id}", chat_id=self._chat_id
            )
            return None

    async def _update_stream(self, text: str, *, force: bool = False) -> None:
        """Edit the current streaming message with new text.

        Throttled to _stream_edit_interval seconds unless force=True.
        On the first call (no stream_msg_id), sends a new message and records its ID.
        """
        if self._stream_msg_id is None:
            await self._send_placeholder(text)
            return
        now = time.monotonic()
        if not force and (now - self._stream_last_edit) < self._stream_edit_interval:
            return
        self._stream_last_edit = now
        try:
            await self._server.edit_chat_message(self._chat_id, self._stream_msg_id, text)
        except Exception:
            logger.exception(
                "Failed to edit stream message in chat_id={chat_id}", chat_id=self._chat_id
            )

    async def _run_shell_passthrough(self, command: str) -> None:
        """Run a shell command directly and send output back, bypassing AI."""
        if not command:
            await self._send("用法: !<命令>  例如: !pwd")
            return

        from pathlib import Path

        # Run in the session's work directory so pwd/ls reflect the right context
        base = Path(self._im_config.work_dir).expanduser().resolve()
        work_dir = base / "sessions" / self._chat_id
        work_dir.mkdir(parents=True, exist_ok=True)

        try:
            from kimi_cli.utils.subprocess_env import get_noninteractive_env

            if sys.platform == "win32":
                ps_command = f"[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; {command}"
                args = ["powershell.exe", "-command", ps_command]
            else:
                args = ["/bin/bash", "-c", command]
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=str(work_dir),
                env=get_noninteractive_env(),
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            output = stdout.decode("utf-8", errors="replace").strip()
            if output:
                await self._send(f"```\n{output}\n```")
            else:
                await self._send(f"✓ (exit {proc.returncode})")
        except TimeoutError:
            await self._send("[Error] 命令超时（30s）")
        except Exception as e:
            await self._send(f"[Error] {e}")

    async def _send(self, text: str) -> None:
        """Send a message to the IM chat."""
        try:
            await self._server.send_to_chat(self._chat_id, text)
        except Exception:
            logger.exception(
                "Failed to send IM message to chat_id={chat_id}", chat_id=self._chat_id
            )
