"""Mock database for the wealth management assistant.

Three small SQLite tables:

    users               -> user_id
    security_questions  -> user_id, position, question, answer   (TWO per user)
    accounts            -> user_id, checking_balance, savings_balance

The schema is multi-user (everything is keyed by user_id) and supports multiple
security questions per user. We seed TWO demo users, each with TWO different
security questions, so two things can be demonstrated:
  * multi-user isolation — the agent reads the active user from the authenticated
    session, never from the model, so one user can't touch another's money.
  * multi-question verification — both questions must be answered to verify.

It is created and seeded on first use so the agent, the tests, and the `adk` CLI
all see the same starting data. In production the answers would be stored as
salted hashes, never in plain text — this is a mock for evaluation.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# The SQLite file lives next to this module so it is easy to find and delete.
DATABASE_PATH = Path(__file__).parent / "wealth.db"

DEMO_USER_ID = "user_123"      # first user 
SECOND_USER_ID = "user_456"    # a second user

_SEED_USERS = [DEMO_USER_ID, SECOND_USER_ID]

# Two security questions per user; BOTH must be answered correctly to verify.
# Each user has different questions. (user_id, position, question, answer)
_SEED_QUESTIONS = [
    (DEMO_USER_ID,   0, "What is the name of your first pet?", "Rex"),
    (DEMO_USER_ID,   1, "What is your favorite color?",        "Blue"),
    (SECOND_USER_ID, 0, "In what city were you born?",         "Toronto"),
    (SECOND_USER_ID, 1, "What was the name of your first school?", "Maple"),
]

# (user_id, checking_balance, savings_balance)
_SEED_ACCOUNTS = [
    (DEMO_USER_ID,   2000.00, 5000.00),
    (SECOND_USER_ID, 8000.00, 12000.00),
]


def get_connection() -> sqlite3.Connection:
    """Open a connection to the mock database.

    Rows are returned as ``sqlite3.Row`` so callers can access columns by name
    (e.g. ``row["checking_balance"]``), which keeps the service code readable.
    """
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db(*, reset: bool = False) -> None:
    """Create the tables and insert the seed data if they do not exist yet.

    Args:
        reset: When True, drop the existing tables first — useful in tests so
            every run starts from known balances and a clean state.
    """
    with get_connection() as connection:
        if reset:
            connection.execute("DROP TABLE IF EXISTS users")
            connection.execute("DROP TABLE IF EXISTS security_questions")
            connection.execute("DROP TABLE IF EXISTS accounts")

        connection.execute(
            "CREATE TABLE IF NOT EXISTS users (user_id TEXT PRIMARY KEY)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS security_questions (
                user_id  TEXT    NOT NULL,
                position INTEGER NOT NULL,
                question TEXT     NOT NULL,
                answer   TEXT     NOT NULL,
                PRIMARY KEY (user_id, position),
                FOREIGN KEY (user_id) REFERENCES users (user_id)
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

        # Seed the demo data. "INSERT OR IGNORE" skips any row that already
        # exists, so re-running this never duplicates rows or overwrites data
        # (e.g. a balance changed by an earlier transfer).
        connection.executemany(
            "INSERT OR IGNORE INTO users (user_id) VALUES (?)",
            [(user_id,) for user_id in _SEED_USERS],
        )
        connection.executemany(
            "INSERT OR IGNORE INTO security_questions (user_id, position, question, answer) "
            "VALUES (?, ?, ?, ?)",
            _SEED_QUESTIONS,
        )
        connection.executemany(
            "INSERT OR IGNORE INTO accounts (user_id, checking_balance, savings_balance) "
            "VALUES (?, ?, ?)",
            _SEED_ACCOUNTS,
        )


# Create and seed the database as soon as the module is imported, so simply
init_db()
