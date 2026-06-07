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

from wealth_agent import database

# Directory holding the .evalset.json files and test_config.json.
EVAL_DIR = Path(__file__).parent.parent / "eval"

# The dotted module path ADK imports to find `root_agent`.
AGENT_MODULE = "wealth_agent"


@pytest.fixture(autouse=True)
def reset_database():
    """Start every test from the seeded balances so transfers are repeatable."""
    database.init_db(reset=True)


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
