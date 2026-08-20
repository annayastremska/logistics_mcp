"""Regression cover for two transport defects that had none.

Both were found late, both were silent, and both had the same shape: an absent
thing became a present-but-wrong thing. Neither could have been caught by the
domain tests, because neither is arithmetic — they live in the one function
where the network is allowed to happen.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from mcp_server.sources import http, wits
from mcp_server.sources.http import SourceMode, UpstreamError


@pytest.fixture
def isolated_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Point the fixture and cache directories at a scratch location.

    The module resolves both from the environment at import time, so they are
    patched as attributes rather than as environment variables.
    """
    fixtures, cache = tmp_path / "fixtures", tmp_path / "cache"
    fixtures.mkdir()
    cache.mkdir()
    monkeypatch.setattr(http, "FIXTURE_DIR", fixtures)
    monkeypatch.setattr(http, "CACHE_DIR", cache)
    return fixtures, cache


def _seed_cache(cache: Path, url: str, payload: dict) -> Path:
    """Write a fresh cache entry for ``url``, as a previous live call would have."""
    path = cache / http._fixture_name(url)
    http._write_envelope(path, url, payload, "2026-08-20T00:00:00+00:00")
    return path


# --------------------------------------------------------------------------- #
# A cache hit must still produce a fixture
# --------------------------------------------------------------------------- #


