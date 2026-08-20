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

from .http import FetchResult, UpstreamError, build_url, fetch_json
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
    return _fetch_period(
        frequency="A",
        period=year,
        hs_code=hs_code,
        flow=flow,
        reporter_code=reporter_code,
        partner_code=partner_code,
    )


def fetch_monthly_flows(
    *,
    hs_code: str,
    period: str,
    flow: FlowCode = "M",
    reporter_code: int = UKRAINE_REPORTER_CODE,
    partner_code: int | None = None,
) -> FlowsResponse:
    """Fetch one month of flows.

    Monthly reporting runs well ahead of the annual series -- as of August 2026
    Ukraine's latest complete annual year is 2024, while monthly data reaches
    September 2025. For seasonal produce the monthly series is also the more
    honest one: an annual aggregate cannot distinguish a counter-season supplier
    from an in-season one at all.

    Args:
        period: ``YYYYMM``.
    """
    if not (len(period) == 6 and period.isdigit() and 1 <= int(period[4:]) <= 12):
        raise UpstreamError("INVALID_ARGUMENT", f"Monthly period must be YYYYMM; got {period!r}.")
    return _fetch_period(
        frequency="M",
        period=period,
        hs_code=hs_code,
        flow=flow,
        reporter_code=reporter_code,
        partner_code=partner_code,
    )


def _fetch_period(
    *,
    frequency: str,
    period: int | str,
    hs_code: str,
    flow: FlowCode,
    reporter_code: int,
    partner_code: int | None,
) -> FlowsResponse:
    """Fetch and normalise one period at either frequency.

    Annual and monthly differ only in the path segment and the period format, so
    they share every downstream step -- deduplication included. Splitting them
    would mean two places to keep that logic correct.
    """
    url = build_url(
        f"{PREVIEW_BASE}/{frequency}/HS",
        {
            "reporterCode": reporter_code,
            "period": period,
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
                period=str(row.get("period") or period),
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


def months_ending(period: str, count: int = 12) -> list[str]:
    """The ``count`` monthly periods ending at ``period`` inclusive, oldest first."""
    year, month = int(period[:4]), int(period[4:])
    out: list[str] = []
    for back in range(count - 1, -1, -1):
        total = year * 12 + (month - 1) - back
        out.append(f"{total // 12:04d}{total % 12 + 1:02d}")
    return out


def fetch_trailing_window(
    *,
    hs_code: str,
    end_period: str,
    months: int = 12,
    flow: FlowCode = "M",
    reporter_code: int = UKRAINE_REPORTER_CODE,
) -> tuple[FlowsResponse, list[str], list[str]]:
    """Sum a rolling window of monthly flows into one response.

    Twelve months rather than a calendar year, because the point is currency: a
    window ending at the reporting frontier is up to a year fresher than the
    latest complete annual figure, and it still covers a full seasonal cycle so
    shares are not distorted by which months happen to be included.

    A month with no records is skipped and named. That is not the same as a
    failed month: the source genuinely publishes nothing for some periods, and
    treating the gap as a zero would understate every partner in the window.

    Returns:
        The summed response, the periods that contributed, and the periods that
        were empty -- both lists travel onward so the caller can disclose them.
    """
    periods = months_ending(end_period, months)
    totals: dict[int, dict[str, Any]] = {}
    world = 0.0
    raw_rows = duplicates = 0
    truncated = False
    covered: list[str] = []
    empty: list[str] = []
    last_fetch: FetchResult | None = None

    for period in periods:
        response = fetch_monthly_flows(
            hs_code=hs_code, period=period, flow=flow, reporter_code=reporter_code
        )
        last_fetch = response.fetch
        raw_rows += response.raw_row_count
        duplicates += response.duplicates_dropped
        truncated = truncated or response.truncated
        if not response.records:
            empty.append(period)
            continue
        covered.append(period)
        world += response.world_total_value_usd or 0.0
        for record in response.records:
            bucket = totals.setdefault(
                record.partner_code,
                {"value": 0.0, "weight": 0.0, "weight_seen": False, "hs": record.hs_code},
            )
            bucket["value"] += record.value_usd
            if record.net_weight_kg is not None:
                bucket["weight"] += record.net_weight_kg
                bucket["weight_seen"] = True

    if last_fetch is None:  # pragma: no cover - months >= 1 always fetches
        raise UpstreamError("INVALID_ARGUMENT", "A trailing window needs at least one month.")

    label = f"{covered[0]}-{covered[-1]}" if covered else end_period
    records = [
        TradeRecord(
            partner_code=code,
            hs_code=bucket["hs"],
            period=label,
            # Weight is summed only where it was reported. A partner reporting
            # weight in some months and not others would otherwise get a unit
            # value computed from a full-window value over a partial weight.
            net_weight_kg=bucket["weight"] if bucket["weight_seen"] else None,
            value_usd=bucket["value"],
            quantity=None,
            quantity_unit_code=None,
        )
        for code, bucket in totals.items()
    ]
    records.sort(key=lambda r: r.value_usd, reverse=True)

    return (
        FlowsResponse(
            records=records,
            world_total_value_usd=world or None,
            raw_row_count=raw_rows,
            duplicates_dropped=duplicates,
            truncated=truncated,
            fetch=last_fetch,
        ),
        covered,
        empty,
    )


def latest_reported_month(
    *, probe_hs_code: str = "0806", start: str | None = None, look_back: int = 30
) -> str | None:
    """Find the most recent month Ukraine has actually reported.

    Walks backwards from ``start`` and stops at the first month with records.
    Hardcoding the frontier would silently rot -- the whole reason this exists is
    that the frontier moves, and moving it is the point of using monthly data.
    """
    from datetime import date

    if start is None:
        today = date.today()
        start = f"{today.year:04d}{today.month:02d}"

    for period in reversed(months_ending(start, look_back)):
        try:
            response = fetch_monthly_flows(hs_code=probe_hs_code, period=period)
        except Exception:  # noqa: BLE001 - a probe failure must not break a caller
            return None
        if response.records:
            return period
    return None


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
