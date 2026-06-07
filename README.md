# Wealth Management Assistant (Google ADK + Gemini)

A prototype digital brokerage assistant built with the **Google Agent Development
Kit (ADK)** and **Gemini**. It answers general portfolio questions freely, but
enforces a strict, **state-aware security verification flow** before any sensitive
action (a transfer).

The guiding principle is **"the LLM proposes, the code disposes"**: the agent
decides *what* to do, but authorization is enforced in deterministic code that the
model cannot talk its way around.

---

## Key features

- **Two-factor protection on transfers**
  1. **Identity** — a verification state machine (`UNVERIFIED → CHALLENGED →
     VERIFIED → LOCKED`) with a time-to-live, single-use verification, and
     lockout after repeated failures.
  2. **Authorization** — a human-in-the-loop (HITL) confirmation of the exact
     transfer before any money moves.
- **Code-level security gate** — a `before_tool_callback` blocks sensitive tools
  unless the session is verified, independent of what the model says.
- **Clean layered architecture** — agent → tools → services → data, with security
  as a cross-cutting gate at the agent↔service boundary.
- **Production-grade observability design** — OpenTelemetry → Langfuse wiring plus
  a full monitoring design ([docs/observability.md](docs/observability.md)).
- **Automated evaluation** — ADK trajectory evalsets (run via `adk eval` *and*
  `pytest`), adversarial evals, an LLM-as-judge bonus, and deterministic unit
  tests (**97% coverage** on application logic).
- **Voice (bonus)** — runs over a Gemini native-audio Live model via `adk web`.

---

## Architecture

```
  USER (text or voice)
        │
   adk web / adk run                       ← View layer (built into ADK, no code)
        │
   agent.py  (Gemini LlmAgent)             ← Agent layer: decides what to do
        │  registers the security gate as before_tool_callback
        ▼
   tools.py  (thin LLM-facing adapters)    ← Agent layer
        │            │
        │     🚧 security gate  ───────────  ← Security (cross-cutting), enforced
        │            │                          at the agent↔service boundary
        ▼            ▼
   services.py                             ← Service layer: real business logic
        │                                      (LLM-agnostic, unit-testable)
        ▼
   database.py → SQLite (users, accounts)  ← Data layer

   config.py (settings, read by all)   ·   observability.py (traces, wraps all)
```

### Security flow (a transfer)

```
  user: "transfer $500 checking → savings"
     │
     ├─ get_security_question()      UNVERIFIED → CHALLENGED ; ask the question
     │
     ├─ user answers
     │     ├─ correct → record_answer()  CHALLENGED → VERIFIED
     │     └─ wrong   → stay CHALLENGED, attempts++  (3 wrong → LOCKED)
     │
     ├─ transfer_funds()  ── 🚧 gate: is_verified? ── no ─→ BLOCKED + audit event
     │                                              └ yes ─→ continue
     │     └─ HITL: "Confirm transfer of $500?"  ── user approves ──┐
     │                                                              ▼
     └─ money moves (services.execute_transfer) → consume()  VERIFIED → UNVERIFIED
                                                  (single-use: re-verify next time)
```

---

## Setup

Requires **Python 3.10+** (developed on 3.12).

```bash
# 1. Create a virtual environment and install dependencies
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Add your Gemini API key
cp wealth_agent/.env.example wealth_agent/.env
#   then edit wealth_agent/.env and set GOOGLE_API_KEY=...
#   (free key from https://aistudio.google.com/app/apikey)
```

The SQLite mock database is created and seeded automatically on first run with one
demo user:

| user_id | security question | answer | checking | savings |
|---|---|---|---|---|
| `user_123` | "What is the name of your first pet?" | `Rex` | 2000.00 | 5000.00 |

---

## Running the agent

```bash
adk web                 # browser UI at http://127.0.0.1:8000 — pick "wealth_agent"
# or
adk run wealth_agent    # chat in the terminal
```

Try in the chat:
- `What is my portfolio balance?` → answered directly (no verification).
- `Transfer $500 from checking to savings` → asks your security question.
  - Answer `Rex` → a **Confirm / Reject** button appears (HITL) → approve → done.
  - Answer wrong → "incorrect, N attempts remaining" → 3 wrong → **locked**.

The `adk web` inspector shows the tool calls and the live session state
(`verification: VERIFIED`), which makes the security flow visible.

---

## Testing

```bash
# Fast deterministic unit tests (no API key needed) + coverage
pytest tests/test_security.py tests/test_tools.py tests/test_services.py \
       tests/test_config.py --cov=wealth_agent

# Trajectory evals via pytest (needs a Gemini API key — makes real LLM calls)
pytest tests/test_eval.py

# LLM-as-judge bonus tests (needs a key)
pytest tests/test_llm_judge.py

# Or run the evalsets directly with the ADK CLI:
WEALTH_REQUIRE_TRANSFER_CONFIRMATION=false \
  adk eval wealth_agent eval/blocked_transfer.evalset.json    --config_file_path eval/test_config.json
WEALTH_REQUIRE_TRANSFER_CONFIRMATION=false \
  adk eval wealth_agent eval/successful_transfer.evalset.json --config_file_path eval/test_config.json
WEALTH_REQUIRE_TRANSFER_CONFIRMATION=false \
  adk eval wealth_agent eval/adversarial.evalset.json        --config_file_path eval/test_config.json
```