def test_recording_writes_a_fixture_even_when_the_cache_is_warm(
    isolated_dirs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The defect: the cache-hit branch returned before writing the fixture.

    Anything already cached was therefore missing from the recorded set, and a
    recording run reported success. This is how the most-exercised value in the
    whole project -- the grape tariff -- ended up with no fixture at all, and why
    offline then reported 0 percent duty where live reported 10.
    """
    fixtures, cache = isolated_dirs
    url = "https://example.invalid/warm?a=1"
    _seed_cache(cache, url, {"value": 42})
    monkeypatch.setenv("SOURCING_MODE", SourceMode.RECORD)

    # If this reaches the network the test environment has no route to it, so a
    # passing run also proves the cache was genuinely used rather than bypassed.
    def _no_network(*_args, **_kwargs):
        raise AssertionError("a warm cache hit must not re-fetch")

    monkeypatch.setattr(http, "_live_get", _no_network)

    result = http.fetch_json(url)
    assert result.payload == {"value": 42}

    fixture = fixtures / http._fixture_name(url)
    assert fixture.exists(), "a recording run left the fixture set incomplete"

    envelope = json.loads(fixture.read_text(encoding="utf-8"))
    assert envelope["url"] == url
    assert envelope["payload"] == {"value": 42}
    assert envelope["retrieved_at"], "provenance must survive the cache round trip"


def test_live_mode_does_not_write_fixtures(
    isolated_dirs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The converse guard: only a recording run may add to the recorded set.

    Without this, the fix above would be free to turn every ordinary run into a
    recording run and quietly rewrite fixtures under a passing test suite.
    """
    fixtures, cache = isolated_dirs
    url = "https://example.invalid/live?a=1"
    _seed_cache(cache, url, {"value": 7})
    monkeypatch.setenv("SOURCING_MODE", SourceMode.LIVE)

    http.fetch_json(url)
    assert not (fixtures / http._fixture_name(url)).exists()


def test_replay_refuses_a_request_it_has_no_recording_of(
    isolated_dirs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Offline must refuse, never default. A default here is an invented answer."""
    monkeypatch.setenv("SOURCING_MODE", SourceMode.REPLAY)

    with pytest.raises(UpstreamError) as raised:
        http.fetch_json("https://example.invalid/never-recorded")
    assert raised.value.code == "FIXTURE_MISSING"


def test_a_stale_cache_entry_is_not_served(
    isolated_dirs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Expiry has to be enforced, or the cache becomes an undated fixture set."""
    _fixtures, cache = isolated_dirs
    url = "https://example.invalid/stale?a=1"
    path = _seed_cache(cache, url, {"value": 1})

    # Age the entry past the configured lifetime.
    stale = time.time() - (http.CACHE_TTL_SECONDS + 60)
    import os as _os

    _os.utime(path, (stale, stale))
    monkeypatch.setenv("SOURCING_MODE", SourceMode.LIVE)
    monkeypatch.setattr(http, "_live_get", lambda *a, **k: {"value": "refetched"})

    assert http.fetch_json(url).payload == {"value": "refetched"}


# --------------------------------------------------------------------------- #
# A missing recording for one year must not abort the tariff fallback chain
# --------------------------------------------------------------------------- #


def test_tariff_fallback_skips_a_year_with_no_recording(monkeypatch: pytest.MonkeyPatch) -> None:
    """The defect: the chain died on the first missing fixture.

    The source holds no observation for the current year and answers 404, so no
    fixture is ever recorded for it. Offline, that absence has to mean "try the
    next year" -- exactly as a live 404 does -- or replay reports no duty at all
    where live reports the real rate.
    """
    calls: list[int] = []

    def fake_fetch(hs6: str, year: int) -> wits.TariffResponse:
        calls.append(year)
        if year == 2024:
            raise UpstreamError("FIXTURE_MISSING", "no recording for 2024")
        return wits.TariffResponse(
            rate=wits.TariffRate(reporter="804", hs6=hs6, year=year, rate_pct=10.0),
            fetch=http.FetchResult({}, SourceMode.REPLAY, "", ""),
        )

    monkeypatch.setattr(wits, "fetch_mfn_rate", fake_fetch)

    response = wits.fetch_mfn_rate_with_fallback("080610", 2024)
    assert response.rate is not None
    assert response.rate.rate_pct == 10.0
    assert response.rate.year == 2023, "the year actually used must travel with the rate"
    assert calls[:2] == [2024, 2023], "the preferred year is tried first, then the fallback"


def test_tariff_fallback_raises_when_no_year_has_a_recording(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An entirely missing recording set is a different problem from a source gap.

    Silently returning "no rate" here would hand the caller a zero duty and a
    clean status, which is the failure mode the whole rule exists to prevent.
    """

    def always_missing(hs6: str, year: int) -> wits.TariffResponse:
        raise UpstreamError("FIXTURE_MISSING", f"no recording for {year}")

    monkeypatch.setattr(wits, "fetch_mfn_rate", always_missing)

    with pytest.raises(UpstreamError) as raised:
        wits.fetch_mfn_rate_with_fallback("080610", 2024)
    assert raised.value.code == "FIXTURE_MISSING"
    assert "2024" in str(raised.value)


def test_a_transient_failure_on_one_year_does_not_abort_the_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """This one cost a live run its duty figures.

    WITS answers 404 for the current year, so every lookup walks back through
    older years. The chain used to re-raise anything that was not a missing
    fixture, so a single timeout on the first year ended it -- while the older
    year sat in the HTTP cache, one call away. Four of eight origins in one
    ranking went down the "duty unknown" path for no reason, and because the
    rate does not depend on the origin, the same table carried two different
    duty assumptions.
    """
    calls: list[int] = []

    def flaky(hs6: str, year: int) -> wits.TariffResponse:
        calls.append(year)
        if year == 2024:
            raise UpstreamError("TIMEOUT", "read timed out")
        return wits.TariffResponse(
            rate=wits.TariffRate(reporter=804, hs6=hs6, year=year, rate_pct=10.0),
            fetch=http.FetchResult({}, SourceMode.LIVE, "", ""),
        )

    monkeypatch.setattr(wits, "fetch_mfn_rate", flaky)

    response = wits.fetch_mfn_rate_with_fallback("080610", 2024)
    assert response.rate is not None
    assert response.rate.rate_pct == 10.0
    assert response.rate.year == 2023
    assert calls[:2] == [2024, 2023], "the failed year must be followed by the next one"


def test_a_chain_that_fails_everywhere_raises_and_names_every_year(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Skipping a bad year must not turn into swallowing an outage.

    When no year answered at all, the caller has to hear about it -- and the
    error must say a transport failure happened rather than blaming the fixture
    set, because the two have different remedies.
    """

    def rate_limited(hs6: str, year: int) -> wits.TariffResponse:
        raise UpstreamError("RATE_LIMITED", "slow down")

    monkeypatch.setattr(wits, "fetch_mfn_rate", rate_limited)

    with pytest.raises(UpstreamError) as raised:
        wits.fetch_mfn_rate_with_fallback("080610", 2024)
    assert raised.value.code == "UPSTREAM_UNAVAILABLE"
    message = str(raised.value)
    for year in ("2024", "2023", "2022", "2021"):
        assert year in message, "every year attempted must be accounted for"
    assert "RATE_LIMITED" in message


def test_an_unestablished_duty_is_reported_as_unknown_not_as_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed lookup used to arrive as 0.0 and score as the best possible duty.

    So not knowing the rate *flattered* the candidate -- the exact confusion
    between "empty" and "good" that the status convention exists to prevent. The
    total is still computed with no duty, and now says it is a lower bound.
    """
    monkeypatch.setenv("SOURCING_MODE", "replay")

    from mcp_server.server import estimate_landed_cost

    def unavailable(hs6: str, year: int, **kwargs: object) -> wits.TariffResponse:
        raise UpstreamError("UPSTREAM_UNAVAILABLE", "WITS unreachable")

    monkeypatch.setattr(
        "mcp_server.server.wits.fetch_mfn_rate_with_fallback", unavailable
    )

    result = estimate_landed_cost(
        hs_code="080610", origin_iso3="TUR", volume_kg=120_000.0, year=2024
    )
    assert result.status == "ok", "a missing duty must not discard a usable cost"
    assert result.duty_rate_pct is None, "unknown must not arrive as the number zero"
    assert result.confidence == "low"
    # The specific sentence the result must carry, not merely the word "unknown"
    # somewhere: an earlier version of this assertion passed on a different
    # branch's wording and let the new one be deleted without a failure.
    assert any("read as a duty-free origin" in a for a in result.assumptions)
    assert any("lower bound" in a for a in result.assumptions)
