"""Pytest wrapper around the ADK evalsets.

These tests run the same trajectory-based evalsets that `adk eval` runs, but
through pytest so they fit into a normal CI pipeline. Each test asks the
evaluator to run the agent against an evalset and check that the agent's tool
trajectory matches the expected one (see eval/test_config.json for the pass
threshold).

Requirements to run:
  * A Gemini API key in wealth_agent/.env (these tests make real LLM calls).
  * `pip install -r requirements.txt`

Run with:  pytest
"""

from __future__ import annotations

from pathlib import Path

import pytest
from google.adk.evaluation.agent_evaluator import AgentEvaluator

from wealth_agent import config, database

# Directory holding the .evalset.json files and test_config.json.
EVAL_DIR = Path(__file__).parent.parent / "eval"

# The dotted module path ADK imports to find `root_agent`.
AGENT_MODULE = "wealth_agent"


@pytest.fixture(autouse=True)
def deterministic_eval_environment(monkeypatch):
    """Make each eval run from a known, deterministic starting point.

    * Reset the database so transfers always start from the seeded balances.
    * Disable the human-in-the-loop confirmation: a trajectory eval cannot click
      "confirm", so we let the transfer complete directly. The confirmation flow
      itself is covered by the deterministic unit tests in test_tools.py.
    """
    database.init_db(reset=True)
    monkeypatch.setattr(config, "REQUIRE_TRANSFER_CONFIRMATION", False)


@pytest.mark.asyncio
async def test_blocked_transfer_unauthenticated():
    """A wrong security answer must block the transfer (no transfer_funds call)."""
    await AgentEvaluator.evaluate(
        agent_module=AGENT_MODULE,
        eval_dataset_file_path_or_dir=str(EVAL_DIR / "blocked_transfer.evalset.json"),
    )


@pytest.mark.asyncio
async def test_successful_transfer_authenticated():
    """A correct security answer must allow the transfer to complete."""
    await AgentEvaluator.evaluate(
        agent_module=AGENT_MODULE,
        eval_dataset_file_path_or_dir=str(EVAL_DIR / "successful_transfer.evalset.json"),
    )


@pytest.mark.asyncio
async def test_adversarial_cannot_bypass_verification():
    """Prompt-injection / urgency pressure must not skip verification."""
    await AgentEvaluator.evaluate(
        agent_module=AGENT_MODULE,
        eval_dataset_file_path_or_dir=str(EVAL_DIR / "adversarial.evalset.json"),
    )
