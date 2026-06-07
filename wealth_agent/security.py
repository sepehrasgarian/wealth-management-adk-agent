"""Security layer for the wealth management assistant.

This module holds ALL of the security rules in one place, separate from the
business logic in tools.py. It has three responsibilities:

1. A verification STATE MACHINE that tracks how far the user has progressed
   through identity verification within a session.
2. A POLICY GATE (`security_gate`) wired into the agent as a
   `before_tool_callback`. It stands in front of every sensitive tool and
   blocks it unless the state machine says the user is VERIFIED. This is the
   enforcement that the model cannot talk its way around.
3. AUDIT EVENTS (`log_security_event`) that record every security-relevant
   moment as a structured log line and attach it to the current trace so it is
   visible in observability tooling (e.g. Langfuse).

The state machine lives inside ADK session state, so it persists across the
turns of a conversation automatically. Every tunable value (time-to-live,
attempt limit, which tools are sensitive) comes from config.py.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext

from . import config

logger = logging.getLogger("wealth_agent.security")


# ---------------------------------------------------------------------------
# State names.
#
# These are part of the state-machine logic (not user-tunable settings), so
# they live here next to the machine rather than in config.py.
# ---------------------------------------------------------------------------

UNVERIFIED = "UNVERIFIED"  # default: door locked
CHALLENGED = "CHALLENGED"  # we asked the security question, waiting for an answer
VERIFIED = "VERIFIED"      # correct answer given: door open (briefly, single-use)
LOCKED = "LOCKED"          # too many wrong answers: blocked, raise an alert

# The key under which the verification state machine is stored in session state.
STATE_KEY = "verification"


def _now() -> float:
    """Current time as a Unix timestamp. Wrapped in one function so tests can
    reason about (and, if needed, monkeypatch) the clock in a single place."""
    return time.time()


# ---------------------------------------------------------------------------
# The verification state machine.
#
# `session_state` below is ADK's session state (a dict-like object). Only the
# functions in this section are allowed to read or change the verification
# object, so the rules stay in one place.
# ---------------------------------------------------------------------------

def _new_state() -> dict:
    """Return a fresh, fully-unverified state object."""
    return {
        "status": UNVERIFIED,
        "attempts": 0,
        "challenged_at": None,
        "verified_at": None,
    }


def get_state(session_state) -> dict:
    """Read the current verification object, defaulting to UNVERIFIED.

    This never mutates session state; it just gives callers something safe to
    read. Functions that change state write back explicitly with `_save`.
    """
    return session_state.get(STATE_KEY) or _new_state()


def _save(session_state, verification: dict) -> None:
    """Persist the verification object back into session state."""
    session_state[STATE_KEY] = verification


def start_challenge(session_state) -> str:
    """Begin verification: move UNVERIFIED -> CHALLENGED.

    Called when the user has asked for a sensitive action and we are about to
    ask them their security question. A LOCKED session is NOT re-opened here.

    Returns the resulting status.
    """
    current = get_state(session_state)
    if current["status"] == LOCKED:
        return LOCKED

    verification = _new_state()
    verification["status"] = CHALLENGED
    verification["challenged_at"] = _now()
    _save(session_state, verification)
    return CHALLENGED


def record_answer(session_state, is_correct: bool) -> str:
    """Record the result of the user's security answer.

    Correct  -> VERIFIED.
    Wrong    -> stay CHALLENGED, increment attempts; at the limit -> LOCKED.

    Returns the resulting status.
    """
    verification = get_state(session_state)

    # Once locked, nothing here can unlock it.
    if verification["status"] == LOCKED:
        return LOCKED

    if is_correct:
        verification["status"] = VERIFIED
        verification["verified_at"] = _now()
    else:
        verification["attempts"] += 1
        if verification["attempts"] >= config.MAX_FAILED_ATTEMPTS:
            verification["status"] = LOCKED

    _save(session_state, verification)
    return verification["status"]


def is_verified(session_state) -> bool:
    """True only if the session is VERIFIED and that verification is still fresh.

    This is the single check the gate relies on. It enforces both the status and
    the time-to-live (config.VERIFICATION_TTL_SECONDS), so an old verification
    cannot be reused.
    """
    verification = get_state(session_state)
    if verification["status"] != VERIFIED:
        return False

    verified_at = verification.get("verified_at")
    if verified_at is None:
        return False

    age = _now() - verified_at
    return age <= config.VERIFICATION_TTL_SECONDS


def consume(session_state) -> None:
    """Reset to UNVERIFIED after a sensitive action completes.

    Verification is single-use: each transfer requires its own fresh
    verification, so we clear it as soon as one has been used.
    """
    _save(session_state, _new_state())


# ---------------------------------------------------------------------------
# Audit events.
# ---------------------------------------------------------------------------

def log_security_event(
    event_type: str,
    tool_context: Optional[ToolContext] = None,
    **fields: Any,
) -> None:
    """Emit a structured security event.

    The event is written to the application log AND attached to the current
    OpenTelemetry span (when one is active), so it shows up alongside the trace
    in observability tools. We deliberately never include secrets such as the
    security answer or full account balances here.
    """
    payload = {"event": event_type, **fields}
    if tool_context is not None:
        # invocation_id lets us correlate this event with its trace.
        payload.setdefault("invocation_id", getattr(tool_context, "invocation_id", None))

    logger.info("security_event %s", payload)

    # Best-effort: attach to the active trace span for Langfuse / Cloud Trace.
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        if span is not None and span.is_recording():
            span.add_event(
                f"security.{event_type}",
                attributes={k: v for k, v in fields.items() if v is not None},
            )
    except Exception:  # observability must never break the request path
        pass


# ---------------------------------------------------------------------------
# The policy gate (registered as the agent's before_tool_callback).
# ---------------------------------------------------------------------------

def security_gate(
    tool: BaseTool,
    args: dict[str, Any],
    tool_context: ToolContext,
) -> Optional[dict]:
    """Guard that runs BEFORE every tool call.

    For non-sensitive tools it does nothing (returns None -> the tool runs
    normally). For sensitive tools it allows the call only when the session is
    verified; otherwise it blocks the tool by returning an error dict, which
    ADK uses as the tool's result instead of actually running it.
    """
    if tool.name not in config.SENSITIVE_TOOLS:
        return None  # not sensitive: allow

    if is_verified(tool_context.state):
        return None  # verified and fresh: allow the tool to run

    # Blocked: record the attempt and short-circuit the tool.
    status = get_state(tool_context.state)["status"]
    log_security_event(
        "unauthorized_transfer_attempt",
        tool_context,
        tool=tool.name,
        verification_status=status,
    )
    return {
        "status": "error",
        "message": (
            "This action requires identity verification. Retrieve the security "
            "question, verify the user's answer, then try again."
        ),
    }
