"""Central configuration 

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


def env_float(name: str, default: float) -> float:
    """Read a float setting; fall back to the default if missing/invalid."""
    raw = os.environ.get(name)
    try:
        return float(raw) if raw not in (None, "") else default
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

# The Gemini model the assistant uses for normal (text) interactions.
MODEL = env("WEALTH_MODEL", "gemini-2.5-flash")

# Model retry settings (robustness when the model fails to respond).
# client this many times.
MODEL_HTTP_RETRY_ATTEMPTS = env_int("WEALTH_MODEL_HTTP_RETRY_ATTEMPTS", 3)
# Occasionally Gemini returns an EMPTY response (no text, no tool call) — not an
MODEL_EMPTY_RESPONSE_RETRIES = env_int("WEALTH_MODEL_EMPTY_RESPONSE_RETRIES", 2)

# A Gemini "Live" model for the optional voice demo (run via adk web).
# Must support the Live API (bidiGenerateContent). Use a HALF-CASCADE model
# (e.g. gemini-3.1-flash-live-preview), NOT a native-audio model: half-cascade
# converts audio->text internally so FUNCTION CALLING is reliable, whereas
# native-audio models have limited/unreliable tool calling in preview. Since
# this agent is tool-heavy (verify/transfer), half-cascade is required.
# To enable voice: set WEALTH_MODEL to this value and restart `adk web`.
LIVE_MODEL = env("WEALTH_LIVE_MODEL", "gemini-3.1-flash-live-preview")


# ---------------------------------------------------------------------------
# Security — verification state machine
# ---------------------------------------------------------------------------

# How long a successful verification stays valid, in seconds.
VERIFICATION_TTL_SECONDS = env_int("WEALTH_VERIFICATION_TTL_SECONDS", 180)

# How many wrong security answers are allowed before the session is LOCKED.
MAX_FAILED_ATTEMPTS = env_int("WEALTH_MAX_FAILED_ATTEMPTS", 3)

# Maximum amount allowed in a single transfer. 
# request above this is rejected. 
MAX_TRANSFER_AMOUNT = env_float("WEALTH_MAX_TRANSFER_AMOUNT", 10000.0)

# Tool names that move money / take sensitive action and therefore require a
# verified session. The security gate protects every tool listed here.
SENSITIVE_TOOLS = {"transfer_funds", "confirm_transfer"}

# Whether transfers require an explicit human-in-the-loop confirmation before the
# money moves. The agent asks the user to confirm by saying "yes"/"no" (one path
# that works in both text and voice). Set to false only for deterministic
# trajectory evals, which cannot answer a confirmation prompt.
REQUIRE_TRANSFER_CONFIRMATION = env_bool("WEALTH_REQUIRE_TRANSFER_CONFIRMATION", True)


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

# Application log file. Structured logs and security audit events are written
# here (append-only) as well as to the console, so there's a durable trail.
LOG_FILE = env("WEALTH_LOG_FILE", "wealth_agent.log")

# Verbose step-by-step trace ([SEC]/[TOOL]/[SVC] lines showing exactly which
# function runs where). Off by default (clean output); set WEALTH_DEBUG_TRACE=true
# to follow the flow live — handy for demos and understanding the code.
DEBUG_TRACE = env_bool("WEALTH_DEBUG_TRACE", False)


def trace(message: str) -> None:
    """Print a step-by-step trace line, but ONLY when WEALTH_DEBUG_TRACE is on.

    Lets us follow exactly which function runs where without leaving raw prints in
    the code: silent by default, opt-in for demos and debugging.
    """
    if DEBUG_TRACE:
        print(message)