### Evaluation scenarios

| Evalset | Scenario | Expected trajectory |
|---|---|---|
| `blocked_transfer` | Unauthenticated (wrong answer) | `get_security_question` → `verify_security_answer` (no transfer) |
| `successful_transfer` | Authenticated (correct answer) | `get_security_question` → `verify_security_answer` → `transfer_funds` |
| `adversarial` | Prompt-injection / urgency pressure | `get_security_question` only — verification is never skipped |

> **Why confirmation is disabled during evals:** a trajectory eval cannot click
> "confirm", so the HITL pause is turned off (`WEALTH_REQUIRE_TRANSFER_CONFIRMATION=false`)
> to keep the trajectory deterministic. The confirmation flow itself is fully
> covered by the deterministic unit tests in `tests/test_tools.py`.

---

## Observability

ADK emits OpenTelemetry spans for the agent, tools, and LLM calls. To export them
(e.g. to Langfuse), set in `wealth_agent/.env`:

```bash
WEALTH_TRACING_ENABLED=true
OTEL_EXPORTER_OTLP_ENDPOINT=https://cloud.langfuse.com/api/public/otel
OTEL_EXPORTER_OTLP_HEADERS=Authorization=Basic <base64(public_key:secret_key)>
```

Security audit events (failed verification, lockout, blocked transfer) are emitted
as structured logs and attached to the trace. Full design:
[docs/observability.md](docs/observability.md).

---

## Sensitive data handling

A financial assistant must be careful about what reaches the LLM, the model
provider, and the traces. This project applies layered data protection:

1. **Data minimization (the primary control).** Secrets should be collected and
   verified **out of band** so they never enter the LLM conversation at all — the
   agent decides *that* verification is needed, but a deterministic component
   handles the actual secret and returns only `verified: true/false`.
   *In this prototype the security answer is typed into the chat (so it does
   reach the model); the out-of-band flow is the documented production design.*
2. **PII redaction guardrail.** `redaction.py` (wired as `before_model_callback`)
   masks card numbers, SSNs, and long account/PIN digit runs in user input
   **before** it reaches the model or the trace — catching accidental PII.
3. **Never log secrets.** Audit events use an allow-list of fields; the security
   answer and full balances are never logged (see `security.log_security_event`).
4. **Hash at rest.** In production the security answer would be a salted hash, not
   plain text (a flagged mock simplification).

## Voice (bonus)

The same agent runs over voice using a Gemini native-audio Live model — no code
changes, just a model swap (ADK's `adk web` shows a mic when the model supports
the Live API). Use **conversational** confirmation for voice, because ADK's
native confirmation button is not supported in live/voice mode:

```bash
WEALTH_MODEL=gemini-2.5-flash-native-audio-latest \
WEALTH_CONFIRMATION_MODE=conversational \
adk web
```

**Confirmation modes** (`WEALTH_CONFIRMATION_MODE`):
- `button` (default) — native ADK Confirm/Reject button; best in text / `adk web`.
- `conversational` — the agent asks you to say "yes"/"no"; works in **voice and
  text** (the agent calls `confirm_transfer` with your answer).

**Voice caveats:** ADK live streaming is preview — a bidirectional stream can't be
restarted (refresh to start a new one). And spoken knowledge-based answers are a
weaker channel (overhearing / recording), so in production we'd prefer voice
biometrics or an out-of-band approval rather than reading a security answer aloud.

---

## Configuration

All tunable values live in `wealth_agent/config.py` and are overridable via
environment variables (`.env`):

| Variable | Default | Meaning |
|---|---|---|
| `WEALTH_MODEL` | `gemini-2.5-flash` | The model the agent uses |
| `WEALTH_VERIFICATION_TTL_SECONDS` | `120` | How long a verification stays valid |
| `WEALTH_MAX_FAILED_ATTEMPTS` | `3` | Wrong answers before lockout |
| `WEALTH_REQUIRE_TRANSFER_CONFIRMATION` | `true` | HITL confirmation on transfers |
| `WEALTH_CONFIRMATION_MODE` | `button` | `button` (text) or `conversational` (voice) |
| `WEALTH_TRACING_ENABLED` | `false` | Export OpenTelemetry traces |

---

## Project structure

```
wealth_agent/
  agent.py          Gemini LlmAgent + instruction + registers the security gate
  tools.py          thin LLM-facing tool adapters (+ HITL confirmation)
  services.py       business logic: balances, security Q/A, transfers
  security.py       verification state machine + policy gate + audit events
  config.py         single source of truth for all settings
  database.py       SQLite mock (users, accounts)
  observability.py  OpenTelemetry -> Langfuse wiring + logging
eval/               trajectory evalsets + adversarial + test_config
tests/              deterministic unit tests + pytest eval wrapper + LLM-judge
docs/observability.md   monitoring & observability design
ai_usage.md         how AI tools were used to build this
```

---

## Design notes

- **Single agent, not multi-agent.** This is one tight security flow, not a
  decomposable multi-specialist task, so a single `LlmAgent` is the right choice.
- **ADK can wrap LangChain/CrewAI tools** via adapters, but native ADK function
  tools were used since the tools are simple DB operations — no extra dependency.
- **Mock simplifications** (flagged for production): the security answer is stored
  in plain text (would be a salted hash), and the database is local SQLite.
