"""Deterministic tests for the service layer, including error branches."""

from __future__ import annotations

import pytest

from wealth_agent import services


def test_get_account_balances_known_user():
    balances = services.get_account_balances("user_123")
    assert balances == {"checking_balance": 2000.0, "savings_balance": 5000.0}


def test_get_account_balances_unknown_user_returns_none():
    assert services.get_account_balances("nobody") is None


def test_get_security_question_known_user():
    assert "pet" in services.get_security_question("user_123").lower()


def test_get_security_question_unknown_user_returns_none():
    assert services.get_security_question("nobody") is None


def test_check_security_answer_is_case_and_space_insensitive():
    assert services.check_security_answer("user_123", "  rEx  ") is True
    assert services.check_security_answer("user_123", "wrong") is False
    assert services.check_security_answer("nobody", "Rex") is False


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
        services.execute_transfer("user_123", "checking", "savings", 999999)


def test_execute_transfer_unknown_user():
    with pytest.raises(services.TransferError):
        services.execute_transfer("nobody", "checking", "savings", 100)
