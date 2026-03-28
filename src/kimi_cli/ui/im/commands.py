"""Bot-layer IM management commands.

These commands operate on IMSession/IMServer state and are distinct from
soul-layer slash commands (/clear /yolo /compact etc.) which are handled
by kimi-cli's soul layer when the user sends them as regular messages.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kimi_cli.ui.im import IMServer


async def handle_model(chat_id: str, model_name: str, server: IMServer) -> None:
    """Switch the model for the current session (/model <name>)."""
    admin_ids = server.im_config.admin_chat_ids
    if admin_ids and chat_id not in admin_ids:
        await server.send_to_chat(chat_id, "⚠️ /model 仅管理员可用。")
        return
    if not model_name:
        current = server.default_model
        session = server.get_session(chat_id)
        if session and session._model_override:
            current = session._model_override
        await server.send_to_chat(chat_id, f"当前模型：`{current}`\n用法：/model <模型名>")
        return
    session = server.get_session(chat_id)
    if session is None:
        # Create a stub session just to relay the switch; it will be initialized on next message
        from kimi_cli.ui.im.session import IMSession
        session = IMSession(
            chat_id=chat_id,
            server=server,
            im_config=server.im_config,
            config=server._config,
        )
        server._sessions[chat_id] = session
    await session.switch_model(model_name)


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
    model = server.default_model
    mode = server.im_config.default_mode

    version: str = "unknown"
    try:
        from kimi_cli import __version__  # type: ignore[attr-defined]

        version = __version__  # type: ignore[assignment]
    except Exception:
        pass

    lines = [
        "📊 Bot 状态",
        f"├─ 版本: {version}",
        f"├─ 活跃会话: {active}",
        f"├─ 模型: {model}",
        f"├─ 默认模式: {mode}",
    ]

    # Append per-session context info if available
    session = server.get_session(chat_id)
    status = session._last_status if session is not None else None
    if status is not None:
        if status.context_tokens is not None and status.max_context_tokens:
            pct = f"{status.context_usage * 100:.0f}%" if status.context_usage is not None else "?"
            lines.append(
                f"├─ 上下文: {status.context_tokens:,} token（{pct}）"
            )
        elif status.context_tokens is not None:
            lines.append(f"├─ 上下文: {status.context_tokens:,} token")
        if status.plan_mode:
            lines.append("├─ 模式: 📋 Plan 模式（只读）")

    # Replace the last ├─ with └─
    if lines:
        lines[-1] = "└─" + lines[-1][2:]

    await server.send_to_chat(chat_id, "\n".join(lines))
