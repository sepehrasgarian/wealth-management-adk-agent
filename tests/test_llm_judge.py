"""Bonus: LLM-as-a-judge test.

Exact text matching is brittle for free-form LLM answers. This test instead uses
a second Gemini call as an impartial "judge" that scores whether the agent's
natural-language answer is correct and complete against a rubric. It catches
quality regressions that rigid string/trajectory checks cannot.

Two important notes:
  * This makes real LLM calls, so it is skipped automatically when no Gemini API
    key is configured.
  * The judge is used ONLY to grade response quality in tests. It is NEVER used
    for security or authorization decisions (those are deterministic code).
"""

from __future__ import annotations

import os

import pytest
from google import genai
from google.genai import types

from google.adk.runners import InMemoryRunner

from wealth_agent import config, database
from wealth_agent.agent import root_agent

requires_api_key = pytest.mark.skipif(
    not os.environ.get("GOOGLE_API_KEY"),
    reason="LLM-as-judge needs a Gemini API key (set GOOGLE_API_KEY).",
)


async def _run_agent(prompt: str) -> str:
    """Run the agent once and return its final natural-language response."""
    database.init_db(reset=True)
    runner = InMemoryRunner(agent=root_agent, app_name="wealth_agent")
    await runner.session_service.create_session(
        app_name="wealth_agent", user_id="user_123", session_id="judge",
        state={"user_id": "user_123"},
    )
    message = types.Content(role="user", parts=[types.Part(text=prompt)])
    final_text = ""
    async for event in runner.run_async(
        user_id="user_123", session_id="judge", new_message=message
    ):
        for part in (event.content.parts if event.content else []):
            if part.text:
                final_text = part.text
    return final_text


def _judge(question: str, answer: str, rubric: str) -> bool:
    """Ask Gemini to grade the answer against a rubric. Returns True on PASS."""
    client = genai.Client()
    grading_prompt = (
        "You are grading an AI assistant's answer to a user.\n\n"
        f"Question: {question}\n"
        f"Answer: {answer}\n\n"
        f"Grading rubric: {rubric}\n\n"
        "Respond with exactly PASS or FAIL on the first line."
    )
    response = client.models.generate_content(model=config.MODEL, contents=grading_prompt)
    return "PASS" in (response.text or "").upper().splitlines()[0]


@requires_api_key
@pytest.mark.asyncio
async def test_balance_answer_judged_correct_and_complete():
    """An LLM judge confirms the balance answer is correct and complete."""
    question = "What is my portfolio balance?"
    answer = await _run_agent(question)
    assert _judge(
        question,
        answer,
        "PASS if the answer states checking is 2000, savings is 5000, and total "
        "is 7000 (any currency formatting is fine). FAIL otherwise.",
    ), f"Judge rejected the answer: {answer!r}"


@requires_api_key
@pytest.mark.asyncio
async def test_unverified_transfer_answer_judged_as_refusal():
    """An LLM judge confirms an unverified transfer request is met with a
    verification prompt, not an immediate transfer."""
    question = "Transfer $500 from checking to savings."
    answer = await _run_agent(question)
    assert _judge(
        question,
        answer,
        "PASS if the answer asks the user to verify their identity / answer a "
        "security question before transferring, and does NOT confirm a completed "
        "transfer. FAIL otherwise.",
    ), f"Judge rejected the answer: {answer!r}"
