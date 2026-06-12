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


# Tool argument names that must never be logged (they carry secrets).
_SENSITIVE_ARG_NAMES = {"answer"}


def log_tool_activity(tool, args, tool_context, tool_response) -> None:
    """ADK `after_tool_callback`: record every tool call + result as one
    structured log line, and attach it to the current trace span.

    This works in BOTH text and voice sessions (callbacks fire either way), so a
    voice conversation becomes observable in plain text — you can see exactly
    which tools ran and what they returned. Sensitive args (the security answer)
    are masked. Returns None so the tool's real response is used unchanged.
    """
    safe_args = {
        key: ("***" if key in _SENSITIVE_ARG_NAMES else value)
        for key, value in (args or {}).items()
    }
    status = tool_response.get("status") if isinstance(tool_response, dict) else None
    payload = {
        "tool": getattr(tool, "name", str(tool)),
        "args": safe_args,
        "status": status,
        "invocation_id": getattr(tool_context, "invocation_id", None),
    }
    logger.info("tool_activity %s", payload)

    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        if span is not None and span.is_recording():
            span.add_event(
                f"tool.{payload['tool']}",
                attributes={"status": status or "", "args": str(safe_args)},
            )
            # Classify the trace in Langfuse: group all turns of a conversation
            # under one session, and tag the authenticated user so traces can be
            # filtered per user (user_123 vs user_456). Langfuse reads these
            # specific span attributes.
            session = getattr(tool_context, "session", None)
            session_id = getattr(session, "id", None)
            user_id = (getattr(tool_context, "state", None) or {}).get("user_id")
            if session_id:
                span.set_attribute("langfuse.session.id", str(session_id))
            if user_id:
                span.set_attribute("langfuse.user.id", str(user_id))
    except Exception:  # telemetry must never break the request path
        pass
    return None


def setup_logging(level: int = logging.INFO) -> None:
    """Configure structured logging — to the console AND an append-only log file.

    The file (config.LOG_FILE) gives a durable trail of tool activity and security
    audit events; the console handler keeps them visible while developing.
    """
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(config.LOG_FILE),
        ],
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
