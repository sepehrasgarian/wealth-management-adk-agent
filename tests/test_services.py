"""Deterministic tests for the service layer, including error branches."""

from __future__ import annotations

import pytest

from wealth_agent import services


def test_get_account_balances_known_user():
    balances = services.get_account_balances("user_123")
    assert balances == {"checking_balance": 2000.0, "savings_balance": 5000.0}


def test_get_account_balances_unknown_user_returns_none():
    assert services.get_account_balances("nobody") is None


def test_each_user_has_two_distinct_security_questions():
    q123 = services.get_security_questions("user_123")
    q456 = services.get_security_questions("user_456")
    assert len(q123) == 2 and len(q456) == 2
    assert q123 != q456  # different users, different questions


def test_security_questions_are_returned_in_order():
    questions = services.get_security_questions("user_123")
    assert "pet" in questions[0].lower()      # position 0
    assert "color" in questions[1].lower()    # position 1
    assert services.get_security_questions("nobody") == []  # unknown user


def test_check_security_answer_is_case_and_space_insensitive():
    assert services.check_security_answer("user_123", 0, "  rEx  ") is True
    assert services.check_security_answer("user_123", 1, "blue") is True
    assert services.check_security_answer("user_123", 0, "wrong") is False
    assert services.check_security_answer("nobody", 0, "Rex") is False


def test_user_isolation_questions_and_balances():
    # Each user's questions and balances are their own — no cross-user access.
    assert services.get_account_balances("user_456") == {
        "checking_balance": 8000.0, "savings_balance": 12000.0,
    }
    # user_456's answer is "Toronto", not user_123's "Rex".
    assert services.check_security_answer("user_456", 0, "Toronto") is True
    assert services.check_security_answer("user_456", 0, "Rex") is False


def test_execute_transfer_moves_money():
    result = services.execute_transfer("user_123", "checking", "savings", 500)
    assert result == {"checking_balance": 1500.0, "savings_balance": 5500.0}


def test_execute_transfer_rejects_unknown_account():
    with pytest.raises(services.TransferError):
        services.execute_transfer("user_123", "crypto", "savings", 100)


def test_execute_transfer_rejects_same_account():
    with pytest.raises(services.TransferError):
        services.execute_transfer("user_123", "checking", "checking", 100)


def test_execute_transfer_rejects_non_positive_amount():
    with pytest.raises(services.TransferError):
        services.execute_transfer("user_123", "checking", "savings", 0)


def test_execute_transfer_rejects_insufficient_funds():
    with pytest.raises(services.TransferError, match="Insufficient"):
        services.execute_transfer("user_123", "checking", "savings", 5000)


def test_execute_transfer_rejects_over_the_limit():
    # Above the per-transfer limit (checked before the funds check).
    with pytest.raises(services.TransferError, match="limit"):
        services.execute_transfer("user_123", "checking", "savings", 20000)


def test_execute_transfer_unknown_user():
    with pytest.raises(services.TransferError):
        services.execute_transfer("nobody", "checking", "savings", 100)
