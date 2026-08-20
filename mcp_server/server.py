"""trade-sourcing-mcp: import-sourcing tools over open trade data.

Runs as its own process over stdio and is started independently of the agent:

    python -m mcp_server.server

Exposes five tools. ``get_import_flows`` is the primary data-source tool; the
other four apply domain rules, computation and comparison on top of it.
"""

from __future__ import annotations

import datetime as _dt
from typing import Annotated

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from .domain import analysis, costing
from .models import (
    ConcentrationRiskResult,
    CostComponent,
    CriterionWeights,
    ErrorCode,
    FactorContribution,
    FlowRow,
    ImportFlowsResult,
    LandedCostResult,
    NormalizedBrief,
    Provenance,
    RankedCountry,
    RankingResult,
    RiskFlag,
    ToolErrorDetail,
    ValidateBriefResult,
    YearObservation,
)
from .sources import comtrade, reference, wits, worldbank
from .sources.http import UpstreamError, current_mode

mcp = MCPServer(
    name="trade-sourcing-mcp",
    version="1.0.0",
    instructions=(
        "Macro-level import sourcing screening for Ukraine, built on open trade data.\n\n"
        "Normal order of use:\n"
        "1. validate_sourcing_brief - resolve the product to an HS code before anything else.\n"
        "2. get_import_flows - see which countries actually supply it.\n"
        "3. assess_supply_concentration_risk - check whether current supply is concentrated.\n"
        "4. estimate_landed_cost - cost one candidate origin.\n"
        "5. rank_sourcing_countries - score candidates against each other.\n\n"
        "Every result carries a 'status' field: 'ok' with data, 'empty' when the source "
        "genuinely reported nothing for that period, or 'error' with codes in 'errors'. "
        "'empty' is not a failure - do not retry it as if it were."
    ),
)

# Mirror comparison is one extra API call per partner, so it is limited to the
# largest origins, which is where a discrepancy would actually matter.
MIRROR_TOP_PARTNERS = 5

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True)
LOCAL_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)


def _err(code: ErrorCode, message: str, field: str | None = None) -> ToolErrorDetail:
    return ToolErrorDetail(code=code, message=message, field=field)


def _upstream_error(exc: UpstreamError) -> ToolErrorDetail:
    """Map a transport failure onto the published error vocabulary."""
    code = {
        "RATE_LIMITED": ErrorCode.RATE_LIMITED,
        "UPSTREAM_UNAVAILABLE": ErrorCode.UPSTREAM_UNAVAILABLE,
        "UPSTREAM_MALFORMED": ErrorCode.UPSTREAM_MALFORMED,
        "FIXTURE_MISSING": ErrorCode.FIXTURE_MISSING,
        "INVALID_ARGUMENT": ErrorCode.INVALID_ARGUMENT,
    }.get(exc.code, ErrorCode.UPSTREAM_UNAVAILABLE)
    return _err(code, exc.message)


# Verified against the live API in August 2026: Ukraine had reported 2024 but not
# 2025, so the practical lag is closer to two years than one.
_REPORTING_LAG_YEARS = 2


def _default_year() -> int:
    """Latest year Ukraine has plausibly finished reporting."""
    return _dt.date.today().year - _REPORTING_LAG_YEARS


# Resolved once per process. Which month the source has published to is a
# property of the source, not of a request, and the probe costs one call per
# month walked back -- worth paying once, not once per product line.
_FRONTIER_CACHE: dict[str, str | None] = {}


def _resolve_window_end(requested: str) -> tuple[str | None, str | None]:
    """Turn a requested window end into a concrete YYYYMM.

    ``"latest"`` asks the source where its monthly reporting actually stops.
    Hardcoding that month would quietly go stale, which is the exact problem
    monthly data is here to solve.

    Returns:
        ``(period, error_message)`` -- exactly one is set.
    """
    cleaned = requested.strip().lower()
    if cleaned != "latest":
        if not (len(cleaned) == 6 and cleaned.isdigit() and 1 <= int(cleaned[4:]) <= 12):
            return None, f"trailing_12m_to must be YYYYMM or 'latest'; got {requested!r}."
        return cleaned, None

    if "frontier" not in _FRONTIER_CACHE:
        _FRONTIER_CACHE["frontier"] = comtrade.latest_reported_month()
    frontier = _FRONTIER_CACHE["frontier"]
    if frontier is None:
        return None, "Could not determine the latest published month from the source."
    return frontier, None


# --------------------------------------------------------------------------- #
# 1. validate_sourcing_brief
# --------------------------------------------------------------------------- #


