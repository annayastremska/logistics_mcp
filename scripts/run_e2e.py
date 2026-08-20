"""Run the agent end to end and write a full trace to disk.

This is the check the demo rests on: one question, both MCP servers attached,
every tool call and result recorded so the run can be inspected afterwards
instead of being taken on trust.

    python scripts/run_e2e.py "which countries should Ukraine source grapes from"
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.sourcing_agent import run_sourcing_query  # noqa: E402

# The five tools the sourcing flow is supposed to exercise. Named here so a run
# that quietly skips one is reported as a failure rather than as a pass.
EXPECTED_CUSTOM_CALLS = [
    "validate_sourcing_brief",
    "get_import_flows",
    "assess_supply_concentration_risk",
    "estimate_landed_cost",
    "rank_sourcing_countries",
]

DEFAULT_QUESTION = (
    "Which countries should Ukraine source fresh grapes (HS 080610) from for the "
    "2025 season? Check the customs turnover page first, then use the sourcing "
    "tools on 2024 data for a 120 tonne shipment, and give a ranked recommendation."
)


async def main() -> int:
    question = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_QUESTION
    out = Path("scripts/last_e2e_trace.jsonl")
    calls: list[str] = []
    errors: list[str] = []
    final: str | None = None
    # Which servers the session actually attached. A run where the custom server
    # failed to start still produces a fluent answer -- the model just reports it
    # has no tools -- so a run only passes if both servers are genuinely connected.
    attached: dict[str, list[str]] = {}

    with out.open("w", encoding="utf-8") as fh:
        async for event in run_sourcing_query(question):
            fh.write(json.dumps(event.__dict__, ensure_ascii=False, default=str) + "\n")
            fh.flush()
            label = f"{event.server or '-'}/{event.tool or '-'}"
            if event.kind == "tool_call":
                calls.append(label)
                print(f"[call ] {label} {json.dumps(event.data.get('arguments', {}))[:160]}", flush=True)
            elif event.kind == "tool_result":
                flag = "ERR " if event.data.get("is_error") else "ok  "
                print(f"[{flag}] {label}", flush=True)
                if event.data.get("is_error"):
                    errors.append(label)
            elif event.kind == "status":
                if event.data.get("servers"):
                    attached = event.data["servers"]
                shown = {k: len(v) for k, v in event.data["servers"].items()} if event.data.get("servers") else event.data
                print(f"[stat ] {event.text}: {json.dumps(shown, default=str)[:400]}", flush=True)
            elif event.kind == "error":
                print(f"[FAIL ] {event.text}", flush=True)
                errors.append(event.text or "error")
            elif event.kind == "done":
                final = event.text
                print(f"[done ] {json.dumps(event.data, default=str)}", flush=True)
            elif event.kind == "text":
                print(f"[text ] {event.text[:300]}", flush=True)

    missing_servers = [name for name in ("trade-sourcing", "playwright") if name not in attached]
    unused_tools = [t for t in EXPECTED_CUSTOM_CALLS if f"trade-sourcing/{t}" not in calls]

    print("\n===== SUMMARY =====", flush=True)
    print(f"servers attached: {({k: len(v) for k, v in attached.items()})}", flush=True)
    print(f"tool calls ({len(calls)}): {calls}", flush=True)
    print(f"errors: {errors or 'none'}", flush=True)
    print(f"trace: {out}", flush=True)
    if final:
        print(f"\n===== FINAL ANSWER =====\n{final}", flush=True)

    problems = []
    if missing_servers:
        problems.append(f"MCP servers never attached: {missing_servers}")
    if unused_tools:
        problems.append(f"custom tools never called: {unused_tools}")
    if errors:
        problems.append(f"tool or run errors: {errors}")
    if not final:
        problems.append("run produced no final answer")

    print("\n===== VERDICT =====", flush=True)
    for line in problems:
        print(f"FAIL  {line}", flush=True)
    if not problems:
        print("PASS  both servers attached, all five custom tools called, no errors", flush=True)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
