"""Output masking for IM: redacts sensitive values before sending to Telegram."""

from __future__ import annotations

import re

# Patterns that match KEY=VALUE style sensitive assignments.
# Only matches when there IS a value (= followed by non-whitespace).
_ASSIGNMENT_PATTERN = re.compile(
    r"([A-Z][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PWD|CREDENTIAL)[A-Z0-9_]*)\s*=\s*(\S+)",
    re.IGNORECASE,
)

# OpenAI / Anthropic style secret keys
_SK_PATTERN = re.compile(r"\bsk-[a-zA-Z0-9]{20,}\b")

# JWT tokens (three base64url segments separated by dots)
_JWT_PATTERN = re.compile(
    r"\beyJ[a-zA-Z0-9+/=_-]{10,}\.[a-zA-Z0-9+/=_-]{10,}\.[a-zA-Z0-9+/=_-]{10,}\b"
)


def mask_output(text: str) -> str:
    """Redact sensitive values from text before sending via IM.

    Replaces values in KEY=VALUE style assignments and known secret patterns.
    Does NOT modify text that merely mentions key names without values.
    """
    # KEY=value → KEY=[REDACTED]
    text = _ASSIGNMENT_PATTERN.sub(r"\1=[REDACTED]", text)
    # sk-... secret keys
    text = _SK_PATTERN.sub("[REDACTED]", text)
    # JWT tokens
    text = _JWT_PATTERN.sub("[REDACTED]", text)
    return text


def mask_output_conditional(text: str, *, enabled: bool) -> str:
    """Apply masking only if enabled=True."""
    if not enabled:
        return text
    return mask_output(text)
