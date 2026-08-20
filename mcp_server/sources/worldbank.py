"""World Bank Indicators API: logistics performance and trade context.

No authentication. The response shape is ``[metadata, [rows]]`` and rows carry
``value: null`` for years with no observation, so nulls are filtered here rather
than leaking into the scoring code.

The Logistics Performance Index is **not** an annual series -- 2022 is the latest
observation for every country tested. It is therefore treated as a structural
constant and always reported with its ``as_of`` year attached.
"""

from __future__ import annotations

from dataclasses import dataclass

from .http import FetchResult, UpstreamError, build_url, fetch_json

BASE = "https://api.worldbank.org/v2"

INDICATORS = {
    "lpi_overall": "LP.LPI.OVRL.XQ",
    "lpi_customs": "LP.LPI.CUST.XQ",
    "lpi_infrastructure": "LP.LPI.INFR.XQ",
    "lpi_timeliness": "LP.LPI.TIME.XQ",
    "lpi_tracking": "LP.LPI.TRAC.XQ",
    "container_port_teu": "IS.SHP.GOOD.TU",
    "tariff_simple_mean_pct": "TM.TAX.MRCH.SM.AR.ZS",
}


@dataclass(frozen=True)
class Observation:
    """One indicator value for one country, with the year it describes."""

    iso3: str
    value: float
    year: str


@dataclass(frozen=True)
class IndicatorResponse:
    observations: dict[str, Observation]
    indicator_code: str
    fetch: FetchResult


def fetch_indicator(
    indicator: str, iso3_codes: list[str], *, date_range: str = "2010:2025"
) -> IndicatorResponse:
    """Fetch the latest non-null observation per country for one indicator.

    Args:
        indicator: Either a key of ``INDICATORS`` or a raw World Bank code.
        iso3_codes: Countries to fetch, ISO3.
        date_range: World Bank ``date`` range; the latest value in it wins.

    Raises:
        UpstreamError: on transport failure or an unexpected response shape.
    """
    code = INDICATORS.get(indicator, indicator)
    if not iso3_codes:
        return IndicatorResponse({}, code, FetchResult(None, "live", "", ""))

    countries = ";".join(sorted({c.upper() for c in iso3_codes}))
    url = build_url(
        f"{BASE}/country/{countries}/indicator/{code}",
        {"date": date_range, "format": "json", "per_page": 500},
    )
    fetch = fetch_json(url, timeout=30.0)

    payload = fetch.payload
    if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[1], list):
        raise UpstreamError(
            "UPSTREAM_MALFORMED",
            f"World Bank returned an unexpected shape for {code}: {type(payload).__name__}.",
        )

    latest: dict[str, Observation] = {}
    for row in payload[1]:
        if not isinstance(row, dict) or row.get("value") is None:
            continue
        iso3 = (row.get("countryiso3code") or "").upper()
        year = str(row.get("date") or "")
        if not iso3 or not year:
            continue
        existing = latest.get(iso3)
        if existing is None or year > existing.year:
            latest[iso3] = Observation(iso3=iso3, value=float(row["value"]), year=year)

    return IndicatorResponse(observations=latest, indicator_code=code, fetch=fetch)
