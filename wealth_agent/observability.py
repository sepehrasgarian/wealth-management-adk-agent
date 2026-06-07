"""Observability — OpenTelemetry trace export (e.g. to Langfuse) and logging.

ADK already creates OpenTelemetry spans for agent runs, tool calls, and LLM
calls (with token usage). This module wires those spans to an OTLP backend such
as Langfuse, and sets up structured logging. It is fully opt-in: with tracing
disabled (the default) the app runs with no external dependencies.

To enable tracing to Langfuse:
  1. `pip install -r requirements.txt` (includes the OTLP exporter).
  2. In wealth_agent/.env set:
        WEALTH_TRACING_ENABLED=true
        OTEL_EXPORTER_OTLP_ENDPOINT=https://cloud.langfuse.com/api/public/otel
        OTEL_EXPORTER_OTLP_HEADERS=Authorization=Basic <base64(public_key:secret_key)>
  3. Import the agent / start `adk web` as usual — spans then flow to Langfuse.

Langfuse then shows traces, latency, token usage and cost (input vs output), and
the security audit events we attach to spans in security.py.
"""

from __future__ import annotations

import logging

from . import config

logger = logging.getLogger("wealth_agent")

# Guard so we only configure tracing once, even if imported multiple times.
_configured = False


def setup_logging(level: int = logging.INFO) -> None:
    """Configure structured application logging (one line per event)."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def setup_observability() -> None:
    """Set up logging and (if enabled) export OpenTelemetry traces via OTLP.

    Safe to call more than once and safe to call when tracing is disabled — in
    that case it just configures logging and returns.
    """
    global _configured
    if _configured:
        return
    _configured = True

    setup_logging()

    if not config.TRACING_ENABLED:
        logger.info("Tracing disabled (set WEALTH_TRACING_ENABLED=true to export traces).")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        # The OTLP exporter reads OTEL_EXPORTER_OTLP_ENDPOINT and
        # OTEL_EXPORTER_OTLP_HEADERS from the environment (set in .env).
        provider = TracerProvider(
            resource=Resource.create({"service.name": config.SERVICE_NAME})
        )
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(provider)
        logger.info("Tracing enabled -> %s", config.OTLP_ENDPOINT or "(OTLP default endpoint)")
    except Exception as error:  # never let observability break the app
        logger.warning("Tracing setup failed, continuing without it: %s", error)
