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
import sys
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
    UserMessage,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

CUSTOM_SERVER = "trade-sourcing"
PLAYWRIGHT_SERVER = "playwright"

# The browser server is spawned directly rather than through the npx shim.
# Measured: bare "npx" is not an executable on Windows -- the extensionless file
# beside node is a POSIX shell script and CreateProcess refuses it -- and
# "npx.cmd" does not help either, because Node refuses to spawn a .cmd without a
# shell. Either way the server never started, the run continued, and the model
# reported it had no browser tool: the recency check silently went unperformed.
# The package is pinned in package.json, so its entry point is a plain .js file
# that node can execute with no shim, no shell and no network fetch per run.
# npx stays as the fallback for a checkout where npm install has not been run.
PLAYWRIGHT_CLI = Path(__file__).resolve().parent.parent / "node_modules" / "@playwright" / "mcp" / "cli.js"


def _playwright_command() -> tuple[str, list[str]]:
    """Return the command and leading arguments that start the browser server."""
    if PLAYWRIGHT_CLI.exists():
        return os.environ.get("SOURCING_NODE", "node"), [str(PLAYWRIGHT_CLI)]
    return os.environ.get("SOURCING_NPX", "npx.cmd" if sys.platform == "win32" else "npx"), [
        "-y",
        "@playwright/mcp@latest",
    ]

# The one page the browser is permitted to visit: the State Customs Service
# publishes current-year turnover as HTML and nowhere else.
CUSTOMS_TURNOVER_URL = os.environ.get(
    "SOURCING_CUSTOMS_URL",
    "https://customs.gov.ua/news/zagalne-20/post/za-sim-misiatsiv-2026-roku-tovaroobig-ukrayini-sklav-822-mlrd-2947",
)
# Fallbacks, tried in order. The customs page is the primary source and the one
# worth reading, but its edge (Akamai) returns HTTP 403 to automated clients even
# with a browser user agent, while opening fine in a human's browser. Rather than
# pretend the recency check works, the agent falls through to the National Bank's
# external-sector page, which serves the same purpose and is actually reachable.
RECENCY_FALLBACK_URLS = [
    "https://bank.gov.ua/ua/statistic/sector-external",
    "https://index.minfin.com.ua/economy/gdp/eximp/",
]

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

# Two model tiers. The sourcing analysis is a long multi-step agentic run where a
# wrong turn wastes rate-limited API calls, so it gets the capable model. Chat
# questions about an already-computed result, and one-shot lookups, are short and
# well-scoped: a small model answers them faster and far cheaper.
MODEL_TIERS = {
    # Sonnet, measured against Opus on the same end-to-end run: both PASS, 23
    # turns against 20, 595s against 620, $0.398 against $0.547 -- and Sonnet
    # walked the whole recency fallback chain to a usable turnover figure where
    # Opus stopped at the second source with a partial result.
    "analysis": (os.environ.get("SOURCING_ANALYSIS_MODEL", "claude-sonnet-5"), "high", 24),
    "chat": (os.environ.get("SOURCING_CHAT_MODEL", "claude-haiku-4-5"), "low", 6),
}

# The chat tier is deliberately narrower: it may read data and explain it, but it
# does not drive the browser or re-run a whole ranking.
CHAT_TOOLS = ["validate_sourcing_brief", "get_import_flows", "assess_supply_concentration_risk"]

CHAT_SYSTEM_PROMPT = """You answer follow-up questions about Ukrainian import sourcing data, briefly and concretely.

You have read-only tools over open trade data. Use one only when the answer needs a figure you do not already have in the conversation; otherwise answer directly from what is there.

Keep answers to a few sentences. Always name the data year. Never present modelled freight or an MFN duty rate as the rate actually paid. If a tool returns status 'empty', say the source has no record for that period rather than guessing."""

