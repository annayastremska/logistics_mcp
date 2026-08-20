"""Exercise every tool end to end and report status, not just absence of crashes.

    python scripts/smoke_tools.py                  # live
    SOURCING_MODE=record python scripts/smoke_tools.py   # live + write fixtures
    REPLAY=1 python scripts/smoke_tools.py         # offline, from fixtures

Demo case: fresh grapes (HS 0806), a real Ukrainian import with several origins.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp_server.server import (  # noqa: E402
    assess_supply_concentration_risk,
    estimate_landed_cost,
    get_import_flows,
    rank_sourcing_countries,
    validate_sourcing_brief,
)
from mcp_server.sources.http import current_mode  # noqa: E402

HS = "080610"  # Grapes, fresh
YEAR = 2024
VOLUME_KG = 120_000.0

failures: list[str] = []


def check(label: str, result, *, expect: tuple[str, ...] = ("ok",)) -> None:
    status = getattr(result, "status", "?")
    ok = status in expect
    print(f"\n=== {label} -> status={status} {'OK' if ok else 'UNEXPECTED'}")
    if not ok:
        failures.append(f"{label}: status={status}")
    payload = result.model_dump(exclude_none=True)
    for key in ("errors", "warnings", "notes", "flags", "caveats"):
        if payload.get(key):
            print(f"  {key}: {json.dumps(payload[key], ensure_ascii=False, default=str)[:400]}")


print(f"transport mode: {current_mode()}")

brief = validate_sourcing_brief(target_volume_kg=VOLUME_KG, hs_code=HS, candidate_countries=["TUR", "IND", "MDA"], year=YEAR)
check("1. validate_sourcing_brief (valid)", brief)
if brief.normalized_brief:
    print(f"  resolved: HS {brief.normalized_brief.hs_code} - {brief.normalized_brief.hs_description}")
    print(f"  unit price available: {brief.normalized_brief.supports_unit_price}")

bad = validate_sourcing_brief(target_volume_kg=1000, hs_code="123456")
check("2. validate_sourcing_brief (invalid HS -> must be error)", bad, expect=("error",))

flows = get_import_flows(hs_code=HS, year=YEAR, top_n=5)
check("3. get_import_flows", flows)
print(f"  partners={flows.partner_count} duplicates_dropped={flows.rows_dropped_as_duplicates}")
print(f"  total={flows.total_value_usd:,.0f} USD")
for row in flows.rows:
    price = f"{row.unit_price_usd_per_kg:.3f}" if row.unit_price_usd_per_kg else "n/a"
    print(f"   {row.partner_iso3} {row.partner_name[:22]:<22} {row.value_usd:>14,.0f} USD  {row.share_of_total_pct:>5.1f}%  {price} USD/kg")

empty = get_import_flows(hs_code=HS, year=2030, top_n=5)
check("4. get_import_flows (future year -> must be empty, not error)", empty, expect=("empty",))

risk = assess_supply_concentration_risk(hs_code=HS, years=[2021, 2022, 2023, 2024])
check("5. assess_supply_concentration_risk", risk)
print(f"  HHI={risk.hhi} effective_partners={risk.effective_partner_count} top={risk.top_partner_iso3} {risk.top_partner_share_pct}%")
print(f"  volatility={risk.yoy_volatility_pct} mirror_gap={risk.mirror_gap_pct}")
print(f"  {risk.interpretation}")

cost = estimate_landed_cost(hs_code=HS, origin_iso3="TUR", volume_kg=VOLUME_KG, transport_mode="road", year=YEAR)
check("6. estimate_landed_cost", cost)
if cost.status == "ok":
    print(f"  distance={cost.distance_km} km  duty={cost.duty_rate_pct}% ({cost.duty_basis})  fta_possible={cost.fta_preference_possible}")
    for component in cost.components:
        print(f"   {component.label[:52]:<52} {component.amount_usd:>12,.2f}  [{component.measurement}]")
    print(f"   {'TOTAL':<52} {cost.total_landed_cost_usd:>12,.2f}  = {cost.cost_per_kg_usd} USD/kg")

ranking = rank_sourcing_countries(hs_code=HS, candidates=["TUR", "IND", "MDA"], volume_kg=VOLUME_KG, year=YEAR, transport_mode="road")
check("7. rank_sourcing_countries", ranking)
for entry in ranking.ranking:
    print(f"   #{entry.rank} {entry.iso3} score={entry.score:>6.2f}  cost/kg={entry.landed_cost_per_kg_usd}  LPI={entry.lpi_overall}  duty={entry.duty_rate_pct}%  supply={entry.supply_share_pct}%")
    print(f"        " + "  ".join(f"{f.criterion}:{f.contribution:.1f}" for f in entry.factors))

bad_weights = rank_sourcing_countries(
    hs_code=HS, candidates=["TUR", "IND"], volume_kg=VOLUME_KG,
    weights={"price": 0.9, "logistics": 0.9, "duty": 0.1, "supply": 0.1},  # type: ignore[arg-type]
)
check("8. rank_sourcing_countries (weights not summing to 1 -> must be error)", bad_weights, expect=("error",))

print("\n" + "=" * 70)
if failures:
    print(f"FAILURES ({len(failures)}):")
    for failure in failures:
        print(f"  - {failure}")
    sys.exit(1)
print("all tool checks passed")