@mcp.tool(
    name="validate_sourcing_brief",
    title="Validate a sourcing brief",
    description=(
        "Resolve and validate a sourcing request before any data is fetched. Accepts either an "
        "HS commodity code or a free-text product name, checks it against the HS2022 "
        "nomenclature, validates candidate origin countries, and reports whether the requested "
        "aggregation level supports a price-per-kg comparison. Call this first: it turns a vague "
        "request into the exact hs_code and year the other tools need, and it fails fast on an "
        "unknown code without spending an API call. When a product name matches several codes it "
        "returns ranked candidates instead of guessing."
    ),
    annotations=LOCAL_ONLY,
)
def validate_sourcing_brief(
    target_volume_kg: Annotated[
        float, Field(gt=0, description="Volume the buyer intends to source, in kilograms.")
    ],
    hs_code: Annotated[
        str | None,
        Field(default=None, description="HS2022 code: 2 digits (chapter), 4 (heading) or 6 (subheading)."),
    ] = None,
    product_query: Annotated[
        str | None,
        Field(default=None, min_length=3, description="Product name to resolve, e.g. 'fresh grapes'."),
    ] = None,
    candidate_countries: Annotated[
        list[str] | None,
        Field(default=None, max_length=10, description="Candidate origins as ISO3 codes or country names."),
    ] = None,
    year: Annotated[
        int | None,
        Field(default=None, ge=2015, le=2030, description="Reference year; defaults to the last complete year."),
    ] = None,
) -> ValidateBriefResult:
    errors: list[ToolErrorDetail] = []
    warnings: list[str] = []

    if not hs_code and not product_query:
        return ValidateBriefResult(
            status="error",
            errors=[_err(ErrorCode.INVALID_ARGUMENT, "Provide either hs_code or product_query.", "hs_code")],
        )

    entry = None
    if hs_code:
        cleaned = hs_code.strip()
        if not cleaned.isdigit() or len(cleaned) not in (2, 4, 6):
            errors.append(
                _err(ErrorCode.INVALID_ARGUMENT, f"HS codes are 2, 4 or 6 digits; got {hs_code!r}.", "hs_code")
            )
        else:
            entry = reference.lookup_hs(cleaned)
            if entry is None:
                candidates = reference.search_hs(cleaned, limit=5)
                return ValidateBriefResult(
                    status="error",
                    hs_candidates=[{"hs_code": c.code, "description": c.description} for c in candidates],
                    errors=[
                        _err(
                            ErrorCode.UNKNOWN_HS_CODE,
                            f"{cleaned} is not a code in the HS2022 nomenclature.",
                            "hs_code",
                        )
                    ],
                )
    else:
        matches = reference.search_hs(product_query or "")
        if not matches:
            return ValidateBriefResult(
                status="empty",
                warnings=[f"No HS2022 description matches {product_query!r}. Try a different wording."],
            )
        if len(matches) > 1 and matches[0].level != 4:
            return ValidateBriefResult(
                status="empty",
                hs_candidates=[{"hs_code": m.code, "description": m.description} for m in matches],
                warnings=[
                    f"{product_query!r} matched {len(matches)} HS codes. Pick one and call again with hs_code."
                ],
            )
        entry = matches[0]
        warnings.append(f"Resolved {product_query!r} to HS {entry.code} ({entry.description}).")

    if errors or entry is None:
        return ValidateBriefResult(status="error", errors=errors or [
            _err(ErrorCode.UNKNOWN_HS_CODE, "Could not resolve the product to an HS code.", "hs_code")
        ])

    resolved_countries: list[str] = []
    for token in candidate_countries or []:
        country = reference.resolve_country(token)
        if country is None:
            errors.append(
                _err(ErrorCode.UNKNOWN_COUNTRY, f"{token!r} is not a known country.", "candidate_countries")
            )
        else:
            resolved_countries.append(country.iso3)

    if errors:
        return ValidateBriefResult(status="error", warnings=warnings, errors=errors)

    resolved_year = year or _default_year()
    if resolved_year >= _dt.date.today().year:
        warnings.append(
            f"{resolved_year} is the current year; Ukraine reports annual trade with roughly a "
            f"one-year lag, so expect no data. Consider {_default_year()}."
        )

    level_name = {2: "chapter", 4: "heading", 6: "subheading"}[len(entry.code)]
    supports_price = len(entry.code) >= 4
    if not supports_price:
        warnings.append(
            "At chapter level Comtrade reports zero net weight, so price per kg cannot be computed. "
            "Use a 4- or 6-digit code for cost comparison."
        )

    return ValidateBriefResult(
        status="ok",
        normalized_brief=NormalizedBrief(
            hs_code=entry.code,
            hs_description=entry.description,
            hs_level=level_name,  # type: ignore[arg-type]
            supports_unit_price=supports_price,
            target_volume_kg=target_volume_kg,
            year=resolved_year,
            candidate_countries=resolved_countries,
        ),
        warnings=warnings,
    )


# --------------------------------------------------------------------------- #
# 2. get_import_flows  (primary data source)
# --------------------------------------------------------------------------- #


