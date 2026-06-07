"""Central configuration — the single source of truth for every tunable value.

Every number, model name, path, and feature toggle in the project lives here so
you never have to hunt through the logic to change one. Each setting reads from
an environment variable (so you can override it via wealth_agent/.env without
editing code) and falls back to a sensible default.

Usage in other modules:
    from . import config
    if attempts >= config.MAX_FAILED_ATTEMPTS: ...
"""

from __future__ import annotations

import os
from pathlib import Path

# Load wealth_agent/.env so values set there are visible here, regardless of how
# the app is started. ADK also loads this file; loading it again is harmless.
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parent / ".env")
except Exception:
    # python-dotenv is optional; without it we simply rely on real env vars.
    pass


# ---------------------------------------------------------------------------
# Small helpers: read an env var with a typed default.
# ---------------------------------------------------------------------------

def env(name: str, default: str) -> str:
    """Read a string setting from the environment, or use the default."""
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def env_int(name: str, default: int) -> int:
    """Read an integer setting; fall back to the default if missing/invalid."""
    raw = os.environ.get(name)
    try:
        return int(raw) if raw not in (None, "") else default
    except ValueError:
        return default


def env_bool(name: str, default: bool) -> bool:
    """Read a boolean setting. Accepts true/1/yes/on (any case) as True."""
    raw = os.environ.get(name)
    if raw in (None, ""):
        return default
    return raw.strip().lower() in {"true", "1", "yes", "on"}


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

# The Gemini model the assistant uses for normal (text) interactions.
MODEL = env("WEALTH_MODEL", "gemini-2.5-flash")

# A Gemini "Live" model used only for the optional voice demo (run via adk web).
# Must support the Live API (bidiGenerateContent). To enable voice, set
# WEALTH_MODEL to this value (or another Live model) and restart `adk web`.
LIVE_MODEL = env("WEALTH_LIVE_MODEL", "gemini-2.5-flash-native-audio-latest")


# ---------------------------------------------------------------------------
# Security — verification state machine
# ---------------------------------------------------------------------------

# How long a successful verification stays valid, in seconds.
VERIFICATION_TTL_SECONDS = env_int("WEALTH_VERIFICATION_TTL_SECONDS", 120)

# How many wrong security answers are allowed before the session is LOCKED.
MAX_FAILED_ATTEMPTS = env_int("WEALTH_MAX_FAILED_ATTEMPTS", 3)

# Tool names that move money / take sensitive action and therefore require a
# verified session. The security gate protects every tool listed here.
SENSITIVE_TOOLS = {"transfer_funds", "confirm_transfer"}

# Whether transfers require an explicit human-in-the-loop confirmation before the
# money moves. On by default for real use and the adk web demo. It is turned OFF
# only for trajectory evals (which cannot simulate a human clicking "confirm"),
# so those tests run deterministically; the confirmation logic is covered
# separately by unit tests.
REQUIRE_TRANSFER_CONFIRMATION = env_bool("WEALTH_REQUIRE_TRANSFER_CONFIRMATION", True)

# How the user confirms a transfer:
#   "button"        -> native ADK confirmation button (best in text / adk web,
#                      but NOT supported in voice/live mode).
#   "conversational"-> the agent asks the user to say "yes"/"no" (works in BOTH
#                      voice and text). Use this for the voice demo.
CONFIRMATION_MODE = env("WEALTH_CONFIRMATION_MODE", "button")


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

# Location of the SQLite mock database file.
DATABASE_PATH = Path(env("WEALTH_DB_PATH", str(Path(__file__).parent / "wealth.db")))


# ---------------------------------------------------------------------------
# Observability (OpenTelemetry / Langfuse)
# ---------------------------------------------------------------------------

# Master switch for exporting traces. Off by default so the app runs with no
# external dependencies; turn on once Langfuse/OTLP credentials are configured.
TRACING_ENABLED = env_bool("WEALTH_TRACING_ENABLED", False)

# Standard OpenTelemetry OTLP endpoint and headers (e.g. pointing at Langfuse).
OTLP_ENDPOINT = env("OTEL_EXPORTER_OTLP_ENDPOINT", "")
OTLP_HEADERS = env("OTEL_EXPORTER_OTLP_HEADERS", "")

# A human-friendly service name attached to every trace.
SERVICE_NAME = env("WEALTH_SERVICE_NAME", "wealth-management-assistant")
