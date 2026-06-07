"""Tools the agent can call — thin, LLM-facing adapters.

Each tool does three small jobs:
  1. read the signed-in user from session state,
  2. call the matching service (services.py) and/or update the verification
     state machine (security.py),
  3. return a small status dict the model can act on.

Because the real work lives in services.py and the security rules live in
security.py, these functions stay short and easy to read.
"""

from __future__ import annotations

from google.adk.tools.tool_context import ToolContext

from . import security, services
from .database import DEMO_USER_ID

# Session-state key holding the authenticated user id.
STATE_USER_ID = "user_id"


def _current_user_id(tool_context: ToolContext) -> str:
    """Return the authenticated user for this session.

    The user is taken from session state (set from an authenticated session in a
    real system), never from the model. We fall back to the demo user so the
    agent also works out of the box in `adk web`.
    """
    return tool_context.state.get(STATE_USER_ID, DEMO_USER_ID)


def get_portfolio_balance(tool_context: ToolContext) -> dict:
    """Return the signed-in user's checking and savings balances.

    This is a general, non-sensitive query, so it needs no verification.

    Returns:
        {"status": "success", "checking_balance", "savings_balance",
        "total_balance"} or {"status": "error", "message"}.
    """
    user_id = _current_user_id(tool_context)
    balances = services.get_account_balances(user_id)
    if balances is None:
        return {"status": "error", "message": "No accounts found for this user."}

    total = round(balances["checking_balance"] + balances["savings_balance"], 2)
    return {"status": "success", **balances, "total_balance": total}


def get_security_question(tool_context: ToolContext) -> dict:
    """Retrieve the user's security question and begin verification.

    Call this first whenever the user requests a sensitive action (such as a
    transfer). Then ask the user the returned question and pass their reply to
    `verify_security_answer`.

    Returns:
        {"status": "success", "security_question"} or {"status": "error",
        "message"} (for example, if the account is locked).
    """
    user_id = _current_user_id(tool_context)
    question = services.get_security_question(user_id)
    if question is None:
        return {"status": "error", "message": "No security question on file for this user."}

    status = security.start_challenge(tool_context.state)
    if status == security.LOCKED:
        security.log_security_event("verification_locked", tool_context, user_id=user_id)
        return {
            "status": "error",
            "message": "This account is locked due to too many failed verification attempts.",
        }

    return {"status": "success", "security_question": question}


def verify_security_answer(answer: str, tool_context: ToolContext) -> dict:
    """Check the user's answer to their security question.

    The result is recorded in the verification state machine. A correct answer
    makes the session VERIFIED; repeated wrong answers eventually LOCK it.

    Args:
        answer: The answer the user gave to their security question.

    Returns:
        {"status": "success", "verified": bool, "locked": bool}.
    """
    user_id = _current_user_id(tool_context)
    is_correct = services.check_security_answer(user_id, answer)
    status = security.record_answer(tool_context.state, is_correct)

    if status == security.VERIFIED:
        return {"status": "success", "verified": True, "locked": False}

    # Not verified: record the failed attempt (and a lockout, if it happened).
    is_locked = status == security.LOCKED
    security.log_security_event(
        "verification_locked" if is_locked else "verification_failed",
        tool_context,
        user_id=user_id,
    )
    return {"status": "success", "verified": False, "locked": is_locked}


def transfer_funds(
    from_account: str,
    to_account: str,
    amount: float,
    tool_context: ToolContext,
) -> dict:
    """Transfer money between the signed-in user's accounts (SENSITIVE action).

    Two independent controls protect this tool:
      1. The security gate (registered on the agent) blocks it unless the
         session is VERIFIED — this runs before we even get here.
      2. Human-in-the-loop: we ask the user to explicitly confirm THIS exact
         transfer before any money moves.

    Args:
        from_account: "checking" or "savings".
        to_account: "checking" or "savings".
        amount: Positive amount of money to move.

    Returns:
        {"status": "success", "message", "checking_balance", "savings_balance"},
        or {"status": "pending"/"error", "message"}.
    """
    # --- Human-in-the-loop confirmation of the exact transfer ---
    confirmation = tool_context.tool_confirmation
    if confirmation is None:
        # First call: pause and ask the human to approve this specific transfer.
        tool_context.request_confirmation(
            hint=f"Please confirm: transfer {amount:.2f} from {from_account} to {to_account}."
        )
        return {"status": "pending", "message": "Awaiting your confirmation of this transfer."}

    if not confirmation.confirmed:
        # The human declined the confirmation.
        security.log_security_event("transfer_declined_by_user", tool_context)
        return {"status": "error", "message": "Transfer cancelled: you declined the confirmation."}

    # --- Confirmed: perform the transfer through the service layer ---
    user_id = _current_user_id(tool_context)
    try:
        balances = services.execute_transfer(user_id, from_account, to_account, amount)
    except services.TransferError as error:
        return {"status": "error", "message": str(error)}

    # Verification is single-use: clear it so the next transfer must re-verify.
    security.consume(tool_context.state)

    return {
        "status": "success",
        "message": f"Transferred {amount:.2f} from {from_account} to {to_account}.",
        **balances,
    }
