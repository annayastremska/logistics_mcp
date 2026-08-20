"""Offline reference data: the HS2022 nomenclature, country codes and centroids.

The Comtrade preview endpoint returns numeric codes only -- every descriptive
field (``reporterDesc``, ``partnerDesc``, ``cmdDesc``) comes back ``null``. These
vendored reference files are what turn those codes back into names, and they let
``validate_sourcing_brief`` check an HS code and resolve a product name without
spending an API call.

Files live in ``data/reference/`` and are the official Comtrade reference
downloads, unmodified.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

REFERENCE_DIR = Path(__file__).resolve().parents[2] / "data" / "reference"

UKRAINE_REPORTER_CODE = 804
UKRAINE_ISO3 = "UKR"

# Countries in the EU customs union: the DCFTA means the MFN rate WITS publishes
# is very likely not the rate actually paid. Used only to raise a flag.
_EU_MEMBER_ISO3 = {
    "AUT", "BEL", "BGR", "HRV", "CYP", "CZE", "DNK", "EST", "FIN", "FRA", "DEU",
    "GRC", "HUN", "IRL", "ITA", "LVA", "LTU", "LUX", "MLT", "NLD", "POL", "PRT",
    "ROU", "SVK", "SVN", "ESP", "SWE",
}
# Other partners with a free-trade agreement in force with Ukraine.
_FTA_PARTNERS_ISO3 = {"GBR", "CAN", "ISR", "TUR", "MKD", "MNE", "GEO", "MDA", "CHE", "NOR", "ISL"}


class HsEntry(NamedTuple):
    """One node of the HS2022 nomenclature."""

    code: str
    description: str
    level: int
    is_leaf: bool
    unit: str | None


class CountryEntry(NamedTuple):
    """One Comtrade area: a real country or a reporting aggregate."""

    code: int
    iso3: str
    name: str
    is_group: bool


def _load(filename: str) -> dict:
    path = REFERENCE_DIR / filename
    if not path.exists():
        raise FileNotFoundError(
            f"Missing reference file {path}. Run scripts/fetch_reference_data.py to vendor it."
        )
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _clean_description(code: str, text: str) -> str:
    """Strip the leading ``"<code> - "`` that Comtrade prefixes onto descriptions."""
    return re.sub(rf"^{re.escape(code)}\s*-\s*", "", text).strip()


@lru_cache(maxsize=1)
def hs_index() -> dict[str, HsEntry]:
    """HS2022 code -> entry, for all 6,900+ nodes."""
    index: dict[str, HsEntry] = {}
    for row in _load("H6.json")["results"]:
        code = str(row["id"])
        if not code.isdigit():
            continue  # skips the synthetic "TOTAL" node
        index[code] = HsEntry(
            code=code,
            description=_clean_description(code, row.get("text", "")),
            level=int(row.get("aggrlevel") or len(code)),
            is_leaf=str(row.get("isLeaf")) == "1",
            unit=(row.get("standardUnitAbbr") or None) if row.get("standardUnitAbbr") != "n/a" else None,
        )
    return index


@lru_cache(maxsize=1)
def partner_index() -> dict[int, CountryEntry]:
    """Comtrade partner code -> entry, aggregates included and flagged."""
    index: dict[int, CountryEntry] = {}
    for row in _load("partnerAreas.json")["results"]:
        try:
            code = int(row["PartnerCode"])
        except (TypeError, ValueError):
            continue
        index[code] = CountryEntry(
            code=code,
            iso3=(row.get("PartnerCodeIsoAlpha3") or "").strip(),
            name=(row.get("PartnerDesc") or "").strip(),
            is_group=bool(row.get("isGroup")),
        )
    return index


@lru_cache(maxsize=1)
def _iso3_to_partner() -> dict[str, CountryEntry]:
    out: dict[str, CountryEntry] = {}
    for entry in partner_index().values():
        if entry.iso3 and not entry.iso3.startswith("_") and not entry.is_group:
            out.setdefault(entry.iso3.upper(), entry)
    return out


def _fold_name(name: str) -> str:
    """Case- and diacritic-insensitive key for country-name matching.

    The reference table spells several countries with diacritics -- "Türkiye",
    "Côte d'Ivoire", "Curaçao" -- while callers and models overwhelmingly type the
    plain-ASCII form. Stripping combining marks makes both spellings resolve.
    """
    decomposed = unicodedata.normalize("NFKD", name)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return stripped.casefold().strip()


@lru_cache(maxsize=1)
def _name_to_partner() -> dict[str, CountryEntry]:
    return {_fold_name(e.name): e for e in _iso3_to_partner().values()}


@lru_cache(maxsize=1)
def centroids() -> dict[str, dict]:
    """ISO3 -> {name, lat, lon} for the freight-distance model."""
    return _load("country_centroids.json")["countries"]


# --------------------------------------------------------------------------- #
# Lookups used by the tools
# --------------------------------------------------------------------------- #


def lookup_hs(code: str) -> HsEntry | None:
    """Return the HS2022 entry for a 2, 4 or 6 digit code, or None if unknown."""
    return hs_index().get(code.strip())


def search_hs(query: str, *, limit: int = 8, levels: tuple[int, ...] = (4, 6)) -> list[HsEntry]:
    """Find HS entries whose description contains every word of the query.

    Ranked shortest-description-first, which favours the general heading over a
    long, narrowly-worded subheading.
    """
    words = [w for w in re.split(r"\W+", query.casefold()) if len(w) > 2]
    if not words:
        return []
    hits = [
        entry
        for entry in hs_index().values()
        if entry.level in levels and all(w in entry.description.casefold() for w in words)
    ]
    hits.sort(key=lambda e: (len(e.description), e.code))
    return hits[:limit]


def resolve_country(token: str) -> CountryEntry | None:
    """Resolve an ISO3 code or a country name to a Comtrade partner entry."""
    token = token.strip()
    if not token:
        return None
    by_iso = _iso3_to_partner().get(token.upper())
    if by_iso:
        return by_iso
    return _name_to_partner().get(_fold_name(token))


def partner_name(code: int) -> str:
    entry = partner_index().get(code)
    return entry.name if entry else f"partner {code}"


def partner_iso3(code: int) -> str:
    entry = partner_index().get(code)
    return entry.iso3 if entry and entry.iso3 else f"#{code}"


def is_aggregate_partner(code: int) -> bool:
    """True for reporting aggregates such as 'World' or 'Africa CAMEU region, nes'.

    These must be excluded before computing shares, or every share is halved.
    """
    if code == 0:
        return True
    entry = partner_index().get(code)
    return bool(entry and (entry.is_group or entry.iso3.startswith("_")))


def fta_preference_possible(iso3: str) -> bool:
    """True when a trade agreement plausibly undercuts the published MFN duty."""
    iso3 = iso3.upper()
    return iso3 in _EU_MEMBER_ISO3 or iso3 in _FTA_PARTNERS_ISO3


def great_circle_km(origin_iso3: str, destination_iso3: str = UKRAINE_ISO3) -> float | None:
    """Great-circle distance between two countries' reference points, in km."""
    table = centroids()
    a = table.get(origin_iso3.upper())
    b = table.get(destination_iso3.upper())
    if not a or not b:
        return None
    lat1, lon1, lat2, lon2 = map(math.radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return round(2 * 6371.0088 * math.asin(math.sqrt(h)), 1)
