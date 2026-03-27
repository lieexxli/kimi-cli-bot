"""Shared utilities for the IM UI layer."""

from __future__ import annotations

# Maximum characters per IM message before splitting
_MAX_MSG_CHARS = 4000


def split_message(text: str, max_chars: int = _MAX_MSG_CHARS) -> list[str]:
    """Split a long message into chunks that fit within IM limits.

    Splits on newlines where possible to avoid cutting mid-word or mid-codeblock.
    If a single line exceeds max_chars it is hard-split as a last resort.
    """
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in text.splitlines(keepends=True):
        if current_len + len(line) > max_chars and current:
            chunks.append("".join(current))
            current = []
            current_len = 0
        # Single line longer than limit: hard-split it
        if len(line) > max_chars:
            for i in range(0, len(line), max_chars):
                chunks.append(line[i : i + max_chars])
        else:
            current.append(line)
            current_len += len(line)
    if current:
        chunks.append("".join(current))
    return chunks
