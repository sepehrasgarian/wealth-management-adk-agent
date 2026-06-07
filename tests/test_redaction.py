"""Tests for the PII redaction guardrail."""

from __future__ import annotations

from wealth_agent import redaction


def test_masks_credit_card_numbers():
    assert "4111111111111111" not in redaction.redact_pii("my card is 4111111111111111")
    assert "[REDACTED]" in redaction.redact_pii("card 4111 1111 1111 1111 please")


def test_masks_ssn():
    out = redaction.redact_pii("my ssn is 123-45-6789")
    assert "123-45-6789" not in out and "[REDACTED]" in out


def test_masks_long_account_numbers():
    out = redaction.redact_pii("account 000123456789")
    assert "000123456789" not in out and "[REDACTED]" in out


def test_does_not_mask_short_amounts_or_words():
    # Transfer amounts and ordinary words must pass through untouched.
    assert redaction.redact_pii("transfer 500 from checking to savings") == (
        "transfer 500 from checking to savings"
    )
    assert redaction.redact_pii("My first pet was Rex") == "My first pet was Rex"


def test_handles_empty_text():
    assert redaction.redact_pii("") == ""


def test_before_model_callback_masks_request_contents():
    # A tiny stand-in for an LlmRequest with one user message part.
    class Part:
        def __init__(self, text):
            self.text = text

    class Content:
        def __init__(self, parts):
            self.parts = parts

    class LlmRequest:
        def __init__(self, contents):
            self.contents = contents

    part = Part("here is my card 4111111111111111")
    request = LlmRequest([Content([part])])
    redaction.redact_pii_before_model(callback_context=None, llm_request=request)
    assert "4111111111111111" not in part.text
    assert "[REDACTED]" in part.text
