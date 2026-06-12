"""PII redaction guardrail.

A defense-in-depth layer that masks obvious sensitive numbers — card numbers,
US SSNs, and long account/PIN-like digit sequences — in user input BEFORE it is
sent to the LLM. This keeps accidental PII out of the prompt, the model
provider, and the traces.

This is a guardrail, NOT the primary control. Knowledge-based secrets (a PIN or
a security answer) are free text and should be collected OUT OF BAND so they
never reach the LLM at all (see the "Sensitive data handling" section of the
README). This layer catches the accidental case — e.g. a user pasting a card
number into the chat.
"""

from __future__ import annotations

import re

MASK = "[REDACTED]"

# Patterns for obviously-sensitive numbers. Short numbers (e.g. a transfer
# amount like 500) are deliberately NOT matched.
_PATTERNS = (
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),          # US SSN: 123-45-6789
    re.compile(r"\b\d(?:[ -]?\d){12,18}\b"),       # card number: 13-19 digits, spaces/dashes ok
    re.compile(r"\b\d{9,}\b"),                      # long account / PIN-like digit run
)


def redact_pii(text: str) -> str:
    """Return `text` with card numbers, SSNs, and long digit runs masked."""
    if not text:
        return text
    for pattern in _PATTERNS:
        text = pattern.sub(MASK, text)
    return text


def redact_pii_before_model(callback_context, llm_request) -> None:
    """ADK `before_model_callback`: mask PII in outgoing content.

    Mutates the request's text parts in place so any masked PII never reaches
    the model (or the trace of the model call). Returns None so the request
    proceeds normally.
    """
    for content in (llm_request.contents or []):
        for part in (content.parts or []):
            if getattr(part, "text", None):
                part.text = redact_pii(part.text)
    return None
