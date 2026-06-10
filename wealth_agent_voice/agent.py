"""Voice variant of the wealth management assistant.

This is the SAME assistant as `wealth_agent` — identical tools, security gate,
services, and instruction — but it runs on a Gemini **Live** model so `adk web`
can use the microphone.

Why a separate agent? Gemini uses different model variants for text
(`generateContent`) and voice (`bidiGenerateContent`), with no overlap — so one
agent (which has a single model) can do text OR voice, not both. Exposing this
as a second app lets one `adk web` server offer both: the user picks
`wealth_agent` (text) or `wealth_agent_voice` (voice) from the dropdown.

Transfers are confirmed conversationally (the agent asks the user to say yes/no),
which works in voice as well as text. Run with:

    adk web wealth_agent_voice
"""

from __future__ import annotations

from google.adk.agents import Agent

# Reuse everything from the text agent — only the model changes.
from wealth_agent import config, model, observability, redaction, security
from wealth_agent.agent import INSTRUCTION
from wealth_agent.tools import (
    confirm_transfer,
    get_portfolio_balance,
    get_security_question,
    transfer_funds,
    verify_security_answer,
)

observability.setup_observability()

# `root_agent` is the symbol the ADK CLI looks for.
root_agent = Agent(
    name="wealth_management_assistant_voice",
    # The Live (half-cascade) model — supports voice (bidiGenerateContent) and
    # reliably calls tools. Same retry behavior as the text agent.
    model=model.build_model(config.LIVE_MODEL),
    description="Voice variant of the wealth assistant (same logic, Gemini Live model).",
    instruction=INSTRUCTION,
    tools=[
        get_portfolio_balance,
        get_security_question,
        verify_security_answer,
        transfer_funds,
        confirm_transfer,
    ],
    before_tool_callback=security.security_gate,
    after_tool_callback=observability.log_tool_activity,
    before_model_callback=redaction.redact_pii_before_model,
)
