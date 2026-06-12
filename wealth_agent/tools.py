"""Tools the agent can call — thin, LLM-facing adapters.

Each tool does three small jobs:
  1. read the signed-in user from session state,
  2. call the matching service (services.py) and/or update the verification
     state machine (security.py),
  3. return a small status dict the model can act on.

"""

from __future__ import annotations

from google.adk.tools.tool_context import ToolContext

from . import config, security, services
from .database import DEMO_USER_ID
from .security import VerificationState

# Session-state key holding the authenticated user id.
STATE_USER_ID = "user_id"
# Session-state key holding a transfer awaiting conversational confirmation.
STATE_PENDING_TRANSFER = "pending_transfer"


def _current_user_id(tool_context: ToolContext) -> str:
    """Return the authenticated user for this session.

    The user is taken from session state. 
    """
    return tool_context.state.get(STATE_USER_ID, DEMO_USER_ID)


def _perform_transfer(
    tool_context: ToolContext,
    from_account: str,
    to_account: str,
    amount: float,
) -> dict:
    """Run the transfer via the service layer, then clear verification and audit it.

    Shared by every confirmation path (none / button / conversational) so the
    actual money movement and bookkeeping live in exactly one place.
    """
    user_id = _current_user_id(tool_context)
    config.trace(f"[TOOL] _perform_transfer: {from_account}→{to_account} ${amount} (user={user_id})")
    try:
        balances = services.execute_transfer(user_id, from_account, to_account, amount)
    except services.TransferError as error:
        return {"status": "error", "message": str(error)}

    # Verification is single-use: clear it so the next transfer must re-verify.
    security.consume(tool_context.state)

    # Audit the completed sensitive action (amount + accounts only — no secrets).
    security.log_security_event(
        "transfer_completed",
        tool_context,
        user_id=user_id,
        from_account=from_account,
        to_account=to_account,
        amount=amount,
    )
    return {
        "status": "success",
        "message": f"Transferred {amount:.2f} from {from_account} to {to_account}.",
        **balances,
    }


def get_portfolio_balance(tool_context: ToolContext) -> dict:
    """Return the signed-in user's checking and savings balances.

    This is a general, non-sensitive query, so it needs no verification.

    Returns:
        {"status": "success", "checking_balance", "savings_balance",
        "total_balance"} or {"status": "error", "message"}.
    """
    user_id = _current_user_id(tool_context)
    config.trace(f"[TOOL] get_portfolio_balance (user={user_id})")
    balances = services.get_account_balances(user_id)
    if balances is None:
        return {"status": "error", "message": "No accounts found for this user."}

    total = round(balances["checking_balance"] + balances["savings_balance"], 2)
    return {"status": "success", **balances, "total_balance": total}


def get_security_question(tool_context: ToolContext) -> dict:
    """Retrieve the FIRST security question and begin verification.

    Call this first whenever the user requests a sensitive action (such as a
    transfer). The user has more than one security question; ask the returned
    question, pass the reply to `verify_security_answer`, and it will tell you
    the next question to ask until the user is verified.

    Returns:
        {"status": "success", "security_question"} or {"status": "error",
        "message"} (for example, if the account is locked).
    """
    user_id = _current_user_id(tool_context)
    config.trace(f"[TOOL] get_security_question (user={user_id})")

    # Idempotent: if the session is already verified (and still fresh), don't
    # restart the challenge — that would throw away a valid verification. Tell the
    # agent to proceed instead of re-asking.
    if security.is_verified(tool_context.state):
        return {
            "status": "success",
            "already_verified": True,
            "message": "The user is already verified. Proceed with the requested action; do not ask a security question.",
        }
    # Get the security questions since start_challenge requires it
    questions = services.get_security_questions(user_id)
    if not questions:
        return {"status": "error", "message": "No security questions on file for this user."}

    status = security.start_challenge(tool_context.state, total_questions=len(questions))
    if status == VerificationState.LOCKED:
        security.log_security_event("verification_locked", tool_context, user_id=user_id)
        return {
            "status": "error",
            "message": "This account is locked due to too many failed verification attempts.",
        }

    return {"status": "success", "security_question": questions[0]}


