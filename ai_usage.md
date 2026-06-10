# How I used AI in this project

**Short version:** I designed the system and made every architectural and security
decision myself. I used an AI coding assistant (Claude) as a tool — to implement
specific functions to my spec, to write tests, and to confirm exact framework
details — and I reviewed and verified everything it produced by running it.

I've tried to be specific below rather than vague, since *how* AI is used (and how
its output is checked) matters more than *whether* it was used.

---

## What I designed and decided myself

These were my decisions, made before or independently of any code generation:

- **The architecture** — a layered design (view → agent → **service** → data) with
  security isolated as a cross-cutting **gate at the agent↔service boundary**.
- **The security model** — "the LLM proposes, code disposes": verification enforced
  in a deterministic `before_tool_callback`, never trusted to the model. Two
  factors: an identity **state machine** plus a **human-in-the-loop** confirmation.
- **Key trade-offs** — a service layer so tools stay thin and logic is
  unit-testable; one file per layer for readability; plain dicts over custom
  Pydantic for ADK tool I/O; a single `config.py` for every tunable; multi-question
  verification; where *not* to use AI (an LLM must never make the security
  decision).
- **The evaluation strategy** — trajectory-based evals for the security contract,
  plus adversarial cases for prompt injection.

The README and the observability document reflect this design; they're mine.

## Where I used AI (and how)

**1. Implementing specific functions to my design.**
Once I'd decided *what* a component should do, I used AI to draft the
implementation, then edited it for clarity and correctness. Examples:

- The verification **state machine** (`security.py`) — I specified the states
  (`UNVERIFIED → CHALLENGED → VERIFIED → LOCKED`), the TTL, single-use, and lockout
  rules; AI drafted the transitions, which I then refactored (e.g. moving the states
  to a `str` Enum and tightening the multi-question logic).
- The **transfer flow** (`services.py` / `tools.py`) — I specified up-front
  validation, the debit/credit, and three confirmation paths; AI drafted them and I
  reviewed the SQL for parameterization/injection safety.
- The **PII redaction** and **retry-on-empty-response** helpers — I described the
  behaviour; AI produced a first cut that I trimmed.

**2. Writing the tests.**
I described the cases I wanted covered; AI generated the pytest scaffolding and I
checked the assertions and added edge cases. This is where AI saved the most time —
the deterministic suite (state machine, gate, services, tools, retry, redaction)
reached **97% coverage** on application logic, plus the trajectory evalsets and a
custom LLM-as-judge.

**3. Confirming exact framework details (instead of guessing).**
ADK is new enough that I verified the real API rather than relying on memory:

> *"Inspect the installed ADK: `Agent` params, `ToolContext`, `AgentEvaluator`, the
> `EvalSet`/`EvalCase` schema, and the `before_tool_callback` signature."*

This kept the code aligned with ADK 2.2 instead of a plausible-but-wrong guess.

## Problem-solving / iterations (debugged by inspecting, not guessing)

- **HITL vs. trajectory evals** — the transfer tool pauses for confirmation, which a
  non-interactive eval can't satisfy. I made confirmation configurable so evals run
  deterministically, and covered the confirmation path with unit tests instead.
- **`adk eval` used default criteria** (`response_match 0.8`) and failed on free-form
  wording → I passed a trajectory-only `--config_file_path`.
- **ADK's LLM judge needs Vertex AI / ADC**, not just an API key → I wrote a small
  custom judge that runs on the Gemini API directly.
- **OpenTelemetry version conflict** with the OTLP exporter → pinned
  `opentelemetry-*==1.41.1`.
- **Empty-200 model responses** ("no reply") — diagnosed from the session trace →
  added a regenerate-on-empty retry wrapper.

## How I verified AI's output

Nothing was trusted because it "looked right" — it was checked by running it:

- the state machine and gate via deterministic unit tests (no API key);
- the full tool flow against a fake `ToolContext`;
- the live agent end-to-end through Gemini (text and voice);
- the evalsets via `adk eval` and `pytest` (trajectory match = 1.0);
- coverage measured at 97% on application logic.

## Summary

I drove the design and the security model; AI accelerated the parts that are easy
to get subtly wrong or slow to type — implementing functions to spec, generating
tests, and pinning down exact framework behaviour — and I validated every piece
empirically. The judgment about *what to build and what to trust* was mine.
