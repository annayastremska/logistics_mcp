"""Unit tests for the parts most likely to be wrong in a subtle, silent way.

Run with:  python -m pytest tests -q
"""

from __future__ import annotations

import math

from mcp_server.domain import analysis, costing
from mcp_server.sources import comtrade, reference


# --------------------------------------------------------------------------- #
# Comtrade deduplication
# --------------------------------------------------------------------------- #


def _row(partner: int, partner2: int, value: float, weight: float = 1000.0) -> dict:
    return {
        "partnerCode": partner,
        "partner2Code": partner2,
        "cmdCode": "0806",
        "primaryValue": value,
        "netWgt": weight,
        "period": "2024",
    }


def test_dedupe_collapses_the_partner2_duplication() -> None:
    """The live API returns every partner twice, once per partner2Code value."""
    rows = [
        _row(792, 899, 100.0),
        _row(792, 0, 100.0),
        _row(699, 899, 50.0),
        _row(699, 0, 50.0),
    ]
    kept, dropped = comtrade._dedupe(rows)
    assert dropped == 2
    assert {r["partnerCode"] for r in kept} == {792, 699}
    # Critically: the value is not doubled.
    assert sum(r["primaryValue"] for r in kept) == 150.0


def test_dedupe_falls_back_without_the_zero_aggregate() -> None:
    """If the 0 aggregate is absent, keep the highest row per partner, never sum."""
    rows = [_row(792, 899, 100.0), _row(792, 251, 60.0), _row(699, 899, 50.0)]
    kept, dropped = comtrade._dedupe(rows)
    assert dropped == 1
    assert sum(r["primaryValue"] for r in kept) == 150.0


def test_aggregate_partners_are_recognised() -> None:
    """World and regional aggregates must never be scored as origin countries."""
    assert reference.is_aggregate_partner(0) is True
    assert reference.is_aggregate_partner(792) is False  # Turkiye


# --------------------------------------------------------------------------- #
# Concentration statistics
# --------------------------------------------------------------------------- #


def test_hhi_of_a_monopoly_is_ten_thousand() -> None:
    stats = analysis.herfindahl([500.0])
    assert stats is not None
    assert stats.hhi == 10000.0
    assert stats.effective_partner_count == 1.0
    assert stats.top_share_pct == 100.0


def test_hhi_of_four_equal_suppliers_is_2500() -> None:
    stats = analysis.herfindahl([25.0, 25.0, 25.0, 25.0])
    assert stats is not None
    assert stats.hhi == 2500.0
    assert stats.effective_partner_count == 4.0


def test_hhi_ignores_zero_and_negative_values() -> None:
    assert analysis.herfindahl([0.0, 0.0]) is None
    stats = analysis.herfindahl([100.0, 0.0])
    assert stats is not None and stats.partner_count == 1


def test_volatility_needs_at_least_three_years() -> None:
    """Two years give one change and a standard deviation of zero, which would
    read as perfect stability. Refuse instead."""
    assert analysis.yoy_volatility_pct([(2023, 100.0), (2024, 200.0)]) is None
    assert analysis.yoy_volatility_pct([(2022, 100.0), (2023, 100.0), (2024, 100.0)]) == 0.0


def test_volatility_detects_a_swing() -> None:
    volatility = analysis.yoy_volatility_pct([(2021, 100.0), (2022, 200.0), (2023, 100.0), (2024, 200.0)])
    assert volatility is not None and volatility > analysis.VOLATILITY_PCT


def test_mirror_gap_sign_and_guard() -> None:
    assert analysis.mirror_gap_pct(100.0, 120.0) == 20.0
    assert analysis.mirror_gap_pct(100.0, 80.0) == -20.0
    assert analysis.mirror_gap_pct(0.0, 50.0) is None


# --------------------------------------------------------------------------- #
# Normalization
# --------------------------------------------------------------------------- #


