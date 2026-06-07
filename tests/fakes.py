"""Lightweight fakes that stand in for ADK objects in the deterministic tests.

The unit tests do NOT call the LLM. They exercise our own code directly, so they
need only a small stand-in for ADK's ToolContext that implements the few
attributes our code actually touches.
"""

from __future__ import annotations


class FakeToolConfirmation:
    """Stands in for ADK's ToolConfirmation (only the `confirmed` flag is used)."""

    def __init__(self, confirmed: bool):
        self.confirmed = confirmed


class FakeToolContext:
    """A minimal stand-in for ADK's ToolContext.

    Implements just what our tools read/write: session `state`, the optional
    `tool_confirmation`, and `request_confirmation` (which records the hint so a
    test can assert on it).
    """

    def __init__(self, state: dict | None = None):
        self.state = dict(state or {"user_id": "user_123"})
        self.invocation_id = "test-invocation"
        self.tool_confirmation = None
        self.requested_hint = None

    def request_confirmation(self, hint: str | None = None, payload=None) -> None:
        self.requested_hint = hint


class FakeTool:
    """Stands in for an ADK tool object; the gate only needs `.name`."""

    def __init__(self, name: str):
        self.name = name
