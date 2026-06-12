"""The wealth management assistant, built with the Google Agent Development Kit.

The agent answers general portfolio questions directly, but enforces a strict
two-factor flow before any sensitive action (a transfer):

  1. Identity  — the security question is asked and the answer verified
                 (tracked by the verification state machine in security.py).
  2. Authority — the user explicitly confirms the exact transfer
                 (human-in-the-loop, handled inside transfer_funds).

"""

from __future__ import annotations

from google.adk.agents import Agent

from . import config, model, observability, redaction, security
from .tools import (
    confirm_transfer,
    get_portfolio_balance,
    get_security_question,
    transfer_funds,
    verify_security_answer,
)

# Configure logging and (if WEALTH_TRACING_ENABLED) export OpenTelemetry traces
# to the configured OTLP backend (e.g. Langfuse) before the agent runs.
observability.setup_observability()

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
        The user has MORE THAN ONE security question and must answer all of them.
        Read the result:
        - verified=true  → identity confirmed; proceed to the transfer (step c).
        - locked=true    → too many failed attempts; deny (step e).
        - answer_correct=true with a `next_question` → that answer was correct but
          another question remains. Tell the user it was correct, ask the
          `next_question`, then call `verify_security_answer` again.
        - answer_correct=false with a `next_question` → that answer was WRONG. Tell
          the user it was incorrect, mention how many attempts remain
          (attempts_remaining), ask the `next_question` again, and call
          `verify_security_answer` again.
     c. The moment `verify_security_answer` returns verified=true, IMMEDIATELY call
        `transfer_funds` in the SAME turn with the source account, destination
        account, and amount the user asked for. Do NOT stop after saying the user
        is verified, and do NOT make them repeat the request — proceed straight to
        `transfer_funds`. It returns status "confirmation_required": tell the user
        the exact transfer and ask them to confirm by saying yes or no. When they
        reply, call `confirm_transfer` with approve=true (yes) or approve=false
        (no), then report the result and the new balances.
     d. If verified is false and locked is false, the answer was wrong but the
        user may try again. Tell them the answer was incorrect, mention how many
        attempts remain (attempts_remaining), and ask them to answer the security
        question again. Do NOT call get_security_question again and do NOT start
        over — simply call `verify_security_answer` again with their new answer.
     e. If locked is true, the account is locked due to too many failed attempts.
        Tell the user the action is denied because the account is locked, and do
        not continue the verification.

Important rules:
- Always ask the exact security-question text returned by `get_security_question`
  or by the `next_question` field. Never make up your own security question.
- Never reveal the security answer, and never perform a transfer without a
  successful verification in the current request.
- If a tool returns status "error" (for example insufficient funds or over the
  per-transfer limit), report that exact reason to the user. Do NOT restart
  verification or invent a different reason.
- Only "checking" and "savings" accounts exist. Amounts must be positive.
- Be concise, clear, and professional.
"""

# `root_agent` is the symbol the ADK CLI and the evaluator look for.
root_agent = Agent(
    name="wealth_management_assistant",
    # A Gemini model that retries transient HTTP errors AND regenerates empty
    # responses (see model.py), so a momentary "no reply" is handled gracefully.
    model=model.build_model(),
    description="Assistant for portfolio queries and verified account transfers.",
    instruction=INSTRUCTION,
    tools=[
        get_portfolio_balance,
        get_security_question,
        verify_security_answer,
        transfer_funds,
        confirm_transfer,
    ],
    # The security gate runs before every tool call and blocks sensitive tools
    # unless the session is verified. This is the authoritative enforcement.
    before_tool_callback=security.security_gate,
    # Telemetry: log every tool call + result as structured text (works in text
    # AND voice), and attach it to the trace. Makes voice sessions observable.
    after_tool_callback=observability.log_tool_activity,
    # PII guardrail: mask card numbers / SSNs / long digit runs in user input
    # before it reaches the model (defense in depth; see redaction.py).
    before_model_callback=redaction.redact_pii_before_model,
)
