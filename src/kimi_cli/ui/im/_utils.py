"""Shared utilities for the IM UI layer."""

from __future__ import annotations

# Maximum characters per IM message before splitting
_MAX_MSG_CHARS = 4000


def split_message(text: str, max_chars: int = _MAX_MSG_CHARS) -> list[str]:
    """Split a long message into chunks that fit within IM limits.

    Splitting priority:
    1. Paragraph boundaries (blank lines) — preserves semantic units
    2. Line boundaries — avoids cutting mid-sentence
    3. Hard split — last resort for lines longer than max_chars

    Multi-chunk results are annotated with (1/N) … (N/N) page numbers.
    """
    if len(text) <= max_chars:
        return [text]

    # Split into paragraphs (separated by blank lines), keeping the delimiter
    paragraphs: list[str] = []
    current_para: list[str] = []
    for line in text.splitlines(keepends=True):
        current_para.append(line)
        if line.strip() == "":
            paragraphs.append("".join(current_para))
            current_para = []
    if current_para:
        paragraphs.append("".join(current_para))

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    def _flush() -> None:
        if current:
            chunks.append("".join(current))
            current.clear()

    for para in paragraphs:
        if len(para) > max_chars:
            # Paragraph itself too long: fall back to line-by-line splitting
            if current:
                _flush()
                current_len = 0
            for line in para.splitlines(keepends=True):
                if current_len + len(line) > max_chars and current:
                    _flush()
                    current_len = 0
                if len(line) > max_chars:
                    # Single line longer than limit: hard-split
                    if current:
                        _flush()
                        current_len = 0
                    for i in range(0, len(line), max_chars):
                        chunks.append(line[i : i + max_chars])
                else:
                    current.append(line)
                    current_len += len(line)
        elif current_len + len(para) > max_chars:
            _flush()
            current_len = 0
            current.append(para)
            current_len = len(para)
        else:
            current.append(para)
            current_len += len(para)

    _flush()

    # Annotate with page numbers when there are multiple chunks
    if len(chunks) > 1:
        total = len(chunks)
        chunks = [f"({i}/{total})\n{chunk}" for i, chunk in enumerate(chunks, 1)]

    return chunks