def test_normalization_orients_both_directions_to_higher_is_better() -> None:
    cost = {"a": 1.0, "b": 3.0}
    assert analysis.min_max_normalize(cost, higher_is_better=False) == {"a": 1.0, "b": 0.0}
    assert analysis.min_max_normalize(cost, higher_is_better=True) == {"a": 0.0, "b": 1.0}


def test_normalization_of_identical_values_is_neutral() -> None:
    """A criterion that cannot separate candidates must not decide the ranking."""
    result = analysis.min_max_normalize({"a": 5.0, "b": 5.0}, higher_is_better=True)
    assert result == {"a": 0.5, "b": 0.5}


def test_normalization_preserves_missing_values() -> None:
    result = analysis.min_max_normalize({"a": 1.0, "b": None}, higher_is_better=True)
    assert result["b"] is None


# --------------------------------------------------------------------------- #
# Landed cost
# --------------------------------------------------------------------------- #


def test_landed_cost_lines_sum_to_the_total() -> None:
    """The breakdown shown to the user must actually add up."""
    result = costing.build_landed_cost(
        volume_kg=10_000.0,
        unit_price_usd_per_kg=1.5,
        distance_km=1200.0,
        mode="road",
        duty_rate_pct=10.0,
        unit_price_is_cif=False,
    )
    assert math.isclose(sum(line.amount_usd for line in result.lines), result.total_usd, abs_tol=0.01)
    assert math.isclose(result.cost_per_kg_usd * 10_000.0, result.total_usd, abs_tol=1.0)


def test_duty_is_assessed_on_the_cif_value_not_the_goods_value() -> None:
    """Customs values duty on CIF; charging it on the goods value understates cost."""
    result = costing.build_landed_cost(
        volume_kg=1000.0,
        unit_price_usd_per_kg=10.0,
        distance_km=5000.0,
        mode="sea",
        duty_rate_pct=10.0,
        unit_price_is_cif=False,
    )
    goods = 10_000.0
    assert result.cif_value_usd > goods
    assert math.isclose(result.duty_amount_usd, result.cif_value_usd * 0.10, abs_tol=0.01)
    assert result.duty_amount_usd > goods * 0.10


def test_cif_unit_value_does_not_add_freight_twice() -> None:
    """A Comtrade import unit value already includes freight to the border."""
    result = costing.build_landed_cost(
        volume_kg=1000.0,
        unit_price_usd_per_kg=10.0,
        distance_km=5000.0,
        mode="sea",
        duty_rate_pct=10.0,
        unit_price_is_cif=True,
    )
    assert result.cif_value_usd == 10_000.0
    freight_lines = [line for line in result.lines if "Freight" in line.label]
    assert freight_lines and freight_lines[0].amount_usd == 0.0


def test_freight_grows_with_distance_and_mode_cost() -> None:
    near = costing.estimate_freight_usd(1000.0, 500.0, "road")
    far = costing.estimate_freight_usd(1000.0, 5000.0, "road")
    assert far > near
    assert costing.estimate_freight_usd(1000.0, 5000.0, "air") > costing.estimate_freight_usd(1000.0, 5000.0, "sea")


def test_modelled_components_are_labelled_estimated() -> None:
    """Nothing modelled may masquerade as measured."""
    result = costing.build_landed_cost(
        volume_kg=1000.0, unit_price_usd_per_kg=2.0, distance_km=1000.0,
        mode="road", duty_rate_pct=5.0, unit_price_is_cif=False,
    )
    freight = next(line for line in result.lines if line.label == "Freight")
    assert freight.measurement == "estimated"
    duty = next(line for line in result.lines if line.label == "Import duty")
    assert duty.measurement == "measured"


# --------------------------------------------------------------------------- #
# Reference data
# --------------------------------------------------------------------------- #


