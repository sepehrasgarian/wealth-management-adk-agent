"""Deterministic tests for the security layer (no LLM, no API key).

These cover the verification state machine and the policy gate directly, so the
security rules are validated quickly and reliably, independent of the model.
"""

from __future__ import annotations

from wealth_agent import config, security
from tests.fakes import FakeTool, FakeToolContext


# --- State machine ---------------------------------------------------------

def test_starts_unverified():
    state = {}
    assert security.get_state(state)["status"] == security.UNVERIFIED
    assert security.is_verified(state) is False


def test_challenge_then_correct_answer_verifies():
    state = {}
    assert security.start_challenge(state) == security.CHALLENGED
    assert security.record_answer(state, is_correct=True) == security.VERIFIED
    assert security.is_verified(state) is True


def test_wrong_answers_lock_after_max_attempts():
    state = {}
    security.start_challenge(state)
    for _ in range(config.MAX_FAILED_ATTEMPTS - 1):
        assert security.record_answer(state, is_correct=False) == security.CHALLENGED
    # The final wrong answer crosses the limit and locks the session.
    assert security.record_answer(state, is_correct=False) == security.LOCKED
    assert security.is_verified(state) is False


def test_locked_session_cannot_recover():
    state = {}
    security.start_challenge(state)
    for _ in range(config.MAX_FAILED_ATTEMPTS):
        security.record_answer(state, is_correct=False)
    assert security.get_state(state)["status"] == security.LOCKED
    # Even a correct answer or a new challenge cannot unlock it.
    assert security.record_answer(state, is_correct=True) == security.LOCKED
    assert security.start_challenge(state) == security.LOCKED


def test_attempts_remaining_counts_down():
    state = {}
    security.start_challenge(state)
    assert security.attempts_remaining(state) == config.MAX_FAILED_ATTEMPTS
    security.record_answer(state, is_correct=False)
    assert security.attempts_remaining(state) == config.MAX_FAILED_ATTEMPTS - 1


def test_consume_resets_to_unverified():
    state = {}
    security.start_challenge(state)
    security.record_answer(state, is_correct=True)
    assert security.is_verified(state) is True
    security.consume(state)
    assert security.get_state(state)["status"] == security.UNVERIFIED
    assert security.is_verified(state) is False


def test_verification_expires_after_ttl():
    state = {}
    security.start_challenge(state)
    security.record_answer(state, is_correct=True)
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
    security.start_challenge(ctx.state)
    security.record_answer(ctx.state, is_correct=True)
    assert security.security_gate(FakeTool("transfer_funds"), {}, ctx) is None


def test_gate_ignores_non_sensitive_tool():
    ctx = FakeToolContext()  # unverified
    assert security.security_gate(FakeTool("get_portfolio_balance"), {}, ctx) is None
