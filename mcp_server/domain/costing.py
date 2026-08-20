"""Landed-cost build-up.

No open data source publishes freight rates, so the transport component is
**modelled** from distance and mode. Every modelled figure is labelled
``estimated`` in the output and every coefficient below is surfaced in the
result's ``assumptions`` list, so a reader can see exactly what was assumed and
substitute their own contracted rates.

The order of the build-up follows normal customs practice: goods value, then
freight and insurance to arrive at a CIF value, then duty assessed **on that CIF
value**, then domestic handling.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

TransportMode = Literal["sea", "road", "rail", "air"]

# USD per kg per 1000 km, plus a per-kg terminal/handling floor for the mode.
# Order-of-magnitude figures for comparing origins, not quotes.
_MODE_MODEL: dict[str, dict[str, float]] = {
    "sea": {"per_kg_per_1000km": 0.018, "handling_per_kg": 0.075, "days_per_1000km": 2.4, "fixed_days": 6},
    "rail": {"per_kg_per_1000km": 0.055, "handling_per_kg": 0.050, "days_per_1000km": 1.4, "fixed_days": 4},
    "road": {"per_kg_per_1000km": 0.095, "handling_per_kg": 0.030, "days_per_1000km": 1.0, "fixed_days": 2},
    "air": {"per_kg_per_1000km": 0.520, "handling_per_kg": 0.180, "days_per_1000km": 0.2, "fixed_days": 2},
}

# Share of goods value charged as cargo insurance.
_INSURANCE_RATE = 0.003
# Flat customs brokerage per consignment, USD.
_BROKERAGE_USD = 120.0


@dataclass(frozen=True)
class CostLine:
    label: str
    amount_usd: float
    basis: str
    measurement: Literal["measured", "estimated"]


@dataclass(frozen=True)
class LandedCost:
    lines: list[CostLine]
    total_usd: float
    cost_per_kg_usd: float
    cif_value_usd: float
    duty_amount_usd: float
    transit_days_estimate: int
    assumptions: list[str]


def supported_modes() -> tuple[str, ...]:
    return tuple(_MODE_MODEL)


def estimate_freight_usd(volume_kg: float, distance_km: float, mode: TransportMode) -> float:
    """Modelled door-to-door freight for a consignment."""
    model = _MODE_MODEL[mode]
    per_kg = model["handling_per_kg"] + model["per_kg_per_1000km"] * (distance_km / 1000.0)
    return round(per_kg * volume_kg, 2)


def estimate_transit_days(distance_km: float, mode: TransportMode) -> int:
    model = _MODE_MODEL[mode]
    return int(round(model["fixed_days"] + model["days_per_1000km"] * (distance_km / 1000.0)))


def build_landed_cost(
    *,
    volume_kg: float,
    unit_price_usd_per_kg: float,
    distance_km: float,
    mode: TransportMode,
    duty_rate_pct: float,
    unit_price_is_cif: bool = True,
) -> LandedCost:
    """Assemble the full landed-cost build-up for one origin.

    Args:
        volume_kg: Consignment weight in kilograms.
        unit_price_usd_per_kg: Goods price per kg. When derived from Comtrade
            import values this is already a CIF unit value, so freight is not
            added a second time to the duty base.
        distance_km: Great-circle distance from the origin.
        mode: Transport mode to model.
        duty_rate_pct: Applied MFN duty rate, percent.
        unit_price_is_cif: True when the unit price already includes freight and
            insurance to the border (the case for Comtrade import unit values).

    Returns:
        A ``LandedCost`` whose ``lines`` sum to ``total_usd``.
    """
    goods = round(unit_price_usd_per_kg * volume_kg, 2)
    freight = estimate_freight_usd(volume_kg, distance_km, mode)
    insurance = round(goods * _INSURANCE_RATE, 2)

    assumptions = [
        f"Freight modelled at {_MODE_MODEL[mode]['handling_per_kg']:.3f} USD/kg handling plus "
        f"{_MODE_MODEL[mode]['per_kg_per_1000km']:.3f} USD/kg per 1000 km over {distance_km:.0f} km by {mode}.",
        "No open data source publishes freight rates; this component is an order-of-magnitude "
        "model for comparing origins, not a quotation.",
        f"Cargo insurance assumed at {_INSURANCE_RATE * 100:.1f} percent of goods value.",
        f"Customs brokerage assumed flat at {_BROKERAGE_USD:.0f} USD per consignment.",
        "Distance is great-circle between country reference points, not routed transport distance.",
    ]

    lines = [CostLine("Goods value", goods, "unit value x volume", "measured")]

    if unit_price_is_cif:
        cif = goods
        assumptions.append(
            "The unit value comes from reported import statistics and is already CIF, so modelled "
            "freight is shown for reference and is not added to the duty base."
        )
        lines.append(
            CostLine("Freight (reference only, already inside the CIF unit value)", 0.0,
                     f"modelled {freight:.2f} USD, excluded to avoid double counting", "estimated")
        )
    else:
        cif = round(goods + freight + insurance, 2)
        lines.append(CostLine("Freight", freight, f"modelled for {mode}", "estimated"))
        lines.append(CostLine("Insurance", insurance, f"{_INSURANCE_RATE * 100:.1f}% of goods value", "estimated"))

    duty = round(cif * duty_rate_pct / 100.0, 2)
    lines.append(
        CostLine("Import duty", duty, f"{duty_rate_pct:.2f}% MFN on the CIF value of {cif:.2f} USD", "measured")
    )
    lines.append(CostLine("Customs brokerage", _BROKERAGE_USD, "flat per consignment", "estimated"))

    total = round(sum(line.amount_usd for line in lines), 2)
    return LandedCost(
        lines=lines,
        total_usd=total,
        cost_per_kg_usd=round(total / volume_kg, 4) if volume_kg else 0.0,
        cif_value_usd=cif,
        duty_amount_usd=duty,
        transit_days_estimate=estimate_transit_days(distance_km, mode),
        assumptions=assumptions,
    )
