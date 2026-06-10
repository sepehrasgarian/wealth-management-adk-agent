"""Deterministic tests for the tools and the human-in-the-loop flow (no LLM).

These call the tool functions directly with a fake tool context, so they verify
the verification flow, the HITL confirmation, and the transfer logic without any
model calls or API key.
"""

from __future__ import annotations

from wealth_agent import config, security, services, tools
from wealth_agent.security import VerificationState
from tests.fakes import FakeToolContext


def test_get_portfolio_balance_returns_totals(ctx):
    result = tools.get_portfolio_balance(ctx)
    assert result["status"] == "success"
    assert result["checking_balance"] == 2000.0
    assert result["savings_balance"] == 5000.0
    assert result["total_balance"] == 7000.0


def test_get_portfolio_balance_unknown_user_errors():
    unknown = FakeToolContext(state={"user_id": "nobody"})
    assert tools.get_portfolio_balance(unknown)["status"] == "error"


def test_get_security_question_unknown_user_errors():
    unknown = FakeToolContext(state={"user_id": "nobody"})
    assert tools.get_security_question(unknown)["status"] == "error"


def test_get_security_question_when_locked_is_denied(ctx):
    # Drive the session into LOCKED, then a new challenge must be refused.
    tools.get_security_question(ctx)
    for _ in range(10):
        if tools.verify_security_answer("wrong", ctx)["locked"]:
            break
    result = tools.get_security_question(ctx)
    assert result["status"] == "error" and "locked" in result["message"].lower()


def test_get_security_question_starts_challenge(ctx):
    result = tools.get_security_question(ctx)
    assert result["status"] == "success"
    assert "pet" in result["security_question"].lower()
    assert security.get_state(ctx.state)["status"] == VerificationState.CHALLENGED


def test_single_answer_cannot_verify_even_when_challenge_autostarts(ctx):
    """If the model skips get_security_question, verify_security_answer auto-starts
    the challenge — but ONE correct answer must still NOT verify (both questions
    are required). This guards the multi-question rule regardless of call order."""
    result = tools.verify_security_answer("Rex", ctx)   # no get_security_question first
    assert result["verified"] is False                  # not verified on one answer
    assert security.is_verified(ctx.state) is False
    # The second question must still be answered to complete verification.
    assert result.get("answer_correct") is True and "color" in result["next_question"].lower()
    tools.verify_security_answer("Blue", ctx)
    assert security.is_verified(ctx.state) is True


def test_first_correct_answer_asks_next_then_second_verifies(ctx):
    tools.get_security_question(ctx)
    # First correct answer is not enough — a second question is returned.
    first = tools.verify_security_answer("Rex", ctx)
    assert first["verified"] is False
    assert "color" in first["next_question"].lower()
    assert security.is_verified(ctx.state) is False
    # Answering the second question completes verification.
    second = tools.verify_security_answer("Blue", ctx)
    assert second == {"status": "success", "verified": True, "locked": False}
    assert security.is_verified(ctx.state) is True


def test_verify_wrong_answer_reports_attempts_remaining(ctx):
    tools.get_security_question(ctx)
    result = tools.verify_security_answer("Fluffy", ctx)
    assert result["verified"] is False
    assert result["locked"] is False
    assert result["attempts_remaining"] >= 1


def test_repeated_wrong_answers_lock_the_account(ctx):
    tools.get_security_question(ctx)
    last = None
    for _ in range(10):
        last = tools.verify_security_answer("wrong", ctx)
        if last["locked"]:
            break
    assert last["locked"] is True


def _verify(ctx):
    """Helper: take the context through to a VERIFIED state (both questions)."""
    tools.get_security_question(ctx)
    tools.verify_security_answer("Rex", ctx)   # question 1
    tools.verify_security_answer("Blue", ctx)  # question 2


def test_get_security_question_is_idempotent_when_already_verified(ctx):
    """Calling get_security_question again while already verified must NOT reset
    the verification — it should report already-verified and keep the session."""
    _verify(ctx)
    assert security.is_verified(ctx.state) is True
    result = tools.get_security_question(ctx)
    assert result.get("already_verified") is True
    assert security.is_verified(ctx.state) is True  # still verified, not re-challenged


# --- Transfer: human-in-the-loop confirmation (say yes/no) ---

def test_transfer_requests_confirmation_and_moves_no_money_yet(ctx):
    _verify(ctx)
    result = tools.transfer_funds("checking", "savings", 500, ctx)
    assert result["status"] == "confirmation_required"
    # A pending transfer is recorded; no money has moved yet.
    assert ctx.state[tools.STATE_PENDING_TRANSFER]["amount"] == 500
    assert services.get_account_balances("user_123")["checking_balance"] == 2000.0


def test_confirm_yes_executes_and_is_single_use(ctx):
    _verify(ctx)
    tools.transfer_funds("checking", "savings", 500, ctx)
    result = tools.confirm_transfer(approve=True, tool_context=ctx)
    assert result["status"] == "success"
    assert result["checking_balance"] == 1500.0
    assert result["savings_balance"] == 5500.0
    assert ctx.state[tools.STATE_PENDING_TRANSFER] is None
    # Verification is consumed: a second transfer is no longer authorized.
    assert security.is_verified(ctx.state) is False


def test_confirm_no_cancels_and_moves_no_money(ctx):
    _verify(ctx)
    tools.transfer_funds("checking", "savings", 500, ctx)
    result = tools.confirm_transfer(approve=False, tool_context=ctx)
    assert result["status"] == "error"
    assert services.get_account_balances("user_123")["checking_balance"] == 2000.0


def test_confirm_with_nothing_pending_errors(ctx):
    assert tools.confirm_transfer(approve=True, tool_context=ctx)["status"] == "error"


def test_transfer_insufficient_funds_rejected_up_front(ctx):
    _verify(ctx)
    # 5000 is under the per-transfer limit but over the checking balance (2000).
    # validate_transfer rejects it immediately — before any confirmation.
    result = tools.transfer_funds("checking", "savings", 5000, ctx)
    assert result["status"] == "error"
    assert "insufficient" in result["message"].lower()
    assert ctx.state.get(tools.STATE_PENDING_TRANSFER) is None  # nothing pending


def test_transfer_completes_directly_when_confirmation_disabled(ctx, monkeypatch):
    # Eval mode: with confirmation off, the transfer completes without a yes/no.
    monkeypatch.setattr(config, "REQUIRE_TRANSFER_CONFIRMATION", False)
    _verify(ctx)
    result = tools.transfer_funds("checking", "savings", 500, ctx)
    assert result["status"] == "success"
    assert result["checking_balance"] == 1500.0
