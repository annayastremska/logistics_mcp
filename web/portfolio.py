"""The portfolio behind the landing screen: risk for every tracked product group.

The landing view has to answer "where should I look first?" before the user asks
anything, so it cannot wait on an agent run. It calls the custom MCP server
directly over stdio -- the same server, the same tools, the same transport the
agent uses, just with no model in the loop. That keeps the whole UI fed by the
MCP server while staying deterministic and free.

One client session serves the whole portfolio: the server process is started
once, every product group is queried over it, and it is torn down at the end.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO_ROOT = Path(__file__).resolve().parents[1]

# Six product groups, all 6-digit HS subheadings. Six digits rather than the
# 4-digit heading because a heading mixes fresh and dried forms of the same
# fruit, and their unit values differ by enough to make a price comparison
# meaningless. Each one is a real Ukrainian import line.
@dataclass(frozen=True)
class Commodity:
    """One tracked product group."""

    hs_code: str
    label: str
    group: str


# Chosen for import volume Ukraine actually has, not for the shape of the basket:
# apples (080810, $0.5M) and walnuts in shell (080231, ~$0) were dropped because
# Ukraine grows and exports both, so their import lines are noise. What is left
# spans four different lead suppliers, and three of the six lean on Turkey -- a
# shared dependency that only shows up when the lines are read side by side.
PORTFOLIO: list[Commodity] = [
    Commodity("080390", "Bananas, fresh", "Fruit"),
    Commodity("070200", "Tomatoes, fresh", "Vegetables"),
    Commodity("080521", "Mandarins, fresh", "Citrus"),
    Commodity("080610", "Grapes, fresh", "Fruit"),
    Commodity("081050", "Kiwifruit, fresh", "Fruit"),
    Commodity("080212", "Almonds, shelled", "Nuts"),
]

# Ordered worst-first, so a portfolio can be sorted by how much attention a line
# needs without the browser having to know what the flag names mean.
FLAG_SEVERITY = {
    "SINGLE_SOURCE": 4,
    "HIGH_CONCENTRATION": 3,
    "MODERATE_CONCENTRATION": 2,
    "VOLATILE_SUPPLY": 2,
    "MIRROR_DISCREPANCY": 1,
    "THIN_DATA": 1,
}


@dataclass
class PortfolioRow:
    """One product group as the landing screen shows it."""

    hs_code: str
    label: str
    group: str
    status: str
    year: int | None = None
    total_value_usd: float | None = None
    partner_count: int | None = None
    top_partner_name: str | None = None
    top_partner_iso3: str | None = None
    top_partner_share_pct: float | None = None
    hhi: float | None = None
    effective_partner_count: float | None = None
    yoy_volatility_pct: float | None = None
    mirror_gap_pct: float | None = None
    flags: list[str] = field(default_factory=list)
    severity: int = 0
    interpretation: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__


def _server_params() -> StdioServerParameters:
    """How to start the custom MCP server.

    sys.executable, never a bare "python": the interpreter on PATH is the system
    one, without this project's dependencies, and a server started with it dies
    on `import mcp` while looking to the caller like a server with no tools.
    """
    return StdioServerParameters(
        command=os.environ.get("SOURCING_PYTHON", sys.executable),
        args=["-m", "mcp_server.server"],
        env={**os.environ, "SOURCING_MODE": os.environ.get("SOURCING_MODE", "live")},
        cwd=str(REPO_ROOT),
    )


def _payload(result: Any) -> dict[str, Any]:
    """Pull the structured result out of an MCP tool response.

    Every tool on this server declares an output schema, so `structuredContent`
    is the contract. The text fallback exists only so a schema-less response
    surfaces as data rather than as an exception.
    """
    if getattr(result, "structuredContent", None):
        return result.structuredContent
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"status": "error", "errors": [{"message": text[:400]}]}
    return {"status": "error", "errors": [{"message": "empty tool response"}]}


async def _one_row(session: ClientSession, item: Commodity, year: int) -> PortfolioRow:
    """Build one portfolio row from two tool calls."""
    row = PortfolioRow(hs_code=item.hs_code, label=item.label, group=item.group, status="ok", year=year)

    flows = _payload(
        await session.call_tool("get_import_flows", {"hs_code": item.hs_code, "year": year, "top_n": 20})
    )
    row.status = flows.get("status", "error")
    if row.status == "ok":
        row.total_value_usd = flows.get("total_value_usd")
        row.partner_count = flows.get("partner_count")
        row.notes = list(flows.get("notes") or [])[:2]
    else:
        # No flows means nothing to concentrate, so the second call is skipped
        # rather than sent and discarded.
        row.notes = [e.get("message", "") for e in (flows.get("errors") or [])][:2]
        return row

    # Three years, not one: the tool needs at least three observations before it
    # can report year-on-year volatility, and volatility is half of what makes a
    # concentrated line actually risky.
    risk = _payload(
        await session.call_tool(
            "assess_supply_concentration_risk",
            {"hs_code": item.hs_code, "years": [year - 2, year - 1, year]},
        )
    )
    if risk.get("status") == "ok":
        row.hhi = risk.get("hhi")
        row.top_partner_name = risk.get("top_partner_name")
        row.top_partner_iso3 = risk.get("top_partner_iso3")
        row.top_partner_share_pct = risk.get("top_partner_share_pct")
        row.effective_partner_count = risk.get("effective_partner_count")
        row.yoy_volatility_pct = risk.get("yoy_volatility_pct")
        row.mirror_gap_pct = risk.get("mirror_gap_pct")
        row.flags = list(risk.get("flags") or [])
        row.interpretation = risk.get("interpretation", "")
        row.severity = max((FLAG_SEVERITY.get(f, 0) for f in row.flags), default=0)
    else:
        # Flows landed but risk did not, so the row is usable and incomplete.
        # Saying "partial" keeps a missing HHI from reading as a low one.
        row.status = "partial"
        detail = "; ".join(e.get("message", "") for e in (risk.get("errors") or [])) or "no detail"
        row.notes.append(f"concentration unavailable ({risk.get('status')}): {detail}"[:300])

    return row


async def build_portfolio(year: int, *, items: list[Commodity] | None = None) -> dict[str, Any]:
    """Query every tracked product group over one MCP session.

    Rows are built sequentially rather than gathered: the upstream trade API is
    rate limited, and six concurrent bursts is how a demo earns a 429.
    """
    items = items or PORTFOLIO
    rows: list[PortfolioRow] = []

    async with stdio_client(_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            declared = [t.name for t in (await session.list_tools()).tools]
            for item in items:
                try:
                    rows.append(await _one_row(session, item, year))
                except Exception as exc:  # noqa: BLE001 - one bad line must not empty the screen
                    rows.append(
                        PortfolioRow(
                            hs_code=item.hs_code,
                            label=item.label,
                            group=item.group,
                            status="error",
                            year=year,
                            notes=[f"{type(exc).__name__}: {exc}"],
                        )
                    )

    rows.sort(key=lambda r: (-r.severity, -(r.total_value_usd or 0)))
    return {
        "year": year,
        "data_mode": os.environ.get("SOURCING_MODE", "live"),
        "server_tools": declared,
        "rows": [r.to_dict() for r in rows],
    }


async def commodity_detail(hs_code: str, year: int) -> dict[str, Any]:
    """Origins and risk detail for one product group, for the drill-down view.

    Returns the full origin table rather than the portfolio summary, because the
    question the detail view answers -- "who could we buy from instead?" -- needs
    the countries below the leader, which the summary row deliberately omits.
    """
    label = next((c.label for c in PORTFOLIO if c.hs_code == hs_code), hs_code)

    async with stdio_client(_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            flows = _payload(
                await session.call_tool(
                    "get_import_flows", {"hs_code": hs_code, "year": year, "top_n": 20}
                )
            )
            risk = _payload(
                await session.call_tool(
                    "assess_supply_concentration_risk",
                    {"hs_code": hs_code, "years": [year - 2, year - 1, year]},
                )
            )

    return {"hs_code": hs_code, "label": label, "year": year, "flows": flows, "risk": risk}


if __name__ == "__main__":
    year = int(sys.argv[1]) if len(sys.argv) > 1 else 2024
    result = asyncio.run(build_portfolio(year))
    print(f"server tools: {result['server_tools']}")
    for r in result["rows"]:
        print(
            f"{r['hs_code']}  {r['label']:<20} {r['status']:<8} "
            f"${(r['total_value_usd'] or 0) / 1e6:>7.1f}M  HHI={r['hhi']} "
            f"top={r['top_partner_iso3']} {r['top_partner_share_pct']}%  flags={r['flags']}"
        )
        for note in r["notes"]:
            print(f"           note: {note}")