# This string is a str.format template: every literal brace must be doubled.
# An un-doubled brace in the JSON example below raised KeyError inside
# build_options() and took out eight tests.
SYSTEM_PROMPT = """\
You are an import sourcing analyst for Ukraine. You answer questions about which countries a \
product group should be sourced from, using only the tools you have been given. You have no \
shell, no filesystem and no general web access.

Work in this order, and let each result change what you do next:

1. Read a current-year trade turnover figure with the browser tools. Try these pages in order \
and stop at the first that loads:
{recency_urls}
   Name which page you actually read. Use the figure only to judge how stale your statistical \
data is. If every page fails, say so plainly, mark the recency check as failed, and carry on \
with the statistical data alone.
2. `validate_sourcing_brief` to resolve the product to an HS code. If it returns status \
'error', stop and report the problem instead of guessing a code.
3. `get_import_flows` to find who actually supplies it.
4. `assess_supply_concentration_risk`. **This step decides what you do next.** If it flags \
HIGH_CONCENTRATION or SINGLE_SOURCE, your candidate list must reach beyond the current top \
suppliers, and you should weight supply capacity lower and logistics higher, because the point \
of the exercise is then diversification rather than reinforcing a dependency.
5. `estimate_landed_cost` for candidates worth costing. When step 4 flagged concentration, \
at least two of your candidates must be origins that did **not** appear in step 3 -- countries \
Ukraine does not currently buy this product from. Those calls come back status 'empty', because \
a unit value can only be derived from trade that actually happened; that is the tool telling \
you to supply `unit_price_usd_per_kg` yourself. Do so, and name the basis in the same \
sentence: the unit value of a comparable incumbent, or a figure from a page you read. A \
shortlist containing only the suppliers we already depend on cannot answer the question that \
was asked.
6. `rank_sourcing_countries` with weights you justify out loud, based on what step 4 found. \
Pass the widened candidates in the same call as the incumbents, so the comparison is one \
table and not two -- and pass the proxy prices you used in step 5 as `unit_prices`, keyed \
by ISO3. Without them a widened origin is unscored on price and duty and lands at the \
bottom of the table for having no data rather than for being a poor choice. Rank once. Transport mode does not change the scores -- reported unit values are already CIF, so \
modelled freight is reference-only and excluded from the total -- so splitting the candidates into \
a road set and a sea set produces two identical answers and wastes rate-limited calls.

Rules you do not break:

- A tool result with status 'empty' is a real answer. Do not retry it and do not treat it as an \
error.
- Never present a modelled number as measured. Freight is modelled; say so whenever you quote \
a landed cost. A unit price you supplied yourself is a proxy, not an observation: say whose \
figure it is every time you use it.
- Duty figures are MFN rates. If fta_preference_possible is true, say the real rate may be \
lower.
- State the data year. Comtrade lags by about two years.
- Close with a recommendation, the two or three facts it rests on, and what would change it.

Then, as the very last thing in your reply, emit exactly one fenced ```json block. It is read \
by the interface, not by a person, so it must parse and must contain only these keys:

{{"headline": "one sentence, under 120 characters",
 "allocation": [{{"origin": "Türkiye", "iso3": "TUR", "share_pct": 58, "role": "price anchor"}}],
 "facts": ["short sentence", "short sentence", "short sentence"],
 "would_change_it": "one sentence"}}

Rules for the block: allocation shares are whole numbers summing to 100, and each entry needs a \
role of a few words. Two or three facts, each one sentence. If the honest answer is to change \
nothing, say so in the headline and give allocation a single entry at 100. Never put a figure in \
the block that does not appear in your reply above it.\
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
    profile: Literal["analysis", "chat"] = "analysis",
    replay: bool = False,
    include_playwright: bool = True,
    break_playwright: bool = False,
    model: str | None = None,
    max_turns: int | None = None,
) -> ClaudeAgentOptions:
    """Assemble the agent configuration, including both MCP connections.

    Args:
        profile: ``analysis`` for the full multi-step sourcing run on the capable
            model, or ``chat`` for short follow-up questions on the small model.
        replay: Run the custom server against recorded fixtures with no network.
        include_playwright: Attach the existing Playwright MCP server. Forced off
            for the chat profile, which has no reason to drive a browser.
        break_playwright: Point the browser at an unresolvable host, to demonstrate
            how a failure of the existing server surfaces. The failure is produced
            by changing the input, not by faking an error.
        model: Model override; defaults to the profile's tier.
        max_turns: Turn ceiling override; defaults to the profile's tier.
    """
    tier_model, tier_effort, tier_turns = MODEL_TIERS[profile]
    if profile == "chat":
        include_playwright = False
    server_env = {"SOURCING_MODE": "replay" if replay else os.environ.get("SOURCING_MODE", "live")}

    mcp_servers: dict[str, Any] = {
        CUSTOM_SERVER: {
            "type": "stdio",
            # sys.executable, not a bare "python": the interpreter on PATH is the
            # system one, which has none of this project's dependencies. Spawning
            # with it starts a server process that dies on `import mcp`, and the
            # agent then simply sees no sourcing tools at all.
            "command": os.environ.get("SOURCING_PYTHON", sys.executable),
            "args": ["-m", "mcp_server.server"],
            "env": {**os.environ, **server_env},
        }
    }
    allowed = [_qualified(CUSTOM_SERVER, tool) for tool in CUSTOM_TOOLS]

    if profile == "chat":
        allowed = [_qualified(CUSTOM_SERVER, tool) for tool in CHAT_TOOLS]

    if include_playwright:
        browser_command, browser_args = _playwright_command()
        mcp_servers[PLAYWRIGHT_SERVER] = {
            "type": "stdio",
            "command": browser_command,
            "args": [
                *browser_args,
                "--headless",
                # A fresh profile per run: no cookies or storage are carried over,
                # and nothing about the developer's own browser session is touched.
                "--isolated",
            ],
        }
        allowed += [_qualified(PLAYWRIGHT_SERVER, tool) for tool in PLAYWRIGHT_TOOLS]

    # The failure demo gets a single unresolvable host and no fallbacks, so the
    # failure it shows is the browser server's, not a fallback quietly rescuing it.
    urls = [BROKEN_URL] if break_playwright else [CUSTOMS_TURNOVER_URL, *RECENCY_FALLBACK_URLS]

    return ClaudeAgentOptions(
        model=model or tier_model,
        system_prompt=(
            CHAT_SYSTEM_PROMPT
            if profile == "chat"
            else SYSTEM_PROMPT.format(
                recency_urls="\n".join(f"   - {url}" for url in urls)
            )
        ),
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
        max_turns=max_turns or tier_turns,
        cwd=str(REPO_ROOT),
        effort=tier_effort,
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
    profile: Literal["analysis", "chat"] = "analysis",
    replay: bool = False,
    include_playwright: bool = True,
    break_playwright: bool = False,
    context: str | None = None,
) -> AsyncIterator[TraceEvent]:
    """Run one question, yielding trace events as they happen.

    Args:
        context: Already-computed findings to hand the chat tier, so a follow-up
            question does not re-run the whole analysis to restate a number.
    """
    options = build_options(
        profile=profile,
        replay=replay,
        include_playwright=include_playwright,
        break_playwright=break_playwright,
    )
    if context:
        question = (
            f"Current analysis on screen:\n{context}\n\nQuestion: {question}"
        )

    yield TraceEvent(
        kind="status",
        text="starting agent",
        data={
            "profile": profile,
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
                # Tool results come back on a UserMessage, not the assistant turn
                # that requested them. Watching only AssistantMessage yields a
                # trace of calls with no outcomes -- every call looks like it
                # succeeded, including the ones that did not.
                elif isinstance(message, UserMessage):
                    blocks = message.content if isinstance(message.content, list) else []
                    for block in blocks:
                        if isinstance(block, ToolResultBlock):
                            server, tool = pending.pop(block.tool_use_id, (None, "unknown"))
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


def _shorten(content: Any, limit: int = 24000) -> Any:
    """Trim a tool result for transport to the browser without losing its shape.

    The limit is generous because the interface parses these payloads rather than
    only displaying them: a ranking of ten candidates with a four-factor
    decomposition is about 4KB, and truncating it mid-JSON left the browser with
    a string it could not read, so the table had to be reconstructed from the
    model's prose instead of from the figures.
    """
    if isinstance(content, str):
        return content if len(content) <= limit else content[:limit] + f"... [{len(content)} chars]"
    if isinstance(content, list):
        return [_shorten(item, limit // max(len(content), 1)) for item in content]
    if isinstance(content, dict):
        return {k: _shorten(v, limit // 2) for k, v in content.items()}
    return content
