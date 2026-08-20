"""The sourcing agent: Claude Agent SDK wired to both MCP connections.

Two deliberate lockdowns, both visible in ``build_options``:

* ``tools=[]`` — the agent gets **none** of Claude Code's built-in tools. No Bash,
  no file editing, no shell. Its entire capability surface is the two MCP servers,
  which is what makes the MCP boundary the real boundary rather than a decoration.
* ``setting_sources=[]`` and ``plugins=[]`` — no user or project configuration is
  loaded. Without this the developer's own ``~/.claude`` plugins and hooks inject
  themselves into the agent session, which pollutes the context and makes a demo
  unreproducible on another machine.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
from claude_agent_sdk.types import (
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

CUSTOM_SERVER = "trade-sourcing"
PLAYWRIGHT_SERVER = "playwright"

# The one page the browser is permitted to visit: the State Customs Service
# publishes current-year turnover as HTML and nowhere else.
CUSTOMS_TURNOVER_URL = os.environ.get(
    "SOURCING_CUSTOMS_URL",
    "https://customs.gov.ua/news/zagalne-20/post/za-sim-misiatsiv-2026-roku-tovaroobig-ukrayini-sklav-822-mlrd-2947",
)
# Used only by the deliberate-failure demo: a host that cannot resolve.
BROKEN_URL = "https://customs.gov.ua.invalid/this-page-does-not-exist"

CUSTOM_TOOLS = [
    "validate_sourcing_brief",
    "get_import_flows",
    "estimate_landed_cost",
    "rank_sourcing_countries",
    "assess_supply_concentration_risk",
]

PLAYWRIGHT_TOOLS = ["browser_navigate", "browser_snapshot", "browser_close"]

SYSTEM_PROMPT = """\
You are an import sourcing analyst for Ukraine. You answer questions about which countries a \
product group should be sourced from, using only the tools you have been given. You have no \
shell, no filesystem and no general web access.

Work in this order, and let each result change what you do next:

1. Read the current-year trade turnover figure from the customs page with the browser tools \
({customs_url}). Use it only to judge how stale your statistical data is. If the page cannot \
be reached, say so plainly, mark the recency check as failed, and carry on with the \
statistical data alone.
2. `validate_sourcing_brief` to resolve the product to an HS code. If it returns status \
'error', stop and report the problem instead of guessing a code.
3. `get_import_flows` to find who actually supplies it.
4. `assess_supply_concentration_risk`. **This step decides what you do next.** If it flags \
HIGH_CONCENTRATION or SINGLE_SOURCE, your candidate list must reach beyond the current top \
suppliers, and you should weight supply capacity lower and logistics higher, because the point \
of the exercise is then diversification rather than reinforcing a dependency.
5. `estimate_landed_cost` for candidates worth costing.
6. `rank_sourcing_countries` with weights you justify out loud, based on what step 4 found.

Rules you do not break:

