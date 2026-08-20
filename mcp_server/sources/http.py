"""Transport layer for the three open data APIs.

Three responsibilities, deliberately kept out of the parsing code above it:

1. **Rate limiting.** UN Comtrade's free endpoint rejects a second request inside
   the same second with HTTP 429, so every host gets a token-bucket throttle and
   429 responses are retried with backoff.
2. **Caching.** WITS is slow and occasionally times out; repeated calls inside a
   run are served from an on-disk cache.
3. **Fixture record/replay.** In ``replay`` mode responses come from
   ``fixtures/`` instead of the network.

The fixture substitution happens **here, at the transport boundary**: replay
returns the same raw JSON the network returned, and every parser, deduplication
step and calculation above runs unchanged. There is no branch anywhere that
short-circuits to a prepared answer.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# WITS rejects the default python-urllib User-Agent with HTTP 403.
USER_AGENT = "Mozilla/5.0 (compatible; import-sourcing-advisor/1.0)"

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = Path(os.environ.get("SOURCING_FIXTURE_DIR", REPO_ROOT / "fixtures"))
CACHE_DIR = Path(os.environ.get("SOURCING_CACHE_DIR", REPO_ROOT / ".cache"))
CACHE_TTL_SECONDS = int(os.environ.get("SOURCING_CACHE_TTL", 24 * 3600))


class SourceMode:
    LIVE = "live"
    RECORD = "record"
    REPLAY = "replay"


def current_mode() -> str:
    """Resolve the transport mode from the environment.

    ``SOURCING_MODE`` is authoritative; ``REPLAY=1`` is accepted as a shorthand
    so the documented demo command stays short.
    """
    mode = os.environ.get("SOURCING_MODE", "").strip().lower()
    if mode in {SourceMode.LIVE, SourceMode.RECORD, SourceMode.REPLAY}:
        return mode
    if os.environ.get("REPLAY", "").strip() in {"1", "true", "yes"}:
        return SourceMode.REPLAY
    return SourceMode.LIVE


class UpstreamError(RuntimeError):
    """A transport-level failure that the tool layer turns into a structured error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class FetchResult:
    """A decoded upstream response plus where it came from."""

    payload: Any
    mode: str
    retrieved_at: str
    url: str


class _RateLimiter:
    """Minimum-interval throttle, one bucket per host."""

    def __init__(self) -> None:
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, host: str, min_interval: float) -> None:
        with self._lock:
            now = time.monotonic()
            earliest = self._last.get(host, 0.0) + min_interval
            if now < earliest:
                time.sleep(earliest - now)
            self._last[host] = max(now, earliest)


_RATE_LIMITER = _RateLimiter()

# UN Comtrade's free preview endpoint allows roughly one request per second.
_MIN_INTERVAL_BY_HOST = {
    "comtradeapi.un.org": 1.1,
    "wits.worldbank.org": 0.5,
    "api.worldbank.org": 0.2,
}


def _fixture_name(url: str) -> str:
    """Build a readable, collision-free fixture filename for a URL."""
    parsed = urllib.parse.urlsplit(url)
    host = parsed.netloc.split(".")[0]
    parts = [p for p in parsed.path.split("/") if p and p not in {"v1", "public", "preview", "API"}]
    query = urllib.parse.parse_qsl(parsed.query)
    query_bits = [f"{k}-{v}" for k, v in sorted(query)]
    slug = "_".join([host, *parts[-4:], *query_bits])
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", slug)[:120].strip("-_")
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
    return f"{slug}__{digest}.json"


def _read_envelope(path: Path) -> FetchResult:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "payload" not in raw:
        raise UpstreamError(
            "UPSTREAM_MALFORMED", f"Fixture {path.name} is not a recorded-response envelope."
        )
    return FetchResult(
        payload=raw["payload"],
        mode=SourceMode.REPLAY,
        retrieved_at=raw.get("retrieved_at", ""),
        url=raw.get("url", ""),
    )


