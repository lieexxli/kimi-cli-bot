Send a notification message to an IM chat (Telegram).

Use this tool to proactively push updates, progress reports, or results to users via instant messaging — without waiting for them to ask.

**When to use:**
- After completing a long-running task
- When important events occur that the user should know about
- To send progress updates during multi-step operations
- To notify users of errors or warnings that need attention

**Parameters:**
- `message`: The text message to send (plain text, keep concise)
- `chat_id`: Target chat/user ID (leave empty to send to current session's user)

**Notes:**
- Only available when kimi-cli is running in IM mode (`--im` flag)
- Messages are sent asynchronously; the tool returns immediately after queuing
- Long messages may be split into multiple IM messages
