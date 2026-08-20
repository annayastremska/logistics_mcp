"""WITS TRAINS: applied import tariff rates, via the SDMX-JSON endpoint.

No authentication, but three verified quirks shape this module:

* The default ``python-urllib`` User-Agent is rejected with HTTP 403; the
  transport layer sends a browser User-Agent for every request.
* Responses are slow and occasionally time out, so results are cached.
* **Only most-favoured-nation rates are available.** Requesting a preferential
  rate for a specific partner (EU, China, Turkiye were all tested) returns HTTP
  404. Any rate returned here is therefore an MFN rate, and a free-trade
  agreement may mean a lower rate is actually paid.

The rate is buried inside an SDMX-JSON observation array rather than exposed as a
plain field, hence the dedicated parser.
"""

from __future__ import annotations

from dataclasses import dataclass

from .http import FetchResult, UpstreamError, build_url, fetch_json

BASE = "https://wits.worldbank.org/API/V1/SDMX/V21/datasource/TRN"
UKRAINE_REPORTER = "804"
MFN_PARTNER = "000"


@dataclass(frozen=True)
class TariffRate:
    """One applied MFN duty rate."""

    reporter: str
    hs6: str
    year: int
    rate_pct: float
    basis: str = "MFN"


@dataclass(frozen=True)
class TariffResponse:
    rate: TariffRate | None
    fetch: FetchResult


def _extract_first_observation(payload: object) -> float | None:
    """Pull the first observation value out of an SDMX-JSON message."""
    if not isinstance(payload, dict):
        return None
    datasets = payload.get("dataSets")
    if not isinstance(datasets, list) or not datasets:
        return None
    series = datasets[0].get("series") if isinstance(datasets[0], dict) else None
    if not isinstance(series, dict):
        return None
    for entry in series.values():
        observations = entry.get("observations") if isinstance(entry, dict) else None
        if not isinstance(observations, dict):
            continue
        for values in observations.values():
            if isinstance(values, list) and values and values[0] is not None:
                try:
                    return float(values[0])
                except (TypeError, ValueError):
                    continue
    return None


def fetch_mfn_rate(hs6: str, year: int, *, reporter: str = UKRAINE_REPORTER) -> TariffResponse:
    """Fetch the applied MFN duty rate for one HS6 code and year.

    A missing rate is returned as ``rate=None`` -- the source genuinely has no
    observation for that combination, which is different from a failed call.

    Raises:
        UpstreamError: on transport failure or a non-SDMX body.
    """
    hs6 = hs6.strip()
    if len(hs6) != 6 or not hs6.isdigit():
        raise UpstreamError(
            "INVALID_ARGUMENT", f"WITS needs a 6-digit HS code; got {hs6!r}."
        )

    url = build_url(
        f"{BASE}/reporter/{reporter}/partner/{MFN_PARTNER}/product/{hs6}"
        f"/year/{year}/datatype/reported",
        {"format": "JSON"},
    )
    try:
        fetch = fetch_json(url, timeout=45.0)
    except UpstreamError as exc:
        if exc.code == "NOT_FOUND":
            # WITS answers 404 for a year it holds no observation for. That is an
            # empty result, not a failure, so the caller can try another year.
            return TariffResponse(rate=None, fetch=FetchResult(None, "live", "", url))
        raise
    value = _extract_first_observation(fetch.payload)
    if value is None:
        return TariffResponse(rate=None, fetch=fetch)
    return TariffResponse(
        rate=TariffRate(reporter=reporter, hs6=hs6, year=year, rate_pct=value), fetch=fetch
    )


def fetch_mfn_rate_with_fallback(
    hs6: str, preferred_year: int, *, fallback_years: tuple[int, ...] = (2023, 2022, 2021)
) -> TariffResponse:
    """Try the preferred year, then known-good years.

    Tariff schedules change rarely -- the grape rate was 10 percent in every year
    from 2018 to 2023 -- so an older observation is a sound stand-in, and the year
    actually used travels with the result.
    """
    years: list[int] = [preferred_year, *[y for y in fallback_years if y != preferred_year]]
    last: TariffResponse | None = None
    failures: list[str] = []

    for year in years:
        try:
            response = fetch_mfn_rate(hs6, year)
        except UpstreamError as exc:
            # No year is allowed to abort the chain. A missing fixture is a year
            # the recording run got a 404 for, and a timeout is a year the source
            # would not answer right now -- in both cases the next year may hold
            # the rate, and it is often already in the HTTP cache. Raising here
            # instead cost a real run its duty figures: a transient timeout on
            # the current year sent four of eight origins down the "0 percent
            # assumed" path while the cached older year sat unread.
            failures.append(f"{year}: {exc.code}")
            continue
        last = response
        if response.rate is not None:
            return response

    if last is None:
        # Nothing in the chain answered at all, so this is not a gap in the
        # source's coverage -- it is a failure to reach it, or an incomplete
        # fixture set. Say which, per year, instead of a silent "no rate".
        raise UpstreamError(
            "UPSTREAM_UNAVAILABLE" if any("FIXTURE_MISSING" not in f for f in failures) else "FIXTURE_MISSING",
            f"No WITS observation for HS {hs6} could be read in any of years "
            f"{', '.join(failures)}. If these are fixture gaps, re-record with SOURCING_MODE=record.",
        )
    return last
