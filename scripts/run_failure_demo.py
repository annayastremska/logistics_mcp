"""Break the browser server on purpose, and check the run still decides.

The graded requirement is not that nothing fails -- it is that a failure is
distinguishable from an empty answer, and that the run says which step failed
instead of quietly producing a confident recommendation with a hole in it.

So this points the browser at an unresolvable host with no fallback URLs, and
passes only if all three hold: the navigate reports as an error, nothing else
errors, and a recommendation still comes out with the failed check named in it.

    python scripts/run_failure_demo.py

Companion to run_e2e.py, which checks the same run when nothing is broken.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.sourcing_agent import run_sourcing_query  # noqa: E402

QUESTION = (
    "Which countries should Ukraine source fresh grapes (HS 080610) from for the "
    "2025 season? Check the customs turnover page first, then use the sourcing "
    "tools on 2024 data for a 120 tonne shipment, and give a ranked recommendation."
)

# The step that is supposed to fail. Anything else failing is a real defect.
BROKEN_STEP = "playwright/browser_navigate"


async def main() -> int:
    errors: list[str] = []
    calls: list[str] = []
    servers: dict[str, int] = {}
    final: str | None = None

    async for event in run_sourcing_query(QUESTION, break_playwright=True):
        label = f"{event.server or '-'}/{event.tool or '-'}"
        if event.kind == "tool_call":
            calls.append(label)
            print(f"[call ] {label}", flush=True)
        elif event.kind == "tool_result":
            bad = bool(event.data.get("is_error"))
            print(f"[{'ERR ' if bad else 'ok  '}] {label}", flush=True)
            if bad:
                errors.append(label)
        elif event.kind == "status" and event.data.get("servers"):
            servers = {k: len(v) for k, v in event.data["servers"].items()}
            print(f"[stat ] {servers}", flush=True)
        elif event.kind == "error":
            print(f"[FAIL ] {event.text}", flush=True)
            errors.append(event.text or "error")
        elif event.kind == "done":
            final = event.text

    print(f"\nservers attached: {servers}", flush=True)
    print(f"tool calls ({len(calls)})", flush=True)
    print(f"errors: {errors or 'none'}", flush=True)
    if final:
        print(f"\n===== ANSWER =====\n{final}", flush=True)

    problems = []
    collateral = sorted(set(errors) - {BROKEN_STEP})
    if collateral:
        problems.append(f"steps failed that were not meant to: {collateral}")
    if BROKEN_STEP not in errors:
        problems.append(f"{BROKEN_STEP} did not report as an error, so the failure was swallowed")
    if not final:
        problems.append("no recommendation was produced")

    print("\n===== VERDICT =====", flush=True)
    for line in problems:
        print(f"FAIL  {line}", flush=True)
    if not problems:
        print(
            "PASS  the browser step failed, reported itself as a failure, and the run still "
            "reached a decision",
            flush=True,
        )
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
