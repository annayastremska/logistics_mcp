"""UN Comtrade preview API: reported merchandise trade flows.

This is the project's primary data source. The free preview endpoint needs no
authentication and no key, and returns at most 500 records per call.

Two behaviours of the endpoint drive the code below, both verified against live
responses rather than taken from documentation:

* Descriptive fields (``partnerDesc``, ``cmdDesc``, ...) are always ``null``;
  names come from the vendored reference tables instead.
* Every partner is returned **twice**, once per value of the ``partner2Code``
  dimension (country of origin vs country of consignment), with identical
  figures. Summing the raw rows double-counts every share, so rows are
  deduplicated on that dimension.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .http import FetchResult, build_url, fetch_json
from .reference import UKRAINE_REPORTER_CODE, is_aggregate_partner

PREVIEW_BASE = "https://comtradeapi.un.org/public/v1/preview/C"
RECORD_CAP = 500

FlowCode = Literal["M", "X"]


@dataclass(frozen=True)
class TradeRecord:
    """One deduplicated trade record for a single partner."""

    partner_code: int
    hs_code: str
    period: str
    net_weight_kg: float | None
    value_usd: float
    quantity: float | None
    quantity_unit_code: int | None


@dataclass(frozen=True)
class FlowsResponse:
    """Deduplicated records plus the transport metadata behind them."""

    records: list[TradeRecord]
    world_total_value_usd: float | None
    raw_row_count: int
    duplicates_dropped: int
    truncated: bool
    fetch: FetchResult


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _dedupe(rows: list[dict]) -> tuple[list[dict], int]:
    """Collapse the ``partner2Code`` duplication.

    Preferred path: keep the rows whose second-partner dimension is the
    ``0`` aggregate, which is the total across all second partners. If a response
    ever lacks that aggregate, fall back to keeping the highest-value row per
    partner so a share is never inflated by double counting.
    """
    preferred = [r for r in rows if r.get("partner2Code") in (0, None)]
    if preferred and len({r.get("partnerCode") for r in preferred}) == len(preferred):
        return preferred, len(rows) - len(preferred)

    best: dict[tuple[int, str], dict] = {}
    for row in rows:
        key = (row.get("partnerCode"), str(row.get("cmdCode")))
        current = best.get(key)
        if current is None or (_to_float(row.get("primaryValue")) or 0) > (
            _to_float(current.get("primaryValue")) or 0
        ):
            best[key] = row
    kept = list(best.values())
    return kept, len(rows) - len(kept)


def fetch_flows(
    *,
    hs_code: str,
    year: int,
    flow: FlowCode = "M",
    reporter_code: int = UKRAINE_REPORTER_CODE,
    partner_code: int | None = None,
) -> FlowsResponse:
    """Fetch annual flows for one HS code and period.

    Args:
        hs_code: HS2022 code, 2/4/6 digits.
        year: Reference year.
        flow: ``M`` for imports reported by ``reporter_code``, ``X`` for exports.
        reporter_code: Comtrade reporter; defaults to Ukraine (804).
        partner_code: Restrict to one partner, or None for every partner.

    Raises:
        UpstreamError: propagated from the transport layer.
    """
    url = build_url(
        f"{PREVIEW_BASE}/A/HS",
        {
            "reporterCode": reporter_code,
            "period": year,
            "cmdCode": hs_code,
            "flowCode": flow,
            "partnerCode": partner_code,
        },
    )
    fetch = fetch_json(url)
    payload = fetch.payload if isinstance(fetch.payload, dict) else {}
    rows = [r for r in (payload.get("data") or []) if isinstance(r, dict)]
    raw_count = len(rows)

    deduped, dropped = _dedupe(rows)

    world_total: float | None = None
    records: list[TradeRecord] = []
    for row in deduped:
        code = row.get("partnerCode")
        if not isinstance(code, int):
            continue
        value = _to_float(row.get("primaryValue")) or 0.0
        if is_aggregate_partner(code):
            if code == 0:
                world_total = value
            continue
        records.append(
            TradeRecord(
                partner_code=code,
                hs_code=str(row.get("cmdCode") or hs_code),
                period=str(row.get("period") or year),
                net_weight_kg=_to_float(row.get("netWgt")) or None,
                value_usd=value,
                quantity=_to_float(row.get("qty")),
                quantity_unit_code=row.get("qtyUnitCode") if isinstance(row.get("qtyUnitCode"), int) else None,
            )
        )

    records.sort(key=lambda r: r.value_usd, reverse=True)
    return FlowsResponse(
        records=records,
        world_total_value_usd=world_total,
        raw_row_count=raw_count,
        duplicates_dropped=dropped,
        truncated=raw_count >= RECORD_CAP,
        fetch=fetch,
    )


def latest_reported_year(*, probe_hs_code: str = "0806", earliest: int = 2018) -> int | None:
    """Find the most recent year Ukraine has actually reported.

    Ukraine's latest complete annual year lags the calendar by about a year, and
    hardcoding it would silently rot. Walks backwards from the current year,
    stopping at the first year that returns records.
    """
    from datetime import date

    for year in range(date.today().year, earliest - 1, -1):
        try:
            response = fetch_flows(hs_code=probe_hs_code, year=year)
        except Exception:  # noqa: BLE001 - a probe failure must not break validation
            return None
        if response.records:
            return year
    return None


@dataclass(frozen=True)
class MirrorComparison:
    """What partners reported exporting to Ukraine, per partner."""

    reported_by_partner_usd: dict[int, float]
    partners_that_report: list[int]
    partners_silent: list[int]
    mode: str


def fetch_reported_exports_to_ukraine(
    *, hs_code: str, year: int, partner_codes: list[int]
) -> MirrorComparison:
    """Ask each partner what it reported exporting to Ukraine.

    A mirror comparison has to swap the roles: the *partner* becomes the reporter
    and Ukraine becomes the counterpart. Querying Ukraine as reporter with Ukraine
    as partner -- the obvious-looking shortcut -- returns nothing at all and makes
    every gap look like -100 percent.

    Partners that do not report to Comtrade are returned separately in
    ``partners_silent`` so they can be excluded from the comparison rather than
    counted as zero.
    """
    reported: dict[int, float] = {}
    silent: list[int] = []
    mode = "live"

    for code in partner_codes:
        try:
            response = fetch_flows(
                hs_code=hs_code,
                year=year,
                flow="X",
                reporter_code=code,
                partner_code=UKRAINE_REPORTER_CODE,
            )
        except Exception:  # noqa: BLE001 - one silent partner must not fail the check
            silent.append(code)
            continue
        if response.fetch.mode == "replay":
            mode = "fixture"
        total = sum(r.value_usd for r in response.records)
        if total <= 0:
            silent.append(code)
        else:
            reported[code] = total

    return MirrorComparison(
        reported_by_partner_usd=reported,
        partners_that_report=list(reported),
        partners_silent=silent,
        mode=mode,
    )
