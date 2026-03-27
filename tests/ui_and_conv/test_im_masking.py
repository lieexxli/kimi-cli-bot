"""Tests for IM output masking."""

from __future__ import annotations

from kimi_cli.ui.im.masking import mask_output


def test_masks_api_key_assignment():
    result = mask_output("OPENAI_API_KEY=sk-abc123xyz456abc123xyz456abc123xyz456")
    assert "sk-abc123" not in result
    assert "[REDACTED]" in result


def test_masks_token_assignment():
    result = mask_output("TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ1234567890")
    assert "ABCdefGHI" not in result
    assert "[REDACTED]" in result


def test_masks_secret_assignment():
    result = mask_output("MY_SECRET=supersecretvalue123")
    assert "supersecretvalue123" not in result
    assert "[REDACTED]" in result


def test_masks_password_assignment():
    result = mask_output("DB_PASSWORD=hunter2")
    assert "hunter2" not in result
    assert "[REDACTED]" in result


def test_masks_sk_prefix_key():
    result = mask_output("Using key: sk-abcdefghijklmnopqrstuvwxyz123456789")
    assert "abcdefghij" not in result
    assert "[REDACTED]" in result


def test_masks_jwt_token():
    jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    result = mask_output(f"token: {jwt}")
    assert "SflKxwRJ" not in result
    assert "[REDACTED]" in result


def test_preserves_normal_text():
    text = "The answer is 42. Here is the result of your calculation."
    assert mask_output(text) == text


def test_preserves_discussion_about_keys():
    # A discussion about API keys should not be masked if it has no actual value
    text = "You should set the OPENAI_API_KEY environment variable."
    assert mask_output(text) == text


def test_multiple_secrets_in_one_message():
    text = "API_KEY=abc123secret\nDB_PASSWORD=mypassword\nNormal text here"
    result = mask_output(text)
    assert "abc123secret" not in result
    assert "mypassword" not in result
    assert "Normal text here" in result


def test_masking_disabled_returns_unchanged():
    from kimi_cli.ui.im.masking import mask_output_conditional

    text = "API_KEY=should_stay"
    assert mask_output_conditional(text, enabled=False) == text


def test_masking_enabled_applies_masking():
    from kimi_cli.ui.im.masking import mask_output_conditional

    text = "API_KEY=should_be_redacted"
    result = mask_output_conditional(text, enabled=True)
    assert "should_be_redacted" not in result
