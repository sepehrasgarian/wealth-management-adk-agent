"""Shared pytest fixtures for the test suite."""

from __future__ import annotations

import pytest

from wealth_agent import database
from tests.fakes import FakeToolContext


@pytest.fixture(autouse=True)
def fresh_database():
    """Reset the mock database before every test so balances are predictable."""
    database.init_db(reset=True)


@pytest.fixture
def ctx():
    """A fresh fake tool context for the demo user."""
    return FakeToolContext()
