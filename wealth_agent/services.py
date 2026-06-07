"""Service layer — the real business logic.

These functions do the actual work: read balances, look up the security
question, check an answer, and move money. They know nothing about the LLM or
ADK — they take plain arguments and return plain values — so they can be called
and unit-tested directly, with no agent and no API key.

The tools in tools.py are thin wrappers around these functions.
"""

from __future__ import annotations

from typing import Optional

from .database import get_connection

# The only account types that exist in this prototype.
ACCOUNTS = ("checking", "savings")


class TransferError(Exception):
    """Raised when a transfer cannot be completed (unknown account, same source
    and destination, non-positive amount, or insufficient funds). The message
    is safe to show to the user."""


def get_account_balances(user_id: str) -> Optional[dict]:
    """Return the user's balances, or None if the user has no accounts."""
    with get_connection() as connection:
        row = connection.execute(
            "SELECT checking_balance, savings_balance FROM accounts WHERE user_id = ?",
            (user_id,),
        ).fetchone()

    if row is None:
        return None
    return {
        "checking_balance": row["checking_balance"],
        "savings_balance": row["savings_balance"],
    }


def get_security_question(user_id: str) -> Optional[str]:
    """Return the user's security question, or None if the user is unknown."""
    with get_connection() as connection:
        row = connection.execute(
            "SELECT security_question FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()

    return row["security_question"] if row else None


def check_security_answer(user_id: str, answer: str) -> bool:
    """Return True if `answer` matches the user's stored security answer.

    The comparison ignores surrounding whitespace and letter case, so "rex"
    matches "Rex". In production the stored value would be a salted hash and we
    would compare hashes instead of plain text.
    """
    with get_connection() as connection:
        row = connection.execute(
            "SELECT security_answer FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()

    if row is None:
        return False
    return answer.strip().casefold() == row["security_answer"].strip().casefold()


def execute_transfer(
    user_id: str,
    from_account: str,
    to_account: str,
    amount: float,
) -> dict:
    """Move money between the user's own accounts and return the new balances.

    Raises TransferError if the request is invalid (unknown account, same
    source and destination, non-positive amount, or insufficient funds).
    """
    from_account = from_account.strip().casefold()
    to_account = to_account.strip().casefold()

    if from_account not in ACCOUNTS or to_account not in ACCOUNTS:
        raise TransferError("Accounts must be 'checking' or 'savings'.")
    if from_account == to_account:
        raise TransferError("Source and destination accounts must be different.")
    if amount <= 0:
        raise TransferError("Transfer amount must be greater than zero.")

    # Column names come from the fixed ACCOUNTS allow-list above, so building
    # them into the SQL string cannot be used for injection.
    from_column = f"{from_account}_balance"
    to_column = f"{to_account}_balance"

    # NOTE (mock simplification): the balance check and the update below are not
    # wrapped in a locked transaction, so they are not safe against concurrent
    # transfers for the same user. A production system would do the debit/credit
    # in a single atomic, row-locked transaction (e.g. SELECT ... FOR UPDATE).

    with get_connection() as connection:
        row = connection.execute(
            "SELECT checking_balance, savings_balance FROM accounts WHERE user_id = ?",
            (user_id,),
        ).fetchone()

        if row is None:
            raise TransferError("No accounts found for this user.")
        if row[from_column] < amount:
            raise TransferError(
                f"Insufficient funds: {from_account} balance is {row[from_column]:.2f}."
            )

        connection.execute(
            f"UPDATE accounts SET {from_column} = {from_column} - ?, "
            f"{to_column} = {to_column} + ? WHERE user_id = ?",
            (amount, amount, user_id),
        )
        updated = connection.execute(
            "SELECT checking_balance, savings_balance FROM accounts WHERE user_id = ?",
            (user_id,),
        ).fetchone()

    return {
        "checking_balance": updated["checking_balance"],
        "savings_balance": updated["savings_balance"],
    }