- A tool result with status 'empty' is a real answer. Do not retry it and do not treat it as an \
error.
- Never present a modelled number as measured. Freight is modelled; say so whenever you quote \
a landed cost.
- Duty figures are MFN rates. If fta_preference_possible is true, say the real rate may be \
lower.
- State the data year. Comtrade lags by about two years.
- Close with a recommendation, the two or three facts it rests on, and what would change it.\
"""


@dataclass
class TraceEvent:
    """One observable step of the run, for the trace panel."""

    kind: Literal["status", "tool_call", "tool_result", "text", "thinking", "error", "done"]
    server: str | None = None
    tool: str | None = None
    text: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "server": self.server,
            "tool": self.tool,
            "text": self.text,
            "data": self.data,
        }


def _qualified(server: str, tool: str) -> str:
    """MCP tools are namespaced as mcp__<server>__<tool> by the SDK."""
    return f"mcp__{server}__{tool}"


def split_tool_name(name: str) -> tuple[str | None, str]:
    """Split ``mcp__server__tool`` back into its parts for display."""
    if name.startswith("mcp__"):
        parts = name.split("__", 2)
        if len(parts) == 3:
            return parts[1], parts[2]
    return None, name


def build_options(
    *,
    replay: bool = False,
    include_playwright: bool = True,
    break_playwright: bool = False,
    model: str | None = None,
    max_turns: int = 24,
) -> ClaudeAgentOptions:
    """Assemble the agent configuration, including both MCP connections.

    Args:
        replay: Run the custom server against recorded fixtures with no network.
        include_playwright: Attach the existing Playwright MCP server.
        break_playwright: Point the browser at an unresolvable host, to demonstrate
            how a failure of the existing server surfaces. The failure is produced
            by changing the input, not by faking an error.
        model: Model override; defaults to ``SOURCING_AGENT_MODEL``.
        max_turns: Hard ceiling on agent turns.
    """
    server_env = {"SOURCING_MODE": "replay" if replay else os.environ.get("SOURCING_MODE", "live")}

    mcp_servers: dict[str, Any] = {
        CUSTOM_SERVER: {
            "type": "stdio",
            "command": os.environ.get("SOURCING_PYTHON", "python"),
            "args": ["-m", "mcp_server.server"],
            "env": {**os.environ, **server_env},
        }
    }
    allowed = [_qualified(CUSTOM_SERVER, tool) for tool in CUSTOM_TOOLS]

    if include_playwright:
        mcp_servers[PLAYWRIGHT_SERVER] = {
            "type": "stdio",
            "command": os.environ.get("SOURCING_NPX", "npx"),
            "args": [
                "-y",
                "@playwright/mcp@latest",
                "--headless",
                # A fresh profile per run: no cookies or storage are carried over,
                # and nothing about the developer's own browser session is touched.
                "--isolated",
            ],
        }
        allowed += [_qualified(PLAYWRIGHT_SERVER, tool) for tool in PLAYWRIGHT_TOOLS]

    target_url = BROKEN_URL if break_playwright else CUSTOMS_TURNOVER_URL

    return ClaudeAgentOptions(
        model=model or os.environ.get("SOURCING_AGENT_MODEL", "claude-opus-5"),
        system_prompt=SYSTEM_PROMPT.format(customs_url=target_url),
        # No built-in tools at all: the MCP servers are the entire capability surface.
        tools=[],
        mcp_servers=mcp_servers,
        allowed_tools=allowed,
        strict_mcp_config=True,
        # Do not inherit the developer's own Claude Code configuration.
        setting_sources=[],
        plugins=[],
        skills=None,
        permission_mode="bypassPermissions",  # every allowed tool is read-only
        max_turns=max_turns,
        cwd=str(REPO_ROOT),
        effort="high",
    )


async def discover_connections(options: ClaudeAgentOptions) -> dict[str, list[str]]:
    """Connect and report which tools each MCP server actually exposed.

    This is the evidence that both connections initialised, and it is read from the
    live session rather than from our own configuration.
    """
    found: dict[str, list[str]] = {}
    async with ClaudeSDKClient(options=options) as client:
        await client.query("Reply with the single word: ready")
        async for message in client.receive_response():
            if isinstance(message, SystemMessage) and message.subtype == "init":
                for name in message.data.get("tools", []):
                    server, tool = split_tool_name(name)
                    if server:
                        found.setdefault(server, []).append(tool)
                break
    return found


async def run_sourcing_query(
    question: str,
    *,
    replay: bool = False,
    include_playwright: bool = True,
    break_playwright: bool = False,
) -> AsyncIterator[TraceEvent]:
    """Run one sourcing question, yielding trace events as they happen."""
    options = build_options(
        replay=replay, include_playwright=include_playwright, break_playwright=break_playwright
    )

    yield TraceEvent(
        kind="status",
        text="starting agent",
        data={
            "model": options.model,
            "data_mode": "replay" if replay else os.environ.get("SOURCING_MODE", "live"),
            "playwright_attached": include_playwright,
            "failure_demo": break_playwright,
        },
    )

    pending: dict[str, tuple[str | None, str]] = {}

    try:
        async with ClaudeSDKClient(options=options) as client:
            await client.query(question)
            async for message in client.receive_response():
                if isinstance(message, SystemMessage) and message.subtype == "init":
                    servers: dict[str, list[str]] = {}
                    for name in message.data.get("tools", []):
                        server, tool = split_tool_name(name)
                        if server:
                            servers.setdefault(server, []).append(tool)
                    yield TraceEvent(
                        kind="status", text="MCP connections discovered", data={"servers": servers}
                    )

                elif isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, ToolUseBlock):
                            server, tool = split_tool_name(block.name)
                            pending[block.id] = (server, tool)
                            yield TraceEvent(
                                kind="tool_call", server=server, tool=tool, data={"arguments": block.input}
                            )
                        elif isinstance(block, TextBlock) and block.text.strip():
                            yield TraceEvent(kind="text", text=block.text)
                        elif isinstance(block, ThinkingBlock):
                            summary = getattr(block, "thinking", "") or ""
                            if summary.strip():
                                yield TraceEvent(kind="thinking", text=summary)
                        elif isinstance(block, ToolResultBlock):
                            server, tool = pending.get(block.tool_use_id, (None, "unknown"))
                            yield TraceEvent(
                                kind="tool_result",
                                server=server,
                                tool=tool,
                                data={"is_error": bool(block.is_error), "content": _shorten(block.content)},
                            )

                elif isinstance(message, ResultMessage):
                    yield TraceEvent(
                        kind="done",
                        text=getattr(message, "result", None),
                        data={
                            "is_error": bool(getattr(message, "is_error", False)),
                            "turns": getattr(message, "num_turns", None),
                            "duration_ms": getattr(message, "duration_ms", None),
                            "cost_usd": getattr(message, "total_cost_usd", None),
                        },
                    )
    except Exception as exc:  # noqa: BLE001 - the UI must see why a run died
        yield TraceEvent(kind="error", text=f"{type(exc).__name__}: {exc}")


def _shorten(content: Any, limit: int = 4000) -> Any:
    """Trim a tool result for transport to the browser without losing its shape."""
    if isinstance(content, str):
        return content if len(content) <= limit else content[:limit] + f"... [{len(content)} chars]"
    if isinstance(content, list):
        return [_shorten(item, limit // max(len(content), 1)) for item in content]
    if isinstance(content, dict):
        return {k: _shorten(v, limit // 2) for k, v in content.items()}
    return content