@mcp.tool(
    name="get_import_flows",
    title="Get reported import flows",
    description=(
        "Fetch which countries actually supplied a product to Ukraine in a given year, from UN "
        "Comtrade. Returns each origin's weight, value, unit value per kg and share of the total, "
        "sorted by value. Use this to discover real suppliers rather than assuming them. Set "
        "flow_direction='mirror_export' to instead read what partner countries reported exporting "
        "to Ukraine, which is the input to a mirror-gap check. Duplicate rows in the source are "
        "collapsed and reporting aggregates such as 'World' are excluded before shares are "
        "computed. status='empty' means Comtrade holds no record for that product and year, which "
        "is a real answer, not a failure."
    ),
    annotations=READ_ONLY,
)
def get_import_flows(
    hs_code: Annotated[str, Field(min_length=2, max_length=6, description="HS2022 code, 2/4/6 digits.")],
    year: Annotated[int, Field(ge=2015, le=2030, description="Reference year.")],
    flow_direction: Annotated[
        str,
        Field(
            default="import",
            description=(
                "'import' for flows Ukraine reported importing; 'mirror_export' for flows partner "
                "countries reported exporting to Ukraine."
            ),
        ),
    ] = "import",
    top_n: Annotated[int, Field(default=10, ge=1, le=50, description="Number of origins to return.")] = 10,
    partner_iso3: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Required when flow_direction is 'mirror_export': the country whose own export "
                "report should be read. Ignored for 'import'."
            ),
        ),
    ] = None,
    trailing_12m_to: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "YYYYMM, or 'latest' to use whatever month the source has published to. When set, "
                "returns the twelve monthly periods ending there instead of the "
                "annual figure for 'year'. Monthly reporting runs up to a year ahead of the annual "
                "series, so this is the more current view; use it when currency matters and the "
                "annual figure when a settled calendar year is needed. Imports only."
            ),
        ),
    ] = None,
) -> ImportFlowsResult:
    if flow_direction not in ("import", "mirror_export"):
        return ImportFlowsResult(
            status="error",
            errors=[
                _err(
                    ErrorCode.INVALID_ARGUMENT,
                    "flow_direction must be 'import' or 'mirror_export'.",
                    "flow_direction",
                )
            ],
        )

    entry = reference.lookup_hs(hs_code.strip())
    if entry is None:
        return ImportFlowsResult(
            status="error",
            errors=[_err(ErrorCode.UNKNOWN_HS_CODE, f"{hs_code} is not in HS2022.", "hs_code")],
        )

    notes: list[str] = []
    period_label = str(year)
    try:
        if trailing_12m_to and flow_direction == "import":
            window_end, window_error = _resolve_window_end(trailing_12m_to)
            if window_error:
                return ImportFlowsResult(
                    status="error",
                    errors=[_err(ErrorCode.INVALID_ARGUMENT, window_error, "trailing_12m_to")],
                )
            response, covered, empty = comtrade.fetch_trailing_window(
                hs_code=entry.code, end_period=window_end or ""
            )
            period_label = f"{covered[0]}-{covered[-1]}" if covered else trailing_12m_to
            notes.append(
                f"Rolling twelve-month window {period_label}, summed from monthly reports. "
                "Monthly data is more current than the annual series but a month can still be "
                "revised after publication."
            )
            if empty:
                # A month the source publishes nothing for is not a zero month.
                # Saying which ones are missing is the difference between a
                # partial window and a window that looks complete.
                notes.append(
                    f"{len(empty)} month(s) in the window have no published data and were "
                    f"excluded rather than counted as zero: {', '.join(empty)}."
                )
        elif flow_direction == "import":
            response = comtrade.fetch_flows(hs_code=entry.code, year=year, flow="M")
        else:
            counterpart = reference.resolve_country(partner_iso3 or "")
            if counterpart is None:
                return ImportFlowsResult(
                    status="error",
                    errors=[
                        _err(
                            ErrorCode.INVALID_ARGUMENT,
                            "flow_direction='mirror_export' needs partner_iso3 set to the country "
                            "whose export report should be read.",
                            "partner_iso3",
                        )
                    ],
                )
            response = comtrade.fetch_flows(
                hs_code=entry.code,
                year=year,
                flow="X",
                reporter_code=counterpart.code,
                partner_code=reference.UKRAINE_REPORTER_CODE,
            )
            notes.append(
                f"Mirror view: what {counterpart.name} reported exporting to Ukraine, valued FOB, "
                f"so it sits below Ukraine's CIF import figure by design."
            )
    except UpstreamError as exc:
        return ImportFlowsResult(status="error", errors=[_upstream_error(exc)])

    provenance = Provenance(
        source="UN Comtrade",
        mode="fixture" if response.fetch.mode == "replay" else "live",
        retrieved_at=response.fetch.retrieved_at or None,
        as_of=period_label,
        measurement="measured",
    )

    if not response.records:
        return ImportFlowsResult(
            status="empty",
            provenance=provenance,
            rows_dropped_as_duplicates=response.duplicates_dropped,
            notes=[
                f"UN Comtrade reported no {flow_direction} records for HS {entry.code} in "
                f"{period_label}. Ukraine's latest complete annual year is usually "
                f"{_default_year()}."
            ],
        )

    total_value = sum(r.value_usd for r in response.records)
    weights = [r.net_weight_kg for r in response.records if r.net_weight_kg]
    total_weight = sum(weights) if weights else None

    if len(entry.code) == 2:
        notes.append(
            "Chapter-level query: Comtrade reports zero net weight for aggregates, so unit prices "
            "are unavailable here."
        )
    if response.duplicates_dropped:
        notes.append(
            f"{response.duplicates_dropped} duplicate rows collapsed on the partner2Code dimension "
            f"(country of origin vs consignment); the source repeats every partner."
        )
    if response.truncated:
        notes.append(
            f"The response hit the {comtrade.RECORD_CAP}-record cap, so less-significant origins may "
            f"be missing."
        )

    rows = [
        FlowRow(
            partner_iso3=reference.partner_iso3(r.partner_code),
            partner_name=reference.partner_name(r.partner_code),
            net_weight_kg=r.net_weight_kg,
            value_usd=round(r.value_usd, 2),
            unit_price_usd_per_kg=(
                round(r.value_usd / r.net_weight_kg, 4) if r.net_weight_kg else None
            ),
            share_of_total_pct=round(r.value_usd / total_value * 100.0, 2) if total_value else 0.0,
        )
        for r in response.records[:top_n]
    ]

    return ImportFlowsResult(
        status="ok",
        rows=rows,
        total_value_usd=round(total_value, 2),
        total_net_weight_kg=round(total_weight, 1) if total_weight else None,
        partner_count=len(response.records),
        rows_dropped_as_duplicates=response.duplicates_dropped,
        truncated=response.truncated,
        provenance=provenance,
        notes=notes,
    )