def _write_envelope(path: Path, url: str, payload: Any, retrieved_at: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    envelope = {
        "url": url,
        "retrieved_at": retrieved_at,
        "note": "Genuine upstream response, recorded verbatim. Do not hand-edit.",
        "payload": payload,
    }
    path.write_text(json.dumps(envelope, ensure_ascii=False, indent=1), encoding="utf-8")


def _live_get(url: str, timeout: float) -> Any:
    """Perform one throttled GET with 429 retry, returning decoded JSON."""
    host = urllib.parse.urlsplit(url).netloc
    min_interval = _MIN_INTERVAL_BY_HOST.get(host, 0.5)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    backoff = 2.0
    last_error: str = ""
    for attempt in range(4):
        _RATE_LIMITER.wait(host, min_interval)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read()
            try:
                return json.loads(body)
            except json.JSONDecodeError as exc:
                raise UpstreamError(
                    "UPSTREAM_MALFORMED", f"{host} returned a non-JSON body: {exc}"
                ) from exc
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                last_error = f"{host} rate-limited the request (HTTP 429)."
                time.sleep(backoff)
                backoff *= 2
                continue
            if exc.code == 404:
                # For these APIs a 404 means "no observation for that key", which is
                # a legitimate empty answer rather than a broken server.
                raise UpstreamError(
                    "NOT_FOUND", f"{host} has no record for {url} (HTTP 404)."
                ) from exc
            raise UpstreamError(
                "UPSTREAM_UNAVAILABLE", f"{host} returned HTTP {exc.code} for {url}."
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = f"{host} was unreachable: {exc}"
            if attempt == 3:
                break
            time.sleep(backoff)
            backoff *= 2

    raise UpstreamError("RATE_LIMITED" if "429" in last_error else "UPSTREAM_UNAVAILABLE", last_error)


def fetch_json(url: str, *, timeout: float = 45.0) -> FetchResult:
    """Fetch and decode JSON, honouring the configured transport mode.

    Raises:
        UpstreamError: on rate limiting, unreachable hosts, malformed bodies, or a
            missing fixture in replay mode.
    """
    mode = current_mode()
    fixture_path = FIXTURE_DIR / _fixture_name(url)

    if mode == SourceMode.REPLAY:
        if not fixture_path.exists():
            raise UpstreamError(
                "FIXTURE_MISSING",
                (
                    f"Replay mode is on but no fixture exists for {url}. "
                    f"Expected {fixture_path.name}. Re-record with SOURCING_MODE=record."
                ),
            )
        return _read_envelope(fixture_path)

    cache_path = CACHE_DIR / _fixture_name(url)
    if cache_path.exists() and time.time() - cache_path.stat().st_mtime < CACHE_TTL_SECONDS:
        cached = _read_envelope(cache_path)
        if mode == SourceMode.RECORD and not fixture_path.exists():
            # A cache hit must still produce a fixture. Returning here without
            # writing one is how a recording run on a warm cache yields an
            # incomplete fixture set, and replay then quietly disagrees with
            # live -- a missing tariff fixture reads as 0 percent duty.
            _write_envelope(fixture_path, url, cached.payload, cached.retrieved_at)
        return FetchResult(cached.payload, SourceMode.LIVE, cached.retrieved_at, url)

    payload = _live_get(url, timeout)
    retrieved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _write_envelope(cache_path, url, payload, retrieved_at)
    if mode == SourceMode.RECORD:
        _write_envelope(fixture_path, url, payload, retrieved_at)

    return FetchResult(payload, SourceMode.LIVE, retrieved_at, url)


def build_url(base: str, params: dict[str, Any]) -> str:
    """Join a base URL with query parameters in a stable order.

    Sorting matters: the fixture and cache keys are derived from the URL, so an
    unstable parameter order would fragment both.
    """
    clean = {k: v for k, v in params.items() if v is not None}
    query = urllib.parse.urlencode(sorted(clean.items()), safe=",")
    return f"{base}?{query}" if query else base