def test_hs_lookup_and_search() -> None:
    entry = reference.lookup_hs("080610")
    assert entry is not None and "rape" in entry.description.lower()
    # 999999 looks invalid but is a real HS2022 bucket ("Commodities not specified
    # according to kind"), so an out-of-nomenclature code is used instead.
    assert reference.lookup_hs("999999") is not None
    assert reference.lookup_hs("123456") is None
    assert any(hit.code.startswith("0806") for hit in reference.search_hs("grapes fresh"))


def test_country_resolution_by_code_and_name() -> None:
    """The table spells it "Turkiye" with an umlaut; callers type plain ASCII."""
    by_code = reference.resolve_country("TUR")
    by_name = reference.resolve_country("Turkiye")
    assert by_code is not None and by_name is not None
    assert by_code.iso3 == by_name.iso3 == "TUR"
    assert reference.resolve_country("Atlantis") is None


def test_distance_is_symmetric_and_zero_to_self() -> None:
    assert reference.great_circle_km("UKR") == 0.0
    forward = reference.great_circle_km("TUR", "UKR")
    backward = reference.great_circle_km("UKR", "TUR")
    assert forward == backward
    assert 800 < (forward or 0) < 1600  # Ankara to Kyiv


def test_eu_members_flag_a_possible_preference() -> None:
    """The DCFTA means an MFN rate is probably not what is actually paid."""
    assert reference.fta_preference_possible("POL") is True
    assert reference.fta_preference_possible("CHN") is False


def test_mirror_gap_threshold_is_asymmetric() -> None:
    """FOB-versus-CIF makes a moderately negative gap the expected reading."""
    assert analysis.mirror_gap_is_suspicious(-20.0) is False
    assert analysis.mirror_gap_is_suspicious(-25.6) is False  # observed live for HS 080610
    assert analysis.mirror_gap_is_suspicious(-80.0) is True   # far beyond valuation effects
    assert analysis.mirror_gap_is_suspicious(40.0) is True    # partners report more than arrived
    assert analysis.mirror_gap_is_suspicious(None) is False


# --------------------------------------------------------------------------- #
# Ranking: an unscorable criterion must not read as a bad one
# --------------------------------------------------------------------------- #


def test_partially_scored_candidate_declares_how_much_weight_was_scored(monkeypatch) -> None:
    """A missing input contributes nothing, exactly like a bad value would.

    Without ``scored_weight_pct`` a candidate whose cost could not be priced
    scores 15 out of 100 next to a fully priced candidate's 90, and the reader
    has no way to tell "unknown" from "poor". The score is deliberately left
    unrenormalised -- inventing a comparison the data cannot support would be
    worse -- so the gap has to travel alongside it.
    """
    # Replay, so the suite stays offline and fast: this is the only test that
    # reaches the tool layer rather than the pure domain functions, and against
    # the live APIs it took 97 seconds on its own.
    monkeypatch.setenv("SOURCING_MODE", "replay")

    from mcp_server.server import rank_sourcing_countries

    result = rank_sourcing_countries(
        hs_code="080610",
        candidates=["TUR", "MDA", "IND"],
        volume_kg=120_000.0,
        transport_mode="road",
        year=2024,
    )
    assert result.status == "ok"

    for country in result.ranking:
        scored = {f.criterion for f in country.factors if f.normalized is not None}
        missing = {f.criterion for f in country.factors if f.normalized is None}

        # The declared gap must match the decomposition it summarises.
        assert set(country.unscored_criteria) == missing
        expected_weight = sum(f.weight for f in country.factors if f.criterion in scored)
        assert country.scored_weight_pct == round(expected_weight * 100.0, 1)

        # A contribution of zero is only allowed to mean "scored zero", never
        # "not scored" -- the two are distinguished by ``normalized`` being None.
        for factor in country.factors:
            if factor.normalized is None:
                assert factor.raw_value is None
                assert factor.contribution == 0.0

    # Whenever any candidate is short of the full weight, the result must say so
    # where the scores are read, not only in the per-factor detail.
    if any(c.scored_weight_pct < 100.0 for c in result.ranking):
        assert any("NOT comparable" in caveat for caveat in result.caveats)