# --------------------------------------------------------------------------- #
# 3. estimate_landed_cost
# --------------------------------------------------------------------------- #


@mcp.tool(
    name="estimate_landed_cost",
    title="Estimate landed cost for one origin",
    description=(
        "Build up the landed cost of importing a given volume from one origin country: goods "
        "value, cargo insurance, the applied MFN import duty from WITS assessed on the CIF value, "
        "and modelled freight for the chosen transport mode. Returns an itemised breakdown where "
        "each line is labelled 'measured' or 'estimated', because no open source publishes freight "
        "rates and that component is modelled from distance. The duty is always the MFN rate; when "
        "a free-trade agreement such as the EU DCFTA plausibly applies, "
        "fta_preference_possible is set so the caller knows the real rate may be lower. Use it to "
        "compare origins on cost, not to quote a shipment."
    ),
    annotations=READ_ONLY,
)
def estimate_landed_cost(
    hs_code: Annotated[str, Field(min_length=4, max_length=6, description="HS code, 4 or 6 digits.")],
    origin_iso3: Annotated[str, Field(min_length=3, max_length=3, description="Origin country ISO3.")],
    volume_kg: Annotated[float, Field(gt=0, description="Volume to cost, in kilograms.")],
    transport_mode: Annotated[
        str, Field(default="road", description="One of: sea, road, rail, air.")
    ] = "road",
    year: Annotated[
        int | None, Field(default=None, ge=2015, le=2030, description="Year for prices and duty.")
    ] = None,
    unit_price_usd_per_kg: Annotated[
        float | None,
        Field(default=None, gt=0, description="Override the unit value; otherwise taken from Comtrade."),
    ] = None,
) -> LandedCostResult:
    if transport_mode not in costing.supported_modes():
        return LandedCostResult(
            status="error",
            errors=[
                _err(
                    ErrorCode.INVALID_ARGUMENT,
                    f"transport_mode must be one of {', '.join(costing.supported_modes())}.",
                    "transport_mode",
                )
            ],
        )

    entry = reference.lookup_hs(hs_code.strip())
    if entry is None:
        return LandedCostResult(
            status="error",
            errors=[_err(ErrorCode.UNKNOWN_HS_CODE, f"{hs_code} is not in HS2022.", "hs_code")],
        )

    country = reference.resolve_country(origin_iso3)
    if country is None:
        return LandedCostResult(
            status="error",
            errors=[_err(ErrorCode.UNKNOWN_COUNTRY, f"{origin_iso3} is not a known country.", "origin_iso3")],
        )

    distance = reference.great_circle_km(country.iso3)
    if distance is None:
        return LandedCostResult(
            status="error",
            errors=[
                _err(
                    ErrorCode.INSUFFICIENT_DATA,
                    f"No reference coordinates for {country.iso3}, so freight cannot be modelled.",
                    "origin_iso3",
                )
            ],
        )

    resolved_year = year or _default_year()
    mode_label: str = "live"
    assumptions: list[str] = []

    price = unit_price_usd_per_kg
    if price is None:
        try:
            flows = comtrade.fetch_flows(
                hs_code=entry.code, year=resolved_year, flow="M", partner_code=country.code
            )
        except UpstreamError as exc:
            return LandedCostResult(status="error", errors=[_upstream_error(exc)])
        mode_label = "fixture" if flows.fetch.mode == "replay" else "live"
        priced = [r for r in flows.records if r.net_weight_kg]
        if not priced:
            return LandedCostResult(
                status="empty",
                origin_iso3=country.iso3,
                hs_code=entry.code,
                errors=[],
                assumptions=[
                    f"Comtrade reported no weighted import of HS {entry.code} from {country.name} in "
                    f"{resolved_year}, so no unit value could be derived. Pass "
                    f"unit_price_usd_per_kg to cost a hypothetical shipment."
                ],
            )
        price = priced[0].value_usd / (priced[0].net_weight_kg or 1.0)
        assumptions.append(
            f"Unit value {price:.3f} USD/kg derived from reported {resolved_year} imports from "
            f"{country.name}; it is a statistical unit value, not a quoted price."
        )

    duty_rate = 0.0
    duty_year_note = ""
    hs6 = entry.code if len(entry.code) == 6 else None
    if hs6 is None:
        assumptions.append(
            "Duty looked up at 6-digit level is unavailable for a 4-digit heading; 0 percent assumed. "
            "Pass a 6-digit code for a real rate."
        )
    else:
        try:
            tariff = wits.fetch_mfn_rate_with_fallback(hs6, resolved_year)
            if tariff.rate is not None:
                duty_rate = tariff.rate.rate_pct
                duty_year_note = f" (WITS observation for {tariff.rate.year})"
                if tariff.rate.year != resolved_year:
                    assumptions.append(
                        f"WITS had no {resolved_year} tariff observation; used the {tariff.rate.year} "
                        f"rate, which is stable for this product."
                    )
            else:
                assumptions.append(
                    f"WITS holds no MFN rate for HS {hs6}; 0 percent assumed, which understates cost "
                    f"if a duty in fact applies."
                )
        except UpstreamError as exc:
            assumptions.append(
                f"Tariff lookup failed ({exc.message}); 0 percent duty assumed. Treat the total as a "
                f"lower bound."
            )

    result = costing.build_landed_cost(
        volume_kg=volume_kg,
        unit_price_usd_per_kg=price,
        distance_km=distance,
        mode=transport_mode,  # type: ignore[arg-type]
        duty_rate_pct=duty_rate,
        unit_price_is_cif=unit_price_usd_per_kg is None,
    )

    return LandedCostResult(
        status="ok",
        origin_iso3=country.iso3,
        hs_code=entry.code,
        volume_kg=volume_kg,
        transport_mode=transport_mode,  # type: ignore[arg-type]
        components=[
            CostComponent(
                label=line.label, amount_usd=line.amount_usd, basis=line.basis, measurement=line.measurement
            )
            for line in result.lines
        ],
        total_landed_cost_usd=result.total_usd,
        cost_per_kg_usd=result.cost_per_kg_usd,
        duty_rate_pct=duty_rate,
        duty_basis="MFN",
        fta_preference_possible=reference.fta_preference_possible(country.iso3),
        distance_km=distance,
        confidence="medium" if duty_rate or price else "low",
        assumptions=[*assumptions, *result.assumptions, f"Duty basis: MFN{duty_year_note}."],
        provenance=Provenance(
            source="model",
            mode="fixture" if mode_label == "fixture" else "live",
            as_of=str(resolved_year),
            measurement="estimated",
        ),
    )


