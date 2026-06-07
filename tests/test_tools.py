"""Deterministic tests for the tools and the human-in-the-loop flow (no LLM).

These call the tool functions directly with a fake tool context, so they verify
the verification flow, the HITL confirmation, and the transfer logic without any
model calls or API key.
"""

from __future__ import annotations

from wealth_agent import security, services, tools
from tests.fakes import FakeToolConfirmation, FakeToolContext


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
    assert security.get_state(ctx.state)["status"] == security.CHALLENGED


def test_verify_correct_answer_marks_verified(ctx):
    tools.get_security_question(ctx)
    result = tools.verify_security_answer("Rex", ctx)
    assert result == {"status": "success", "verified": True, "locked": False}
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
    """Helper: take the context through to a VERIFIED state."""
    tools.get_security_question(ctx)
    tools.verify_security_answer("Rex", ctx)


def test_transfer_first_call_requests_confirmation(ctx):
    _verify(ctx)
    result = tools.transfer_funds("checking", "savings", 500, ctx)
    assert result["status"] == "pending"
    assert ctx.requested_hint is not None and "500" in ctx.requested_hint
    # No money moved yet.
    assert services.get_account_balances("user_123")["checking_balance"] == 2000.0


def test_transfer_declined_does_not_move_money(ctx):
    _verify(ctx)
    tools.transfer_funds("checking", "savings", 500, ctx)  # request confirmation
    ctx.tool_confirmation = FakeToolConfirmation(confirmed=False)
    result = tools.transfer_funds("checking", "savings", 500, ctx)
    assert result["status"] == "error"
    assert services.get_account_balances("user_123")["checking_balance"] == 2000.0


def test_transfer_confirmed_moves_money_and_is_single_use(ctx):
    _verify(ctx)
    tools.transfer_funds("checking", "savings", 500, ctx)  # request confirmation
    ctx.tool_confirmation = FakeToolConfirmation(confirmed=True)
    result = tools.transfer_funds("checking", "savings", 500, ctx)
    assert result["status"] == "success"
    assert result["checking_balance"] == 1500.0
    assert result["savings_balance"] == 5500.0
    # Verification is consumed: a second transfer is no longer authorized.
    assert security.is_verified(ctx.state) is False


def test_transfer_insufficient_funds_is_rejected(ctx):
    _verify(ctx)
    tools.transfer_funds("checking", "savings", 999999, ctx)  # request confirmation
    ctx.tool_confirmation = FakeToolConfirmation(confirmed=True)
    result = tools.transfer_funds("checking", "savings", 999999, ctx)
    assert result["status"] == "error"
    assert "insufficient" in result["message"].lower()
