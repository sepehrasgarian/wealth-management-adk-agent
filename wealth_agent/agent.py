"""The wealth management assistant, built with the Google Agent Development Kit.

The agent answers general portfolio questions directly, but enforces a strict
two-factor flow before any sensitive action (a transfer):

  1. Identity  — the security question is asked and the answer verified
                 (tracked by the verification state machine in security.py).
  2. Authority — the user explicitly confirms the exact transfer
                 (human-in-the-loop, handled inside transfer_funds).

The instruction below tells the model how to run the flow, but the real
enforcement is `security.security_gate`, registered as `before_tool_callback`:
even if the model tried to skip verification, the gate would block the transfer
in code. (LLM proposes, code disposes.)
"""

from __future__ import annotations

from google.adk.agents import Agent

from . import config, security
from .tools import (
    get_portfolio_balance,
    get_security_question,
    transfer_funds,
    verify_security_answer,
)

INSTRUCTION = """
You are a digital wealth management assistant for a brokerage platform. You help
the signed-in user with their checking and savings accounts.

You handle two kinds of requests:

1. General queries (for example, "What is my portfolio balance?").
   - Answer these directly. For balances, call `get_portfolio_balance` and report
     the checking, savings, and total balances clearly.

2. Sensitive actions (for example, "Transfer $500 from checking to savings").
   These ALWAYS require verification first. Follow these steps in order and never
   skip one:
     a. Call `get_security_question` and ask the user the exact question returned.
     b. When the user answers, call `verify_security_answer` with their answer.
     c. If verified is true, call `transfer_funds` with the source account,
        destination account, and amount. The user will be asked to confirm the
        exact transfer; once they confirm, report the result and the new balances.
     d. If verified is false, do NOT attempt the transfer. Tell the user that
        verification failed and the action was denied. If the account is locked,
        tell them it is locked due to too many failed attempts.

Important rules:
- Never reveal the security answer, and never perform a transfer without a
  successful verification in the current request.
- Only "checking" and "savings" accounts exist. Amounts must be positive.
- Be concise, clear, and professional.
"""

# `root_agent` is the symbol the ADK CLI and the evaluator look for.
root_agent = Agent(
    name="wealth_management_assistant",
    model=config.MODEL,
    description="Assistant for portfolio queries and verified account transfers.",
    instruction=INSTRUCTION,
    tools=[
        get_portfolio_balance,
        get_security_question,
        verify_security_answer,
        transfer_funds,
    ],
    # The security gate runs before every tool call and blocks sensitive tools
    # unless the session is verified. This is the authoritative enforcement.
    before_tool_callback=security.security_gate,
)
