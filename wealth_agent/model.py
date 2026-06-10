"""A Gemini model that retries when the agent fails to produce a response.

There are two distinct "the agent didn't respond" failures, handled separately:

1. **Transient HTTP errors** (rate limits, 503s, timeouts). These are retried by
   the genai client via `retry_options` (HttpRetryOptions) — see build_model().

2. **Empty responses.** Occasionally Gemini returns an empty candidate — no text,
   no tool call, finish_reason STOP, zero output tokens. That is NOT an HTTP
   error (the call "succeeds"), so the HTTP retry above never fires. We detect a
   turn that produced no content and regenerate it.

Streaming is preserved: responses that carry content are passed straight through
as they arrive; we only retry when an entire turn yields nothing. This wraps the
non-live (run_async) path; voice (run_live) uses a different code path.
"""

from __future__ import annotations

import logging
from typing import AsyncGenerator

from google.genai import types
from google.adk.models.google_llm import Gemini
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse

from . import config

logger = logging.getLogger("wealth_agent.model")


class RetryingGemini(Gemini):
    """Gemini that regenerates a turn when it produces no content at all."""

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        attempts = config.MODEL_EMPTY_RESPONSE_RETRIES + 1

        for attempt in range(1, attempts + 1):
            produced_content = False

            async for response in super().generate_content_async(llm_request, stream=stream):
                if response.content and response.content.parts:
                    # Real content (text or a tool call) — pass it through.
                    produced_content = True
                    yield response
                # A response with no parts is the empty-response case; drop it and
                # let the loop below decide whether to regenerate.

            if produced_content:
                return  # got a real answer this turn

            if attempt < attempts:
                logger.warning(
                    "Model returned an empty response; regenerating (attempt %d of %d).",
                    attempt,
                    config.MODEL_EMPTY_RESPONSE_RETRIES,
                )
        # Every attempt was empty — yield nothing; the caller handles it gracefully.


def build_model(model_name: str | None = None):
    """Build a Gemini model with HTTP + empty-response retries.

    Defaults to the configured text model (config.MODEL). Pass config.LIVE_MODEL
    for the voice agent.
    """
    return RetryingGemini(
        model=model_name or config.MODEL,
        retry_options=types.HttpRetryOptions(attempts=config.MODEL_HTTP_RETRY_ATTEMPTS),
    )
