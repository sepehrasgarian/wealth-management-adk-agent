"""Tests for the empty-response retry in RetryingGemini (no real API calls).

We monkeypatch the parent Gemini.generate_content_async so the model "returns"
empty or content responses on demand, then assert the retry behaviour.
"""

from __future__ import annotations

import pytest
from google.genai import types
from google.adk.models.google_llm import Gemini
from google.adk.models.llm_response import LlmResponse

from wealth_agent.model import RetryingGemini


def _empty():
    """An empty model response (no parts) — the failure case we retry on."""
    return LlmResponse(content=types.Content(role="model", parts=[]))


def _content(text):
    """A normal model response carrying text."""
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text)]))


async def _collect(model):
    return [r async for r in model.generate_content_async(llm_request=None)]


def test_http_retry_is_configured():
    """The built model has HTTP retry (for 429s / 503s / timeouts) wired up.

    The actual 429 retry is performed inside the genai client (well-tested by
    Google); here we assert our configuration is applied.
    """
    from wealth_agent import config, model as model_module

    built = model_module.build_model()
    assert built.retry_options is not None
    assert built.retry_options.attempts == config.MODEL_HTTP_RETRY_ATTEMPTS


@pytest.mark.asyncio
async def test_retries_empty_then_succeeds(monkeypatch):
    calls = {"n": 0}

    async def fake(self, llm_request, stream=False):
        calls["n"] += 1
        yield _empty() if calls["n"] == 1 else _content("hello")

    monkeypatch.setattr(Gemini, "generate_content_async", fake)
    out = await _collect(RetryingGemini(model="gemini-2.5-flash"))

    assert calls["n"] == 2  # retried once after the empty response
    assert out[-1].content.parts[0].text == "hello"


@pytest.mark.asyncio
async def test_content_on_first_try_does_not_retry(monkeypatch):
    calls = {"n": 0}

    async def fake(self, llm_request, stream=False):
        calls["n"] += 1
        yield _content("hi")

    monkeypatch.setattr(Gemini, "generate_content_async", fake)
    out = await _collect(RetryingGemini(model="gemini-2.5-flash"))

    assert calls["n"] == 1  # no retry needed
    assert out[-1].content.parts[0].text == "hi"


@pytest.mark.asyncio
async def test_all_empty_yields_nothing_after_retries(monkeypatch):
    calls = {"n": 0}

    async def fake(self, llm_request, stream=False):
        calls["n"] += 1
        yield _empty()

    monkeypatch.setattr(Gemini, "generate_content_async", fake)
    out = await _collect(RetryingGemini(model="gemini-2.5-flash"))

    # Tried the initial attempt plus the configured retries, all empty.
    from wealth_agent import config
    assert calls["n"] == config.MODEL_EMPTY_RESPONSE_RETRIES + 1
    assert out == []
