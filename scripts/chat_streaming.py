"""Streaming chat demo — shows the agent's response token-by-token (low TTFT).

Runs the agent with streaming enabled (RunConfig(streaming_mode=SSE)) and prints
each partial chunk as it arrives, so the response starts appearing almost
immediately instead of after a long pause. It also prints the time-to-first-token
(TTFT) — the key "perceived latency" metric for real-time / voice agents.

Streaming does NOT change cost (you pay per token either way); it only improves
when the user starts receiving the answer.

Run:
    python scripts/chat_streaming.py                       # default prompt
    python scripts/chat_streaming.py "What is my balance?" # custom prompt
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

# Make the project root importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google.genai import types
from google.adk.runners import InMemoryRunner
from google.adk.agents.run_config import RunConfig, StreamingMode

from wealth_agent import database
from wealth_agent.agent import root_agent


async def stream_turn(runner: InMemoryRunner, session_id: str, text: str) -> None:
    """Send one message and print the response as it streams in."""
    message = types.Content(role="user", parts=[types.Part(text=text)])
    start = time.perf_counter()
    ttft = None
    printed_partial = False

    print(f"\nYou:   {text}\nAgent: ", end="", flush=True)
    async for event in runner.run_async(
        user_id="user_123",
        session_id=session_id,
        new_message=message,
        run_config=RunConfig(streaming_mode=StreamingMode.SSE),
    ):
        for part in (event.content.parts if event.content else []):
            if not part.text:
                continue
            if event.partial:
                # Incremental chunk — print it as it arrives.
                if ttft is None:
                    ttft = time.perf_counter() - start
                print(part.text, end="", flush=True)
                printed_partial = True
            elif not printed_partial:
                # Fallback: no streaming happened, print the whole answer once.
                print(part.text, end="", flush=True)

    total = time.perf_counter() - start
    ttft_ms = f"{ttft * 1000:.0f}ms" if ttft else "n/a"
    print(f"\n  [TTFT: {ttft_ms} | total: {total:.2f}s]")


async def main() -> None:
    database.init_db(reset=True)
    runner = InMemoryRunner(agent=root_agent, app_name="wealth_agent")
    await runner.session_service.create_session(
        app_name="wealth_agent", user_id="user_123", session_id="stream",
        state={"user_id": "user_123"},
    )
    prompt = " ".join(sys.argv[1:]) or "What is my portfolio balance?"
    await stream_turn(runner, "stream", prompt)


if __name__ == "__main__":
    asyncio.run(main())
