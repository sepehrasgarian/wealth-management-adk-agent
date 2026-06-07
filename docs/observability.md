# Observability & Monitoring Design

This document describes how the wealth management assistant would be monitored in
production. A thin slice is already wired in code (`wealth_agent/observability.py`
exports OpenTelemetry traces; `security.py` emits structured security events), but
the design below covers the full production picture.

## Approach: the three pillars

We organise monitoring around **logs**, **metrics**, and **traces**, and map each
required signal to where it is captured in the agent. ADK gives us the capture
points for free:

- **Callbacks** — `before_tool_callback` (our security gate), plus
  `after_tool_callback` / model callbacks, are the instrumentation hooks.
- **OpenTelemetry spans** — ADK already emits spans for the agent run, every tool
  call, and every LLM call (with token usage). We export them via OTLP.
- **Backend** — traces, latency, token usage and cost go to **Langfuse**
  (OTLP-native). Metrics/alerts go to a metrics backend (e.g. Cloud
  Monitoring / Grafana). In a regulated environment Langfuse would be
  **self-hosted** so trace data never leaves our boundary.

A correlation id (`session_id` / `invocation_id`) is attached to every log,
metric, and span so one user interaction can be reconstructed end to end.

---

## 1. Security monitoring

The most important category for a financial assistant. Each event below is
emitted as a structured audit log line **and** attached to the active trace
(see `security.log_security_event`).

| Signal | Where it is captured | Alerting |
|---|---|---|
| **Failed verification attempts** | `verify_security_answer` → `verification_failed` event | ≥ N failures / user / 5 min → alert + auto-lockout |
| **Account lockouts** | state machine reaches `LOCKED` → `verification_locked` event | Any lockout → security dashboard; spikes → page |
| **Unauthorized transfer attempts** | the security gate blocks a sensitive tool → `unauthorized_transfer_attempt` event | Any block is audited; a spike indicates an attack/bug |
| **Declined confirmations** | user rejects the HITL prompt → `transfer_declined_by_user` event | Trend watched (possible account takeover signal) |
| **State inconsistencies** | illegal state transition (e.g. `VERIFIED` without a prior `CHALLENGED`) | Any occurrence → page (indicates a logic bug or tampering) |

**Audit log fields:** `event`, `user_id`, `session_id`/`invocation_id`,
`outcome`, `timestamp`. The log is append-only and **never** contains the
security answer or full balances.

---

## 2. Agent metrics

| Signal | Where it is captured | Notes |
|---|---|---|
| **Tool execution failures** | `on_tool_error_callback` + non-`success` tool results | Error rate tracked per tool; alert on sustained spikes |
| **Loop detection** | count tool calls per invocation; flag repeated identical calls | Agent stuck in a cycle → abort the run + alert |
| **Latency — Time-to-First-Token** | `before_model_callback` → first streamed chunk | Track p50 / p95 / p99 |
| **Multi-step workflow latency** | duration of the root OpenTelemetry span (request → final response) | p95 of the full verify → confirm → transfer flow |

---

## 3. LLM metrics

| Signal | Where it is captured | Notes |
|---|---|---|
| **Token usage per session** | LLM span `usage_metadata` (prompt + candidate tokens), summed by `session_id` | Surfaces runaway prompts / context bloat |
| **Cost tracking (input vs output)** | tokens × per-token rates, **billed separately for input and output** | Output is the expensive side; track them apart |

**Voice note:** the optional voice mode uses a native-audio Live model where
**audio output (~$12/1M) is ~6× audio input and ~5× text output**. Audio and text
token streams must be costed **separately** so a voice session's cost is
attributed correctly.

---

## Dashboards & alerting

- **Security dashboard** — failed verifications, lockouts, blocked transfers,
  declined confirmations, over time and by user.
- **Agent health dashboard** — tool error rates, TTFT, p95 workflow latency,
  loop-detection events.
- **Cost dashboard** — tokens and cost per session, split input vs output
  (and audio vs text).
- **Example alert thresholds:** "≥ 3 failed verifications / user / 5 min →
  alert + lockout"; "p95 workflow latency > 5 s for 5 min → page"; "any illegal
  state transition → page".

## What we deliberately never log

Security answers, full account balances, and any PII. Spans and logs are scrubbed
of these before export. This is enforced by emitting only an explicit allow-list
of fields in `log_security_event`.

## Production hardening (beyond the prototype)

- **Self-host Langfuse** so trace data stays inside our security boundary.
- **Out-of-band confirmation** — escalate the HITL approval to a push
  notification on a trusted device, so the approval channel is independent of the
  chat session (defends against session compromise).
- **Hash the security answer** (salted) and compare hashes; never store or log
  plain text.
- Persist the audit log to a tamper-evident, append-only store for compliance.
