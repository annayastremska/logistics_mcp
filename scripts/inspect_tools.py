"""Print the tool contracts this server publishes over MCP.

Used as defence evidence that the server exposes the required tools with explicit
input *and* output schemas:

    python scripts/inspect_tools.py            # summary table
    python scripts/inspect_tools.py --json     # full JSON schemas
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp_server.server import mcp  # noqa: E402


async def main() -> None:
    tools = await mcp.list_tools()
    as_json = "--json" in sys.argv

    if as_json:
        print(
            json.dumps(
                [
                    {
                        "name": t.name,
                        "title": getattr(t, "title", None),
                        "description": t.description,
                        "input_schema": t.input_schema,
                        "output_schema": getattr(t, "output_schema", None),
                        "annotations": t.annotations.model_dump() if t.annotations else None,
                    }
                    for t in tools
                ],
                indent=2,
                ensure_ascii=False,
            )
        )
        return

    print(f"server: {mcp.name} v{mcp.version}")
    print(f"tools exposed: {len(tools)}\n")
    for tool in sorted(tools, key=lambda t: t.name):
        schema = tool.input_schema or {}
        required = schema.get("required") or []
        properties = list((schema.get("properties") or {}).keys())
        output = getattr(tool, "output_schema", None)
        print(f"- {tool.name}")
        print(f"    input     : {len(properties)} fields, required: {', '.join(required) or 'none'}")
        print(f"    optional  : {', '.join(p for p in properties if p not in required) or 'none'}")
        print(f"    output    : {'declared' if output else 'MISSING'}", end="")
        if output:
            print(f" ({len((output.get('properties') or {}))} fields)")
        else:
            print()
        annotations = tool.annotations
        if annotations:
            print(
                f"    readOnly={annotations.read_only_hint} "
                f"idempotent={annotations.idempotent_hint} "
                f"openWorld={annotations.open_world_hint}"
            )
        print(f"    description: {(tool.description or '')[:110]}...")
        print()


asyncio.run(main())
