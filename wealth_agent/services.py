"""Service layer — the real business logic.

These functions do the actual work: read balances, look up the security
question, check an answer, and move money. They know nothing about the LLM or
ADK — they take plain arguments and return plain values — so they can be called
and unit-tested directly, with no agent and no API key.

The tools in tools.py are thin wrappers around these functions.
"""

from __future__ import annotations

from typing import Optional

from . import config
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


def get_security_questions(user_id: str) -> list[str]:
    """Return the user's security questions in order (empty list if unknown).

    Each user has more than one question; ALL must be answered to verify.
    """
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT question FROM security_questions WHERE user_id = ? ORDER BY position",
            (user_id,),
        ).fetchall()
    return [row["question"] for row in rows]


def get_security_question(user_id: str, position: int) -> Optional[str]:
    """Return the user's security question at `position`, or None if missing."""
    with get_connection() as connection:
        row = connection.execute(
            "SELECT question FROM security_questions WHERE user_id = ? AND position = ?",
            (user_id, position),
        ).fetchone()
    return row["question"] if row else None


def check_security_answer(user_id: str, position: int, answer: str) -> bool:
    """Return True if `answer` matches the stored answer at `position`.

    The comparison ignores surrounding whitespace and letter case, so "rex"
    matches "Rex". In production the stored value would be a salted hash and we
    would compare hashes instead of plain text.
    """
    with get_connection() as connection:
        row = connection.execute(
            "SELECT answer FROM security_questions WHERE user_id = ? AND position = ?",
            (user_id, position),
        ).fetchone()

    if row is None:
        return False
    return answer.strip().casefold() == row["answer"].strip().casefold()


def validate_transfer(
    user_id: str,
    from_account: str,
    to_account: str,
    amount: float,
) -> tuple[str, str]:
    """Check that a transfer is allowed WITHOUT moving any money.

    Raises TransferError if the request is invalid (unknown account, same
    source and destination, non-positive amount, over the per-transfer limit,
    or insufficient funds). Returns the normalized (from_account, to_account).

    Used to reject an impossible transfer up front — before asking the user to
    confirm — so they get an immediate, clear "no" instead of going through the
    whole verification/confirmation flow only to fail at the end.
    """
    from_account = from_account.strip().casefold()
    to_account = to_account.strip().casefold()

    if from_account not in ACCOUNTS or to_account not in ACCOUNTS:
        raise TransferError("Accounts must be 'checking' or 'savings'.")
    if from_account == to_account:
        raise TransferError("Source and destination accounts must be different.")
    if amount <= 0:
        raise TransferError("Transfer amount must be greater than zero.")
    if amount > config.MAX_TRANSFER_AMOUNT:
        raise TransferError(
            f"Transfer amount exceeds the per-transfer limit of "
            f"{config.MAX_TRANSFER_AMOUNT:.2f}."
        )

    balances = get_account_balances(user_id)
    if balances is None:
        raise TransferError("No accounts found for this user.")
    from_balance = balances[f"{from_account}_balance"]
    if from_balance < amount:
        raise TransferError(
            f"Insufficient funds: your {from_account} balance is "
            f"{from_balance:.2f}, so you cannot transfer {amount:.2f}."
        )

    return from_account, to_account


def execute_transfer(
    user_id: str,
    from_account: str,
    to_account: str,
    amount: float,
) -> dict:
    """Move money between the user's own accounts and return the new balances.

    Re-validates with `validate_transfer` (so it is safe to call directly), then
    performs the debit/credit. Raises TransferError if the request is invalid.
    """
    # Validate again here (the amount/balance may have changed since the up-front
    # check) and get the normalized account names.
    from_account, to_account = validate_transfer(user_id, from_account, to_account, amount)

    # Column names come from the fixed ACCOUNTS allow-list, so building them into
    # the SQL string cannot be used for injection.
    from_column = f"{from_account}_balance"
    to_column = f"{to_account}_balance"

    # NOTE (mock simplification): validation and the update below are not wrapped
    # in a single locked transaction, so they are not safe against concurrent
    # transfers for the same user. A production system would do the debit/credit
    # in one atomic, row-locked transaction (e.g. SELECT ... FOR UPDATE).

    with get_connection() as connection:
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
