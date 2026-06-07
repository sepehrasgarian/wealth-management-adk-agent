# How AI was used to build this project

I used an AI coding assistant (Claude) throughout this assignment — not to generate
a finished answer in one shot, but as a pair-programming partner for research,
design, implementation, and debugging. The goal was to make deliberate engineering
decisions quickly and verify everything against the real ADK API rather than
relying on memory. Below is an honest summary of how it was used.

## 1. Research before building

I had the assistant confirm the actual ADK 2.2.0 API surface instead of guessing,
and research best practices:

- *"Inspect the installed ADK: Agent params, ToolContext, AgentEvaluator, the
  EvalSet/EvalCase schema, and the before_tool_callback signature."*
- *"Research Google ADK project-structure best practices and HITL authorization
  patterns for financial agents."*

This surfaced the Zero-Trust principle ("don't trust the LLM for authorization")
and the human-in-the-loop pattern for high-impact actions, which shaped the design.

## 2. Design decisions (discussed, not dictated)

I worked through the architecture interactively before writing code:

- Layering: **view → agent → service → data**, with security as a cross-cutting
  gate at the agent↔service boundary.
- Whether to use a service layer (yes — keeps tools thin and logic unit-testable).
- Whether to split into folders or files (kept one file per layer for readability).
- Two-factor security: an identity **state machine** + a **HITL confirmation**.
- Where *not* to use AI: an LLM judge must never make the security decision.

Example prompt: *"Should the service layer sit above or below the agent layer, and
why?"* — which led to the "agent orchestrates the flow, code enforces the
decision" framing used in the README.

## 3. Implementation

Each module was generated and then reviewed for clarity (a stated requirement was
"code that is easy to understand"). I had the assistant keep all tunable values in
a single `config.py`, write thorough docstrings (ADK uses them as tool
descriptions), and verify each layer with a quick standalone run before moving on.

## 4. Problem-solving / iterations

Several real problems came up and were solved by inspecting behaviour, not
guessing:

- **HITL vs. trajectory evals.** The transfer tool pauses for confirmation, which
  a non-interactive eval can't satisfy. Solution: make confirmation configurable
  so trajectory evals run deterministically, and cover the confirmation flow with
  unit tests instead.
- **`adk eval` config not applied.** The CLI used default criteria
  (`response_match_score: 0.8`) and failed on free-form wording. Solution: pass
  `--config_file_path` with a trajectory-only config.
- **LLM-as-judge needed Vertex AI.** ADK's `response_evaluation_score` requires
  GCP credentials, not just an API key. Solution: replace it with a small custom
  LLM judge that runs on the Gemini API key directly.
- **OpenTelemetry version conflict.** The OTLP exporter pulled a version newer than
  ADK allows. Solution: pin `opentelemetry-*==1.41.1`.
- **Verification dead-end.** Testing in the UI showed a single wrong answer ended
  the flow. Solution: let the user retry until lockout, and report attempts
  remaining.

## 5. Verification

Everything claimed was checked by running it: the state machine transitions, the
full tool flow with a fake context, the live agent through Gemini, the evalsets via
`adk eval`, and the unit-test suite with coverage (97% on application logic).

## Summary

AI accelerated the parts that are easy to get subtly wrong — confirming the exact
framework API, surfacing security best practices, and debugging integration
issues — while the architecture and security decisions were made deliberately and
verified empirically at each step.
