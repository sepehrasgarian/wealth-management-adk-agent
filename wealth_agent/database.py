"""Mock database for the wealth management assistant.

This module owns a small SQLite database with two tables, exactly as the
assignment requires:

    Users    -> user_id, security_question, security_answer
    Accounts -> user_id, checking_balance, savings_balance

The database is intentionally simple. It is created and seeded on first use so
that the agent, the tests, and the `adk` CLI all see the same starting data.

In a real system this layer would talk to a secured production database and the
security answer would be stored as a salted hash, never in plain text. We keep
it in plain text here only because this is a mock for evaluation.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# The SQLite file lives next to this module so it is easy to find and delete.
DATABASE_PATH = Path(__file__).parent / "wealth.db"

# Seed data. One demo user with one set of accounts. The agent reads the active
# user from session state (see tools.py), defaulting to this user.
DEMO_USER_ID = "user_123"

_SEED_USERS = [
    {
        "user_id": DEMO_USER_ID,
        "security_question": "What is the name of your first pet?",
        "security_answer": "Rex",
    },
]

_SEED_ACCOUNTS = [
    {
        "user_id": DEMO_USER_ID,
        "checking_balance": 2000.00,
        "savings_balance": 5000.00,
    },
]


def get_connection() -> sqlite3.Connection:
    """Open a connection to the mock database.

    Rows are returned as ``sqlite3.Row`` objects so callers can access columns
    by name (for example ``row["checking_balance"]``), which keeps the tool
    code readable.
    """
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db(*, reset: bool = False) -> None:
    """Create the tables and insert the seed data if they do not exist yet.

    Args:
        reset: When True, drop the existing tables first. This is useful in
            tests so every run starts from a known balance.
    """
    with get_connection() as connection:
        if reset:
            connection.execute("DROP TABLE IF EXISTS users")
            connection.execute("DROP TABLE IF EXISTS accounts")

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id           TEXT PRIMARY KEY,
                security_question TEXT NOT NULL,
                security_answer   TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                user_id          TEXT PRIMARY KEY,
                checking_balance REAL NOT NULL,
                savings_balance  REAL NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
            """
        )

        # Only seed when the tables are empty so we never overwrite live data.
        already_seeded = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if not already_seeded:
            connection.executemany(
                "INSERT INTO users (user_id, security_question, security_answer) "
                "VALUES (:user_id, :security_question, :security_answer)",
                _SEED_USERS,
            )
            connection.executemany(
                "INSERT INTO accounts (user_id, checking_balance, savings_balance) "
                "VALUES (:user_id, :checking_balance, :savings_balance)",
                _SEED_ACCOUNTS,
            )


# Create and seed the database as soon as the module is imported so that simply
# importing the agent gives you a working, populated database.
init_db()