def test_a_proxy_price_scores_a_candidate_that_does_not_ship_here_yet(monkeypatch) -> None:
    """Widening the shortlist must not be punished for the widening itself.

    An origin Ukraine does not currently buy from has no trade to derive a unit
    value from, so price and duty go unscored and it lands last on missing data
    rather than on merit -- measured at 1.33 out of 100 on a live run, for an
    origin the agent had just been told to include. Passing the proxy it already
    used for ``estimate_landed_cost`` closes the gap, and the row records that
    the figure was supplied rather than observed.
    """
    monkeypatch.setenv("SOURCING_MODE", "replay")

    from mcp_server.server import rank_sourcing_countries

    without = rank_sourcing_countries(
        hs_code="080610", candidates=["TUR", "MDA", "MAR"], volume_kg=120_000.0, year=2024
    )
    with_proxy = rank_sourcing_countries(
        hs_code="080610",
        candidates=["TUR", "MDA", "MAR"],
        volume_kg=120_000.0,
        year=2024,
        unit_prices={"MAR": 2.05},
    )
    assert without.status == "ok" and with_proxy.status == "ok"

    bare = next(c for c in without.ranking if c.iso3 == "MAR")
    proxied = next(c for c in with_proxy.ranking if c.iso3 == "MAR")

    # Before: unscored on price, and the score reflects the gap, not the origin.
    assert "price" in bare.unscored_criteria
    assert bare.landed_cost_per_kg_usd is None
    assert bare.price_basis is None

    # After: fully scored, and the basis of the figure travels with it.
    assert proxied.price_basis == "caller_supplied"
    assert proxied.landed_cost_per_kg_usd is not None
    assert "price" not in proxied.unscored_criteria
    assert proxied.scored_weight_pct > bare.scored_weight_pct

    # An origin that does have reported trade is untouched by the argument.
    for iso in ("TUR", "MDA"):
        assert next(c for c in with_proxy.ranking if c.iso3 == iso).price_basis == "reported"

    # A supplied price is never allowed to pass for an observed one.
    assert any("supplied by the caller" in caveat for caveat in with_proxy.caveats)
    assert not any("supplied by the caller" in caveat for caveat in without.caveats)


def test_a_supplied_price_that_displaces_a_reported_one_says_so(monkeypatch) -> None:
    """Filling a gap and overriding an observation are not the same act.

    A live run supplied a proxy for Greece, which does report trade with Ukraine
    -- thin, but real -- while the caveat claimed the origin had done no trade
    with the importer. True of Morocco in the same run, false of Greece. Whether
    an origin reports anything is already known from the flows fetched for supply
    share, so telling the two apart costs no extra request.
    """
    monkeypatch.setenv("SOURCING_MODE", "replay")

    from mcp_server.server import rank_sourcing_countries

    result = rank_sourcing_countries(
        hs_code="080610",
        candidates=["TUR", "MDA", "MAR"],
        volume_kg=120_000.0,
        year=2024,
        # TUR is the largest existing origin; MAR does not ship here at all.
        unit_prices={"TUR": 2.50, "MAR": 2.05},
    )
    assert result.status == "ok"

    by_iso = {c.iso3: c for c in result.ranking}
    assert by_iso["TUR"].price_basis == "caller_override", "a reported value was displaced"
    assert by_iso["MAR"].price_basis == "caller_supplied", "there was nothing to displace"
    assert by_iso["MDA"].price_basis == "reported"

    # Each case gets its own sentence, and neither claims the other's reason.
    gap = next(c for c in result.caveats if "no trade with this importer exists" in c)
    displaced = next(c for c in result.caveats if "in place of a reported one" in c)
    assert "MAR" in gap and "TUR" not in gap
    assert "TUR" in displaced and "MAR" not in displaced