def verify_security_answer(answer: str, tool_context: ToolContext) -> dict:
    """Check the user's answer to the CURRENT security question.

    The user must answer all of their security questions correctly to be
    verified. The result tells you what to do next:
      * verified=true  -> identity confirmed; proceed.
      * locked=true    -> too many wrong answers; deny.
      * otherwise a `next_question` is returned -> ask it and call this again.

    Args:
        answer: The answer the user gave to the current security question.

    Returns:
        {"status": "success", "verified": bool, "locked": bool,
        "next_question"?: str, "attempts_remaining"?: int}.
    """
    user_id = _current_user_id(tool_context)
    config.trace(f"[TOOL] verify_security_answer (user={user_id}, answer=***)")

    # Be robust to the model's call order: if verification wasn't started 
    # start_challenge sets total_questions (the user's full question count), so a
    # single answer can never satisfy the multi-question requirement. It just
    # means the agent can verify even if it forgot to fetch the question first.
    if security.get_state(tool_context.state)["status"] != VerificationState.CHALLENGED:
        questions = services.get_security_questions(user_id)
        if not questions:
            return {"status": "error", "message": "No security questions on file for this user."}
        if security.start_challenge(tool_context.state, total_questions=len(questions)) == VerificationState.LOCKED:
            security.log_security_event("verification_locked", tool_context, user_id=user_id)
            return {"status": "success", "verified": False, "locked": True}

    index = security.current_question_index(tool_context.state)
    is_correct = services.check_security_answer(user_id, index, answer)
    status = security.record_answer(tool_context.state, is_correct)

    if status == VerificationState.VERIFIED:
        return {"status": "success", "verified": True, "locked": False}

    if status == VerificationState.LOCKED:
        security.log_security_event("verification_locked", tool_context, user_id=user_id)
        return {"status": "success", "verified": False, "locked": True}

    # Still CHALLENGED — another question must be answered. The `answer_correct`
    # flag tells the agent whether this answer was right (advance to the next
    # question) or wrong (retry the same one), so it phrases the reply correctly.
    next_index = security.current_question_index(tool_context.state)

    questions = services.get_security_questions(user_id)
    next_question = questions[next_index] if next_index < len(questions) else None

    if is_correct:
        return {
            "status": "success",
            "verified": False,
            "locked": False,
            "answer_correct": True,
            "next_question": next_question,
        }

    security.log_security_event("verification_failed", tool_context, user_id=user_id)
    return {
        "status": "success",
        "verified": False,
        "locked": False,
        "answer_correct": False,
        "attempts_remaining": security.attempts_remaining(tool_context.state),
        "next_question": next_question,
    }


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
        or {"status": "confirmation_required"/"error", "message"}.
    """
    user_id = _current_user_id(tool_context)
    config.trace(f"[TOOL] transfer_funds: {from_account}→{to_account} ${amount} (user={user_id})")

    # Validate up front: reject an impossible transfer (bad account, over the
    # limit, insufficient funds) IMMEDIATELY — before asking the user to confirm —
    # so they get a clear "no" instead of going through confirmation only to fail.
    try:
        services.validate_transfer(user_id, from_account, to_account, amount)
    except services.TransferError as error:
        return {"status": "error", "message": str(error)}

    # No confirmation required (deterministic trajectory evals): transfer directly.
    if not config.REQUIRE_TRANSFER_CONFIRMATION:
        return _perform_transfer(tool_context, from_account, to_account, amount)

    # Human-in-the-loop confirmation: record the pending transfer and ask the user
    # to confirm in their next message. The agent then calls confirm_transfer with
    # their yes/no. This one path works in both text and voice.
    tool_context.state[STATE_PENDING_TRANSFER] = {
        "from_account": from_account,
        "to_account": to_account,
        "amount": amount,
    }
    return {
        "status": "confirmation_required",
        "message": (
            f"Please confirm with the user: transfer {amount:.2f} from "
            f"{from_account} to {to_account}. Ask them to say yes to proceed or no "
            f"to cancel, then call confirm_transfer with their answer."
        ),
    }


def confirm_transfer(approve: bool, tool_context: ToolContext) -> dict:
    """Confirm or cancel a transfer the user was asked to approve (SENSITIVE action).

    Call this only after `transfer_funds` returned status "confirmation_required"
    and the user has replied. This is the voice-friendly confirmation path.

    Args:
        approve: True if the user said yes (proceed), False if they said no (cancel).

    Returns:
        On approve+success: {"status": "success", "message", "checking_balance",
        "savings_balance"}. On cancel or if nothing is pending:
        {"status": "error", "message"}.
    """
    config.trace(f"[TOOL] confirm_transfer(approve={approve})")
    pending = tool_context.state.get(STATE_PENDING_TRANSFER)
    if not pending:
        return {"status": "error", "message": "There is no transfer awaiting confirmation."}

    # Clear the pending request either way, so it cannot be reused.
    tool_context.state[STATE_PENDING_TRANSFER] = None

    if not approve:
        security.log_security_event("transfer_declined_by_user", tool_context)
        return {"status": "error", "message": "Transfer cancelled."}

    return _perform_transfer(
        tool_context,
        pending["from_account"],
        pending["to_account"],
        pending["amount"],
    )
