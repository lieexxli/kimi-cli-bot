"""SendIMNotification tool — lets the agent proactively send IM messages."""

from __future__ import annotations

from pathlib import Path
from typing import override

from kosong.tooling import CallableTool2, ToolError, ToolOk, ToolReturnValue
from pydantic import BaseModel, Field

from kimi_cli.tools import SkipThisTool
from kimi_cli.tools.utils import load_desc

NAME = "SendIMNotification"


class SendIMNotificationParams(BaseModel):
    """Parameters for SendIMNotification tool."""

    message: str = Field(description="Message content to send. Supports plain text.")
    chat_id: str = Field(
        default="",
        description=(
            "Target chat/user ID to send the message to. "
            "Leave empty to send to the current conversation (the user who triggered this session)."
        ),
    )


class SendIMNotification(CallableTool2[SendIMNotificationParams]):
    """
    Tool for the AI agent to proactively send IM messages/notifications.
    Only available when kimi-cli is running in IM mode (--im flag).
    Raises SkipThisTool if not running in IM mode.
    """

    name: str = NAME
    description: str = load_desc(Path(__file__).parent / "im_notify.md")
    params: type[SendIMNotificationParams] = SendIMNotificationParams

    def __init__(self) -> None:
        from kimi_cli.ui.im import get_current_im_server

        if get_current_im_server() is None:
            raise SkipThisTool("Not running in IM mode")
        super().__init__()

    @override
    async def __call__(self, params: SendIMNotificationParams) -> ToolReturnValue:
        from kimi_cli.ui.im import get_current_im_server

        server = get_current_im_server()
        if server is None:
            return ToolError(
                output="",
                message="IM server is not running. This tool is only available in IM mode.",
                brief="IM server not available",
            )

        message = params.message.strip()
        if not message:
            return ToolError(
                output="",
                message="Message cannot be empty.",
                brief="Empty message",
            )

        try:
            if params.chat_id:
                await server.send_to_chat(params.chat_id, message)
                brief = f"Sent to chat {params.chat_id}"
            else:
                # Broadcast to all active sessions
                chat_ids = server.active_chat_ids()
                for chat_id in chat_ids:
                    await server.send_to_chat(chat_id, message)
                brief = f"Sent to {len(chat_ids)} chat(s)"

            return ToolOk(
                output="",
                message=f"Message sent successfully. {brief}.",
                brief=brief,
            )
        except Exception as e:
            return ToolError(
                output="",
                message=f"Failed to send IM message: {e}",
                brief="Send failed",
            )
