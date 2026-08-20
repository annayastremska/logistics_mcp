"""How the landing screen's rows are assembled, and in what order they appear.

The rows are the first thing anyone sees, and they are built from two tool calls
whose failures are not symmetrical: no flows means there is nothing to
concentrate, so the second call must not be sent; flows without concentration
means the row is usable and incomplete, and must not read as a row with a low
HHI. Both of those are decisions in ``_one_row`` rather than in the tools, so
they are tested here, against a stub session -- no server, no network.

Run with:  python -m pytest tests -q
"""

from __future__ import annotations

import asyncio
from typing import Any

from web.portfolio import FLAG_SEVERITY, Commodity, PortfolioRow, _one_row

FLOWS_OK = {
    "status": "ok",
    "total_value_usd": 12_000_000.0,
    "partner_count": 7,
    "notes": ["note one", "note two", "note three"],
    "provenance": {"as_of": "Oct 2024 – Sep 2025"},
}

RISK_OK = {
    "status": "ok",
    "hhi": 4503.0,
    "top_partner_name": "Türkiye",
    "top_partner_iso3": "TUR",
    "top_partner_share_pct": 64.8,
    "effective_partner_count": 2.2,
    "yoy_volatility_pct": 31.0,
    "mirror_gap_pct": -8.0,
    "flags": ["HIGH_CONCENTRATION", "VOLATILE_SUPPLY"],
    "interpretation": "Two thirds from one origin.",
}


class _Result:
    """Stands in for an MCP CallToolResult carrying structured output."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.structuredContent = payload
        self.content: list[Any] = []


class _Session:
    """Records the calls made, and answers each from a fixed script."""

    def __init__(self, script: dict[str, dict[str, Any]]) -> None:
        self.script = script
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, name: str, args: dict[str, Any]) -> _Result:
        self.calls.append((name, args))
        return _Result(self.script[name])


def _row(script: dict[str, dict[str, Any]], *, window: str | None = "latest"):
    session = _Session(script)
    item = Commodity("080610", "Grapes, fresh", "Fruit")
    row = asyncio.run(_one_row(session, item, 2024, window))
    return row, session


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #


def test_a_complete_row_carries_both_calls_and_the_period_the_tools_reported() -> None:
    row, session = _row({"get_import_flows": FLOWS_OK, "assess_supply_concentration_risk": RISK_OK})

    assert [name for name, _ in session.calls] == [
        "get_import_flows",
        "assess_supply_concentration_risk",
    ]
    assert row.status == "ok"
    assert row.total_value_usd == 12_000_000.0
    assert row.partner_count == 7
    assert row.hhi == 4503.0
    assert row.top_partner_iso3 == "TUR"

    # The period shown is the one the tool reported, never the year we asked for:
    # a trailing window and an annual basis are different claims about the data.
    assert row.period_label == "Oct 2024 – Sep 2025"

    # Two notes at most. The screen has room for two, and a row that quietly
    # grows a third pushes the figures out of alignment.
    assert row.notes == ["note one", "note two"]


def test_the_window_is_passed_to_both_calls_and_omitted_when_not_asked_for() -> None:
    _, windowed = _row({"get_import_flows": FLOWS_OK, "assess_supply_concentration_risk": RISK_OK})
    assert all(args.get("trailing_12m_to") == "latest" for _, args in windowed.calls)

    _, annual = _row(
        {"get_import_flows": FLOWS_OK, "assess_supply_concentration_risk": RISK_OK}, window=None
    )
    assert all("trailing_12m_to" not in args for _, args in annual.calls)


def test_volatility_is_asked_for_over_three_years_because_two_cannot_show_it() -> None:
    _, session = _row({"get_import_flows": FLOWS_OK, "assess_supply_concentration_risk": RISK_OK})
    risk_args = next(args for name, args in session.calls if name.startswith("assess"))
    assert risk_args["years"] == [2022, 2023, 2024]


# --------------------------------------------------------------------------- #
# The two failures are not the same failure
# --------------------------------------------------------------------------- #


def test_no_flows_means_the_second_call_is_never_sent() -> None:
    """There is nothing to concentrate, so the call would be sent and discarded."""
    row, session = _row(
        {
            "get_import_flows": {"status": "empty", "errors": [{"message": "no reported trade"}]},
            "assess_supply_concentration_risk": RISK_OK,
        }
    )
    assert [name for name, _ in session.calls] == ["get_import_flows"]
    assert row.status == "empty"
    assert row.notes == ["no reported trade"]
    assert row.hhi is None


def test_flows_without_concentration_is_partial_not_ok() -> None:
    """A missing HHI must not be readable as a low one.

    The row has real value and partner figures, so it stays on screen -- but if
    its status said "ok" while hhi was null, an empty concentration column would
    look like a diversified line rather than an unanswered question.
    """
    row, _ = _row(
        {
            "get_import_flows": FLOWS_OK,
            "assess_supply_concentration_risk": {
                "status": "error",
                "errors": [{"message": "upstream 429"}],
            },
        }
    )
    assert row.status == "partial"
    assert row.total_value_usd == 12_000_000.0
    assert row.hhi is None
    assert row.severity == 0
    assert any("concentration unavailable" in note and "upstream 429" in note for note in row.notes)


# --------------------------------------------------------------------------- #
# Severity and ordering
# --------------------------------------------------------------------------- #


def test_severity_is_the_worst_flag_not_the_first_or_the_sum() -> None:
    row, _ = _row(
        {
            "get_import_flows": FLOWS_OK,
            "assess_supply_concentration_risk": {
                **RISK_OK,
                # Deliberately worst-last: a first-flag rule would score this 1.
                "flags": ["MIRROR_DISCREPANCY", "THIN_DATA", "SINGLE_SOURCE"],
            },
        }
    )
    assert row.severity == FLAG_SEVERITY["SINGLE_SOURCE"] == 4


def test_an_unknown_flag_scores_zero_rather_than_raising() -> None:
    """A flag added upstream must not take the landing screen down."""
    row, _ = _row(
        {
            "get_import_flows": FLOWS_OK,
            "assess_supply_concentration_risk": {**RISK_OK, "flags": ["SOMETHING_NEW"]},
        }
    )
    assert row.severity == 0
    assert row.flags == ["SOMETHING_NEW"]


def test_rows_sort_worst_first_then_by_size() -> None:
    """The sort the screen depends on: attention first, money as the tiebreak."""
    rows = [
        PortfolioRow("A", "a", "g", "ok", severity=0, total_value_usd=90.0),
        PortfolioRow("B", "b", "g", "ok", severity=4, total_value_usd=10.0),
        PortfolioRow("C", "c", "g", "ok", severity=2, total_value_usd=50.0),
        PortfolioRow("D", "d", "g", "ok", severity=4, total_value_usd=80.0),
        PortfolioRow("E", "e", "g", "error", severity=0, total_value_usd=None),
    ]
    rows.sort(key=lambda r: (-r.severity, -(r.total_value_usd or 0)))
    assert [r.hs_code for r in rows] == ["D", "B", "C", "A", "E"]
