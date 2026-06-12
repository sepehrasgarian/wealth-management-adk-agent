"""Deterministic tests for the security layer (no LLM, no API key).

These cover the verification state machine and the policy gate directly, so the
security rules are validated quickly and reliably, independent of the model.
"""

from __future__ import annotations

from wealth_agent import config, security
from wealth_agent.security import VerificationState
from tests.fakes import FakeTool, FakeToolContext


# --- State machine ---------------------------------------------------------

def test_starts_unverified():
    state = {}
    assert security.get_state(state)["status"] == VerificationState.UNVERIFIED
    assert security.is_verified(state) is False


def test_both_questions_required_to_verify():
    state = {}
    assert security.start_challenge(state, total_questions=2) == VerificationState.CHALLENGED
    # First correct answer is not enough — one question remains.
    assert security.record_answer(state, is_correct=True) == VerificationState.CHALLENGED
    assert security.is_verified(state) is False
    # Second correct answer completes verification.
    assert security.record_answer(state, is_correct=True) == VerificationState.VERIFIED
    assert security.is_verified(state) is True


def test_answer_without_challenge_cannot_verify():
    """A correct answer must NOT verify if start_challenge was never called.

    Regression: if get_security_question is skipped, total_questions stays 0 and
    a single answer would otherwise satisfy `index >= total_questions`.
    """
    state = {}
    assert security.record_answer(state, is_correct=True) == VerificationState.UNVERIFIED
    assert security.is_verified(state) is False


def test_wrong_answers_lock_after_max_attempts():
    state = {}
    security.start_challenge(state, total_questions=2)
    for _ in range(config.MAX_FAILED_ATTEMPTS - 1):
        assert security.record_answer(state, is_correct=False) == VerificationState.CHALLENGED
    # The final wrong answer crosses the limit and locks the session.
    assert security.record_answer(state, is_correct=False) == VerificationState.LOCKED
    assert security.is_verified(state) is False


def test_locked_session_cannot_recover():
    state = {}
    security.start_challenge(state, total_questions=2)
    for _ in range(config.MAX_FAILED_ATTEMPTS):
        security.record_answer(state, is_correct=False)
    assert security.get_state(state)["status"] == VerificationState.LOCKED
    # Even a correct answer or a new challenge cannot unlock it.
    assert security.record_answer(state, is_correct=True) == VerificationState.LOCKED
    assert security.start_challenge(state, total_questions=2) == VerificationState.LOCKED


def test_attempts_remaining_counts_down():
    state = {}
    security.start_challenge(state, total_questions=2)
    assert security.attempts_remaining(state) == config.MAX_FAILED_ATTEMPTS
    security.record_answer(state, is_correct=False)
    assert security.attempts_remaining(state) == config.MAX_FAILED_ATTEMPTS - 1


def _fully_verify(state):
    security.start_challenge(state, total_questions=2)
    security.record_answer(state, is_correct=True)
    security.record_answer(state, is_correct=True)


def test_consume_resets_to_unverified():
    state = {}
    _fully_verify(state)
    assert security.is_verified(state) is True
    security.consume(state)
    assert security.get_state(state)["status"] == VerificationState.UNVERIFIED
    assert security.is_verified(state) is False


def test_verification_expires_after_ttl():
    state = {}
    _fully_verify(state)
    # Pretend the verification happened longer ago than the TTL allows.
    state[security.STATE_KEY]["verified_at"] -= config.VERIFICATION_TTL_SECONDS + 1
    assert security.is_verified(state) is False


# --- Policy gate -----------------------------------------------------------

def test_gate_blocks_sensitive_tool_when_unverified():
    ctx = FakeToolContext()
    result = security.security_gate(FakeTool("transfer_funds"), {}, ctx)
    assert result is not None and result["status"] == "error"


def test_gate_allows_sensitive_tool_when_verified():
    ctx = FakeToolContext()
    _fully_verify(ctx.state)
    assert security.security_gate(FakeTool("transfer_funds"), {}, ctx) is None


def test_gate_ignores_non_sensitive_tool():
    ctx = FakeToolContext()  # unverified
    assert security.security_gate(FakeTool("get_portfolio_balance"), {}, ctx) is None


def test_verification_survives_loss_of_conversation_history():
    """Long-context robustness: verification lives in session STATE, not the prompt.

    Even if the entire conversation history were dropped (e.g. the context window
    overflowed and older turns were truncated), the gate still reads VERIFIED from
    the persisted state — so a long conversation can't make the agent "forget" the
    user was verified, nor let an unverified one through.
    """
    # Verify, then capture ONLY the persisted session state (no history at all).
    verified_state = {"user_id": "user_123"}
    _fully_verify(verified_state)

    # A brand-new turn carrying just that state — as if all prior turns were gone.
    fresh_ctx = FakeToolContext(state=verified_state)
    assert security.is_verified(fresh_ctx.state) is True
    assert security.security_gate(FakeTool("transfer_funds"), {}, fresh_ctx) is None  # still allowed

    # And the converse: history full of activity but no verification → still blocked.
    unverified_ctx = FakeToolContext(state={"user_id": "user_123"})
    assert security.security_gate(FakeTool("transfer_funds"), {}, unverified_ctx)["status"] == "error"
