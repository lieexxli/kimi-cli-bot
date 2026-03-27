"""Bot-layer IM management commands.

These commands operate on IMSession/IMServer state and are distinct from
soul-layer slash commands (/clear /yolo /compact etc.) which are handled
by kimi-cli's soul layer when the user sends them as regular messages.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kimi_cli.ui.im import IMServer


HELP_TEXT = """\
🤖 Kimi Code AI Assistant

Bot 管理命令：
  /start   — 显示本帮助
  /help    — 显示本帮助
  /cancel  — 中止当前正在运行的 AI 任务
  /status  — 显示 Bot 状态（仅管理员）

AI 对话命令（直接发消息即可）：
  /clear   — 清除对话历史，开始新会话
  /yolo    — 切换 yolo（全自动）模式
  /compact — 手动压缩上下文
  /plan    — 进入/退出 Plan 模式
  /export  — 导出当前会话
"""


async def handle_start(chat_id: str, server: IMServer) -> None:
    await server.send_to_chat(chat_id, HELP_TEXT)


async def handle_help(chat_id: str, server: IMServer) -> None:
    await server.send_to_chat(chat_id, HELP_TEXT)


async def handle_cancel(chat_id: str, server: IMServer) -> None:
    session = server.get_session(chat_id)
    if session is None:
        await server.send_to_chat(chat_id, "当前没有活跃的会话。")
        return
    await session.cancel_current_turn()


async def handle_status(chat_id: str, server: IMServer) -> None:
    admin_ids = server.im_config.admin_chat_ids
    if admin_ids and chat_id not in admin_ids:
        await server.send_to_chat(chat_id, "⚠️ /status 仅管理员可用。")
        return

    active = len(server.active_chat_ids())
    model = server.im_config.model_name or "（默认）"
    mode = server.im_config.default_mode

    version: str = "unknown"
    try:
        from kimi_cli import __version__  # type: ignore[attr-defined]

        version = __version__  # type: ignore[assignment]
    except Exception:
        pass

    text = (
        f"📊 Bot 状态\n"
        f"├─ 版本: {version}\n"
        f"├─ 活跃会话: {active}\n"
        f"├─ 模型: {model}\n"
        f"└─ 默认模式: {mode}"
    )
    await server.send_to_chat(chat_id, text)
