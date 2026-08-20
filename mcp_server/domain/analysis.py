"""Concentration, volatility, mirror-gap and composite scoring.

Thresholds are stated as named constants rather than buried in comparisons, so a
reader can see the bar each risk flag is measured against and argue with it.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

# HHI thresholds. Competition authorities use these for market concentration;
# they are borrowed here as a supply-dependency proxy, which is a deliberate
# analogy, not an established supply-chain standard.
HHI_HIGH = 2500.0
HHI_MODERATE = 1500.0

# A single origin above this share is treated as a dependency.
SINGLE_SOURCE_SHARE_PCT = 70.0

# Year-over-year swing above this is treated as volatile supply.
VOLATILITY_PCT = 35.0

# Mirror gaps are asymmetric, and treating them symmetrically flags the normal case
# as an anomaly. Imports are valued CIF (freight and insurance included) and exports
# FOB, so partners systematically report *less* than the importer: a moderately
# negative gap is the expected reading, not a warning sign.
#
# Suspicious in either direction:
#   gap > +MIRROR_GAP_OVER_PCT   partners report materially MORE than Ukraine recorded
#                               as arriving, which points at under-recorded imports.
#   gap < -MIRROR_GAP_UNDER_PCT  a shortfall far larger than valuation alone explains.
MIRROR_GAP_OVER_PCT = 25.0
MIRROR_GAP_UNDER_PCT = 50.0
# Kept for display: the band within which a negative gap needs no explanation.
MIRROR_GAP_NORMAL_PCT = 25.0


def mirror_gap_is_suspicious(gap_pct: float | None) -> bool:
    """True when a mirror gap cannot be explained by CIF-versus-FOB valuation alone."""
    if gap_pct is None:
        return False
    return gap_pct > MIRROR_GAP_OVER_PCT or gap_pct < -MIRROR_GAP_UNDER_PCT

# Below this many origins the statistics are too thin to lean on.
THIN_DATA_PARTNER_COUNT = 3


@dataclass(frozen=True)
class ConcentrationStats:
    hhi: float
    effective_partner_count: float
    top_share_pct: float
    partner_count: int


def herfindahl(values: list[float]) -> ConcentrationStats | None:
    """Compute HHI over a list of positive values (0..10000 scale)."""
    positive = [v for v in values if v and v > 0]
    total = sum(positive)
    if not positive or total <= 0:
        return None
    shares = [v / total * 100.0 for v in positive]
    hhi = sum(s * s for s in shares)
    return ConcentrationStats(
        hhi=round(hhi, 1),
        effective_partner_count=round(10000.0 / hhi, 2) if hhi else 0.0,
        top_share_pct=round(max(shares), 2),
        partner_count=len(positive),
    )


def yoy_volatility_pct(totals_by_year: list[tuple[int, float]]) -> float | None:
    """Standard deviation of year-over-year percentage change in a series.

    Needs at least three years, since two years give a single change and a
    standard deviation of zero, which would read as "perfectly stable".
    """
    ordered = [value for _, value in sorted(totals_by_year)]
    if len(ordered) < 3:
        return None
    changes: list[float] = []
    for previous, current in zip(ordered, ordered[1:]):
        if previous <= 0:
            continue
        changes.append((current - previous) / previous * 100.0)
    if len(changes) < 2:
        return None
    return round(statistics.stdev(changes), 2)


def mirror_gap_pct(importer_reported_usd: float, partner_reported_usd: float) -> float | None:
    """Relative gap between exporter-reported and importer-reported value."""
    if importer_reported_usd <= 0:
        return None
    return round((partner_reported_usd - importer_reported_usd) / importer_reported_usd * 100.0, 2)


def min_max_normalize(values: dict[str, float | None], *, higher_is_better: bool) -> dict[str, float | None]:
    """Scale values to 0..1 where 1 is always the better outcome.

    A criterion where every candidate scores the same carries no information, so
    each candidate is given 0.5 rather than an arbitrary 0 or 1.
    """
    present = {k: v for k, v in values.items() if v is not None}
    if not present:
        return {k: None for k in values}

    low, high = min(present.values()), max(present.values())
    span = high - low
    out: dict[str, float | None] = {}
    for key in values:
        raw = values.get(key)
        if raw is None:
            out[key] = None
        elif span == 0:
            out[key] = 0.5
        else:
            scaled = (raw - low) / span
            out[key] = round(scaled if higher_is_better else 1.0 - scaled, 4)
    return out