# --------------------------------------------------------------------------- #
# 4. rank_sourcing_countries
# --------------------------------------------------------------------------- #


@mcp.tool(
    name="rank_sourcing_countries",
    title="Rank candidate sourcing countries",
    description=(
        "Score and rank candidate origin countries for one product against four criteria: landed "
        "cost per kg, World Bank Logistics Performance Index, applied MFN duty, and demonstrated "
        "supply capacity measured as share of reported trade. Each criterion is min-max normalized "
        "across the candidates and weighted, and every country's score comes back decomposed into "
        "per-criterion contributions that sum to the score, so a ranking can be argued with rather "
        "than taken on trust. Weights are caller-supplied and must sum to 1. Call this after "
        "get_import_flows has established who the real candidates are."
    ),
    annotations=READ_ONLY,
)
def rank_sourcing_countries(
    hs_code: Annotated[str, Field(min_length=4, max_length=6, description="HS code, 4 or 6 digits.")],
    candidates: Annotated[
        list[str], Field(min_length=2, max_length=10, description="Candidate origins, ISO3 codes.")
    ],
    volume_kg: Annotated[float, Field(gt=0, description="Volume used for the cost comparison, kg.")],
    year: Annotated[int | None, Field(default=None, ge=2015, le=2030, description="Reference year.")] = None,
    transport_mode: Annotated[str, Field(default="road", description="sea, road, rail or air.")] = "road",
    weights: Annotated[
        CriterionWeights | None,
        Field(default=None, description="Criterion weights; defaults to price .40 / logistics .30 / duty .15 / supply .15."),
    ] = None,
) -> RankingResult:
    if isinstance(weights, dict):
        try:
            weights = CriterionWeights(**weights)
        except Exception as exc:  # noqa: BLE001 - surfaced as a structured error
            return RankingResult(
                status="error",
                errors=[_err(ErrorCode.INVALID_ARGUMENT, f"Invalid weights object: {exc}", "weights")],
            )
    active_weights = weights or CriterionWeights()
    total_weight = active_weights.price + active_weights.logistics + active_weights.duty + active_weights.supply
    if abs(total_weight - 1.0) > 0.001:
        return RankingResult(
            status="error",
            errors=[
                _err(
                    ErrorCode.INVALID_ARGUMENT,
                    f"Weights must sum to 1.0; they sum to {total_weight:.3f}.",
                    "weights",
                )
            ],
        )

    entry = reference.lookup_hs(hs_code.strip())
    if entry is None:
        return RankingResult(
            status="error",
            errors=[_err(ErrorCode.UNKNOWN_HS_CODE, f"{hs_code} is not in HS2022.", "hs_code")],
        )

    resolved_year = year or _default_year()
    excluded: list[dict[str, str]] = []
    resolved: dict[str, reference.CountryEntry] = {}
    for token in candidates:
        country = reference.resolve_country(token)
        if country is None:
            excluded.append({"iso3": token, "reason": "not a known country"})
        elif reference.great_circle_km(country.iso3) is None:
            excluded.append({"iso3": country.iso3, "reason": "no reference coordinates for freight modelling"})
        else:
            resolved[country.iso3] = country

    if len(resolved) < 2:
        return RankingResult(
            status="error",
            excluded=excluded,
            errors=[
                _err(
                    ErrorCode.INSUFFICIENT_DATA,
                    "At least two resolvable candidates are needed to rank.",
                    "candidates",
                )
            ],
        )

    # Supply capacity: each candidate's share of total reported imports.
    supply_share: dict[str, float | None] = {iso: None for iso in resolved}
    try:
        flows = comtrade.fetch_flows(hs_code=entry.code, year=resolved_year, flow="M")
        total = sum(r.value_usd for r in flows.records) or 1.0
        by_iso = {reference.partner_iso3(r.partner_code): r.value_usd for r in flows.records}
        for iso in resolved:
            supply_share[iso] = round(by_iso.get(iso, 0.0) / total * 100.0, 3)
        data_mode = "fixture" if flows.fetch.mode == "replay" else "live"
    except UpstreamError as exc:
        return RankingResult(status="error", excluded=excluded, errors=[_upstream_error(exc)])

    # Logistics: World Bank LPI.
    lpi: dict[str, float | None] = {iso: None for iso in resolved}
    lpi_year = None
    try:
        indicator = worldbank.fetch_indicator("lpi_overall", list(resolved))
        for iso, obs in indicator.observations.items():
            lpi[iso] = obs.value
            lpi_year = obs.year
    except UpstreamError:
        pass  # a missing criterion is normalized to None, not fatal

    # Cost and duty per candidate, reusing the landed-cost tool's own logic.
    cost: dict[str, float | None] = {}
    duty: dict[str, float | None] = {}
    for iso in resolved:
        priced = estimate_landed_cost(
            hs_code=entry.code,
            origin_iso3=iso,
            volume_kg=volume_kg,
            transport_mode=transport_mode,
            year=resolved_year,
        )
        cost[iso] = priced.cost_per_kg_usd if priced.status == "ok" else None
        duty[iso] = priced.duty_rate_pct if priced.status == "ok" else None

    norm_cost = analysis.min_max_normalize(cost, higher_is_better=False)
    norm_lpi = analysis.min_max_normalize(lpi, higher_is_better=True)
    norm_duty = analysis.min_max_normalize(duty, higher_is_better=False)
    norm_supply = analysis.min_max_normalize(supply_share, higher_is_better=True)

    criteria = (
        ("price", cost, norm_cost, active_weights.price),
        ("logistics", lpi, norm_lpi, active_weights.logistics),
        ("duty", duty, norm_duty, active_weights.duty),
        ("supply", supply_share, norm_supply, active_weights.supply),
    )

    scored: list[RankedCountry] = []
    for iso, country in resolved.items():
        factors: list[FactorContribution] = []
        score = 0.0
        # Track how much of the weight was actually scorable. An unscorable
        # criterion contributes nothing, which depresses the score exactly like a
        # bad value would -- so a candidate missing its cost data looks worse than
        # an expensive one. The score is left alone (renormalising it would invent
        # a comparison that the data does not support) but the gap travels with it,
        # so a reader can tell "unknown" from "poor".
        scored_weight = 0.0
        unscored: list[str] = []
        for name, raw_map, norm_map, weight in criteria:
            normalized = norm_map.get(iso)
            contribution = round((normalized or 0.0) * weight * 100.0, 2)
            score += contribution
            if normalized is None:
                unscored.append(name)
            else:
                scored_weight += weight
            factors.append(
                FactorContribution(
                    criterion=name,  # type: ignore[arg-type]
                    raw_value=raw_map.get(iso),
                    normalized=normalized,
                    weight=weight,
                    contribution=contribution,
                )
            )
        scored.append(
            RankedCountry(
                rank=0,
                iso3=iso,
                name=country.name,
                score=round(score, 2),
                scored_weight_pct=round(scored_weight * 100.0, 1),
                unscored_criteria=unscored,
                factors=factors,
                landed_cost_per_kg_usd=cost.get(iso),
                lpi_overall=lpi.get(iso),
                duty_rate_pct=duty.get(iso),
                supply_share_pct=supply_share.get(iso),
            )
        )

    scored.sort(key=lambda c: c.score, reverse=True)
    for position, country_score in enumerate(scored, start=1):
        country_score.rank = position

    caveats = [
        "Scores are relative to this candidate set only: adding or removing a country rewrites "
        "every normalized value and can change the order.",
        "The cost criterion contains a modelled freight component, so cost differences smaller than "
        "roughly ten percent should not decide anything.",
        "Duty is the MFN rate; candidates with a trade agreement may pay less.",
        "Transport mode does not change these scores. Reported unit values are already "
        "CIF, so modelled freight is shown for reference and excluded from the total to "
        "avoid double counting; cost differences here come from unit value and duty only.",
    ]
    if lpi_year:
        caveats.append(f"Logistics Performance Index values are as of {lpi_year}; it is not an annual series.")
    if any(v is None for v in cost.values()):
        caveats.append("Some candidates had no reported trade to price, so their cost criterion is unscored.")

    partial = [c for c in scored if c.scored_weight_pct < 100.0]
    if partial:
        caveats.append(
            "Partially scored candidates are NOT comparable with fully scored ones: an unscorable "
            "criterion contributes nothing, so a missing input looks the same as a bad one. "
            + "; ".join(
                f"{c.iso3} scored on {c.scored_weight_pct:.0f} percent of the weight "
                f"(missing: {', '.join(c.unscored_criteria)})"
                for c in partial
            )
            + "."
        )

    return RankingResult(
        status="ok",
        ranking=scored,
        weights_used=active_weights,
        excluded=excluded,
        caveats=caveats,
        provenance=Provenance(
            source="model", mode="fixture" if data_mode == "fixture" else "live", as_of=str(resolved_year),
            measurement="estimated",
        ),
    )


# --------------------------------------------------------------------------- #
# 5. assess_supply_concentration_risk
# --------------------------------------------------------------------------- #


@mcp.tool(
    name="assess_supply_concentration_risk",
    title="Assess supply concentration risk",
    description=(
        "Test whether Ukraine's supply of a product is dangerously dependent on few origins, and "
        "whether the reported figures look trustworthy. Computes the Herfindahl-Hirschman index "
        "and effective number of origins over partner shares, the top origin's share, "
        "year-over-year volatility across several years, and the mirror gap between what Ukraine "
        "reported importing and what partners reported exporting. Returns named flags such as "
        "SINGLE_SOURCE, HIGH_CONCENTRATION, VOLATILE_SUPPLY and MIRROR_DISCREPANCY against stated "
        "thresholds. Use it to decide whether a sourcing shortlist needs to reach beyond the "
        "current suppliers."
    ),
    annotations=READ_ONLY,
)
def assess_supply_concentration_risk(
    hs_code: Annotated[str, Field(min_length=2, max_length=6, description="HS2022 code, 2/4/6 digits.")],
    years: Annotated[
        list[int],
        Field(min_length=1, max_length=5, description="Years to analyse; three or more enable volatility."),
    ],
    top_partner_threshold_pct: Annotated[
        float,
        Field(default=analysis.SINGLE_SOURCE_SHARE_PCT, ge=10.0, le=100.0,
              description="Share above which a single origin counts as a dependency."),
    ] = analysis.SINGLE_SOURCE_SHARE_PCT,
    trailing_12m_to: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "YYYYMM, or 'latest'. When set, concentration, the leading origin's share and the mirror check "
                "are computed from the twelve monthly periods ending there rather than from the "
                "latest year in 'years'. Monthly reporting runs up to a year ahead of the annual "
                "series, so a share can differ materially from the latest annual figure. "
                "Volatility still comes from the annual series in 'years', and the result says so."
            ),
        ),
    ] = None,
) -> ConcentrationRiskResult:
    entry = reference.lookup_hs(hs_code.strip())
    if entry is None:
        return ConcentrationRiskResult(
            status="error",
            errors=[_err(ErrorCode.UNKNOWN_HS_CODE, f"{hs_code} is not in HS2022.", "hs_code")],
        )

    observations: list[YearObservation] = []
    latest_records: list[comtrade.TradeRecord] = []
    latest_year: int | None = None
    data_mode = "live"

    for year in sorted(set(years)):
        try:
            flows = comtrade.fetch_flows(hs_code=entry.code, year=year, flow="M")
        except UpstreamError as exc:
            return ConcentrationRiskResult(
                status="error", hs_code=entry.code, errors=[_upstream_error(exc)]
            )
        if flows.fetch.mode == "replay":
            data_mode = "fixture"
        if not flows.records:
            continue
        total = sum(r.value_usd for r in flows.records)
        top = max(flows.records, key=lambda r: r.value_usd)
        observations.append(
            YearObservation(
                year=year,
                total_value_usd=round(total, 2),
                top_partner_iso3=reference.partner_iso3(top.partner_code),
                top_partner_share_pct=round(top.value_usd / total * 100.0, 2) if total else None,
            )
        )
        if latest_year is None or year >= latest_year:
            latest_year, latest_records = year, flows.records

    # The mirror check must stay on the annual basis whatever concentration uses:
    # partner export reports are annual, and comparing a rolling twelve-month
    # import figure against a calendar-year export figure would produce a gap
    # that is an artefact of the mismatched periods.
    annual_records = list(latest_records)

    # The annual loop is kept for the volatility series -- three annual points are
    # cheap and structural -- but when a window is requested, concentration itself
    # is measured on the window, because that is the figure the user acts on.
    basis_label = str(latest_year) if latest_year else None
    window_note = ""
    if trailing_12m_to:
        window_end, window_error = _resolve_window_end(trailing_12m_to)
        if window_error:
            return ConcentrationRiskResult(
                status="error",
                hs_code=entry.code,
                errors=[_err(ErrorCode.INVALID_ARGUMENT, window_error, "trailing_12m_to")],
            )
        try:
            window, covered, empty = comtrade.fetch_trailing_window(
                hs_code=entry.code, end_period=window_end or ""
            )
        except UpstreamError as exc:
            return ConcentrationRiskResult(
                status="error", hs_code=entry.code, errors=[_upstream_error(exc)]
            )
        if window.records:
            latest_records = window.records
            basis_label = f"{covered[0]}-{covered[-1]}" if covered else trailing_12m_to
            if window.fetch.mode == "replay":
                data_mode = "fixture"
            window_note = (
                f" Concentration is measured over the rolling twelve months {basis_label}; "
                f"volatility comes from the annual series "
                f"{', '.join(str(o.year) for o in observations)}, which is the only basis long "
                f"enough to measure it."
            )
            if empty:
                window_note += f" {len(empty)} month(s) in the window are unpublished and excluded."

    provenance = Provenance(
        source="UN Comtrade",
        mode="fixture" if data_mode == "fixture" else "live",
        as_of=basis_label,
        measurement="measured",
    )

    if not latest_records:
        return ConcentrationRiskResult(
            status="empty",
            hs_code=entry.code,
            provenance=provenance,
            interpretation=(
                f"UN Comtrade reported no imports of HS {entry.code} in {', '.join(map(str, sorted(set(years))))}."
            ),
        )

    stats = analysis.herfindahl([r.value_usd for r in latest_records])
    flags: list[RiskFlag] = []
    top_record = max(latest_records, key=lambda r: r.value_usd)

    if stats:
        if stats.partner_count < analysis.THIN_DATA_PARTNER_COUNT:
            flags.append(RiskFlag.THIN_DATA)
        if stats.top_share_pct >= top_partner_threshold_pct:
            flags.append(RiskFlag.SINGLE_SOURCE)
        if stats.hhi >= analysis.HHI_HIGH:
            flags.append(RiskFlag.HIGH_CONCENTRATION)
        elif stats.hhi >= analysis.HHI_MODERATE:
            flags.append(RiskFlag.MODERATE_CONCENTRATION)

    volatility = analysis.yoy_volatility_pct([(o.year, o.total_value_usd) for o in observations])
    if volatility is not None and volatility >= analysis.VOLATILITY_PCT:
        flags.append(RiskFlag.VOLATILE_SUPPLY)

    gap: float | None = None
    mirror_note = ""
    if latest_year is not None and annual_records:
        top_partners = annual_records[:MIRROR_TOP_PARTNERS]
        mirror = comtrade.fetch_reported_exports_to_ukraine(
            hs_code=entry.code,
            year=latest_year,
            partner_codes=[r.partner_code for r in top_partners],
        )
        # Compare like with like: only partners that report to Comtrade at all.
        comparable = [r for r in top_partners if r.partner_code in mirror.reported_by_partner_usd]
        if comparable:
            own_total = sum(r.value_usd for r in comparable)
            their_total = sum(mirror.reported_by_partner_usd[r.partner_code] for r in comparable)
            gap = analysis.mirror_gap_pct(own_total, their_total)
            mirror_note = (
                f"Mirror check covers the {len(comparable)} largest origins that report to Comtrade, "
                f"on the {latest_year} annual basis so both sides cover the same period"
                + (f"; {len(mirror.partners_silent)} did not report and were excluded" if mirror.partners_silent else "")
                + "."
            )
            if analysis.mirror_gap_is_suspicious(gap):
                flags.append(RiskFlag.MIRROR_DISCREPANCY)
        else:
            mirror_note = (
                "No top origin reported its own exports to Ukraine for this product, so no mirror "
                "comparison was possible."
            )

    pieces: list[str] = []
    if stats:
        pieces.append(
            f"{stats.partner_count} origins reported in {basis_label}; HHI {stats.hhi:.0f} "
            f"(equivalent to {stats.effective_partner_count:.1f} equally sized origins). "
            f"{reference.partner_name(top_record.partner_code)} holds {stats.top_share_pct:.1f} percent."
        )
    if volatility is not None:
        pieces.append(f"Year-over-year value swings have a standard deviation of {volatility:.1f} percent.")
    elif len(observations) < 3:
        pieces.append("Fewer than three years supplied, so volatility was not computed.")
    if gap is not None:
        pieces.append(
            f"Partners reported {gap:+.1f} percent versus Ukraine's own figure. Exports are valued "
            f"FOB and imports CIF, so a shortfall of roughly "
            f"{analysis.MIRROR_GAP_NORMAL_PCT:.0f} percent is expected; this is flagged only above "
            f"+{analysis.MIRROR_GAP_OVER_PCT:.0f} percent or below "
            f"-{analysis.MIRROR_GAP_UNDER_PCT:.0f} percent."
        )
    if mirror_note:
        pieces.append(mirror_note)
    if window_note:
        pieces.append(window_note.strip())
    if not flags:
        pieces.append("No risk threshold was crossed.")

    return ConcentrationRiskResult(
        status="ok",
        hs_code=entry.code,
        hhi=stats.hhi if stats else None,
        top_partner_iso3=reference.partner_iso3(top_record.partner_code),
        top_partner_name=reference.partner_name(top_record.partner_code),
        top_partner_share_pct=stats.top_share_pct if stats else None,
        effective_partner_count=stats.effective_partner_count if stats else None,
        yoy_volatility_pct=volatility,
        mirror_gap_pct=gap,
        observations=observations,
        flags=flags,
        interpretation=" ".join(pieces),
        provenance=provenance,
    )


def main() -> None:
    """Entry point: serve over stdio."""
    import sys

    print(
        f"trade-sourcing-mcp starting (transport=stdio, data mode={current_mode()})",
        file=sys.stderr,
        flush=True,
    )
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
