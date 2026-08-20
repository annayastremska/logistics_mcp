"""Input and output contracts for the trade-sourcing MCP server.

Every tool takes typed arguments and returns one of the ``*Result`` models below.
The MCP SDK derives each tool's ``inputSchema`` from the argument annotations and
its ``outputSchema`` from the return annotation, so these models *are* the
published contract.

Error convention
----------------
Every result model carries a ``status`` discriminator:

* ``ok``    - the call succeeded and carries data.
* ``empty`` - the call succeeded and the source genuinely holds no matching
  records. This is **not** a failure; ``notes`` explains why.
* ``error`` - the call failed. ``errors`` is non-empty and every entry carries a
  machine-readable ``code``.

This keeps "no trade was reported for that period" distinguishable from
"the upstream API rate-limited us", which a bare empty list could not express.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

Status = Literal["ok", "empty", "error"]


class ErrorCode(str, Enum):
    """Machine-readable failure reasons shared by every tool."""

    UNKNOWN_HS_CODE = "UNKNOWN_HS_CODE"
    UNKNOWN_COUNTRY = "UNKNOWN_COUNTRY"
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    YEAR_NOT_AVAILABLE = "YEAR_NOT_AVAILABLE"
    AGGREGATION_TOO_COARSE = "AGGREGATION_TOO_COARSE"
    RATE_LIMITED = "RATE_LIMITED"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    UPSTREAM_MALFORMED = "UPSTREAM_MALFORMED"
    FIXTURE_MISSING = "FIXTURE_MISSING"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class ToolErrorDetail(BaseModel):
    """One failure reason. Tools may report several at once (e.g. validation)."""

    code: ErrorCode = Field(description="Machine-readable failure reason.")
    message: str = Field(description="Human-readable explanation of the failure.")
    field: str | None = Field(
        default=None,
        description="Input field the error refers to, when the failure is input-related.",
    )


class Provenance(BaseModel):
    """Where a returned number came from. Attached to every data-bearing result."""

    source: Literal["UN Comtrade", "World Bank", "WITS TRAINS", "local reference", "model"] = Field(
        description="Origin of the values in this result."
    )
    mode: Literal["live", "fixture"] = Field(
        description="Whether the values came from a live HTTP call or a recorded fixture."
    )
    retrieved_at: str | None = Field(
        default=None,
        description="ISO-8601 timestamp of the underlying HTTP response, when known.",
    )
    as_of: str | None = Field(
        default=None,
        description="Reference period the data describes, e.g. '2024' or '2022'.",
    )
    measurement: Literal["measured", "estimated"] = Field(
        default="measured",
        description=(
            "'measured' for values reported by the source; 'estimated' for values this "
            "server modelled (notably freight cost, which no open source publishes)."
        ),
    )


# --------------------------------------------------------------------------- #
# 1. validate_sourcing_brief
# --------------------------------------------------------------------------- #


class NormalizedBrief(BaseModel):
    """A sourcing request resolved against the HS2022 nomenclature."""

    hs_code: str = Field(description="Resolved HS code, 2, 4 or 6 digits.")
    hs_description: str = Field(description="Official HS2022 description of that code.")
    hs_level: Literal["chapter", "heading", "subheading"] = Field(
        description="Aggregation level implied by the code length."
    )
    supports_unit_price: bool = Field(
        description=(
            "True only at heading/subheading level. Comtrade reports zero net weight for "
            "chapter-level aggregates, so USD/kg cannot be computed there."
        )
    )
    target_volume_kg: float = Field(description="Echoed target volume in kilograms.")
    year: int = Field(description="Reference year the request resolved to.")
    candidate_countries: list[str] = Field(
        description="Validated candidate origins as ISO3 codes; empty means 'discover from the data'."
    )


class ValidateBriefResult(BaseModel):
    """Result of validating and normalizing a sourcing brief."""

    status: Status
    normalized_brief: NormalizedBrief | None = Field(
        default=None, description="Present when status is 'ok'."
    )
    hs_candidates: list[dict[str, str]] = Field(
        default_factory=list,
        description=(
            "When a product name matched several HS codes, the ranked candidates as "
            "{'hs_code': ..., 'description': ...}. Present when status is 'empty' or ambiguous."
        ),
    )
    warnings: list[str] = Field(
        default_factory=list, description="Non-fatal observations the caller should surface."
    )
    errors: list[ToolErrorDetail] = Field(
        default_factory=list, description="Non-empty when status is 'error'."
    )


# --------------------------------------------------------------------------- #
# 2. get_import_flows
# --------------------------------------------------------------------------- #


class FlowRow(BaseModel):
    """One origin country's trade in the requested product and period."""

    partner_iso3: str = Field(description="Origin country, ISO3.")
    partner_name: str = Field(description="Origin country name.")
    net_weight_kg: float | None = Field(
        description="Net weight in kg, or null when the source did not report weight."
    )
    value_usd: float = Field(description="Trade value in USD (CIF for imports, FOB for exports).")
    unit_price_usd_per_kg: float | None = Field(
        description=(
            "value_usd / net_weight_kg. Null when weight is missing. This is a unit value, "
            "not a quoted market price."
        )
    )
    share_of_total_pct: float = Field(description="Share of the period total, percent.")


class ImportFlowsResult(BaseModel):
    """Reported trade flows for one product and period."""

    status: Status
    rows: list[FlowRow] = Field(
        default_factory=list, description="Origin countries, descending by value."
    )
    total_value_usd: float = Field(default=0.0, description="Sum of value_usd across all origins.")
    total_net_weight_kg: float | None = Field(
        default=None, description="Sum of net_weight_kg, or null when weight is unreported."
    )
    partner_count: int = Field(default=0, description="Number of distinct origins after dedup.")
    rows_dropped_as_duplicates: int = Field(
        default=0,
        description=(
            "Rows collapsed during deduplication. Comtrade repeats a partner across customs "
            "and mode-of-transport dimensions; ignoring this double-counts shares."
        ),
    )
    truncated: bool = Field(
        default=False,
        description="True when the upstream 500-record cap may have cut the result short.",
    )
    provenance: Provenance | None = None
    notes: list[str] = Field(default_factory=list, description="Caveats about this result.")
    errors: list[ToolErrorDetail] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# 3. estimate_landed_cost
# --------------------------------------------------------------------------- #

TransportMode = Literal["sea", "road", "rail", "air"]


class CostComponent(BaseModel):
    """One line of the landed-cost build-up."""

    label: str = Field(description="Name of the cost component.")
    amount_usd: float = Field(description="Amount in USD for the whole shipment.")
    basis: str = Field(description="How the amount was derived.")
    measurement: Literal["measured", "estimated"] = Field(
        description="'measured' if sourced from data, 'estimated' if modelled by this server."
    )


class LandedCostResult(BaseModel):
    """Modelled landed cost for one origin, product and volume."""

    status: Status
    origin_iso3: str | None = None
    hs_code: str | None = None
    volume_kg: float | None = None
    transport_mode: TransportMode | None = None
    components: list[CostComponent] = Field(
        default_factory=list, description="Ordered cost build-up; components sum to total."
    )
    total_landed_cost_usd: float | None = None
    cost_per_kg_usd: float | None = None
    duty_rate_pct: float | None = Field(
        default=None, description="Applied import duty rate used in the calculation."
    )
    duty_basis: Literal["MFN"] | None = Field(
        default=None,
        description=(
            "Always 'MFN'. WITS exposes most-favoured-nation rates only; preferential rates "
            "returned HTTP 404 for every partner tested."
        ),
    )
    fta_preference_possible: bool = Field(
        default=False,
        description=(
            "True when a free-trade agreement plausibly reduces the duty below the MFN rate "
            "(e.g. the EU DCFTA). The real rate must be confirmed manually."
        ),
    )
    distance_km: float | None = Field(
        default=None, description="Great-circle distance from the origin used for freight modelling."
    )
    confidence: Literal["low", "medium"] | None = Field(
        default=None,
        description="Never 'high': the freight component is modelled, not quoted.",
    )
    assumptions: list[str] = Field(
        default_factory=list, description="Every assumption behind the modelled components."
    )
    provenance: Provenance | None = None
    errors: list[ToolErrorDetail] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# 4. rank_sourcing_countries
# --------------------------------------------------------------------------- #


class CriterionWeights(BaseModel):
    """Weights of the composite sourcing score. Must sum to 1.0 (±0.001)."""

    price: float = Field(default=0.40, ge=0.0, le=1.0, description="Weight of landed cost per kg.")
    logistics: float = Field(
        default=0.30, ge=0.0, le=1.0, description="Weight of the World Bank LPI."
    )
    duty: float = Field(default=0.15, ge=0.0, le=1.0, description="Weight of the MFN duty rate.")
    supply: float = Field(
        default=0.15,
        ge=0.0,
        le=1.0,
        description="Weight of demonstrated supply capacity (share of reported trade).",
    )


class FactorContribution(BaseModel):
    """How one criterion moved one country's score."""

    criterion: Literal["price", "logistics", "duty", "supply"]
    raw_value: float | None = Field(description="Underlying value before normalization.")
    normalized: float | None = Field(description="Min-max normalized to 0..1, higher is better.")
    weight: float = Field(description="Weight applied to this criterion.")
    contribution: float = Field(description="normalized x weight x 100, in score points.")


class RankedCountry(BaseModel):
    """One scored candidate origin."""

    rank: int = Field(description="1 is best.")
    iso3: str
    name: str
    score: float = Field(description="Composite score, 0..100.")
    scored_weight_pct: float = Field(
        default=100.0,
        description=(
            "Share of the total criterion weight that could actually be scored, percent. Below "
            "100 the score is not comparable with a fully scored candidate: an unscorable "
            "criterion contributes nothing, so a missing input depresses the score exactly like "
            "a bad one. Read the score against this number, not on its own."
        ),
    )
    unscored_criteria: list[str] = Field(
        default_factory=list,
        description="Criteria with no value for this candidate, named so the gap is not silent.",
    )
    factors: list[FactorContribution] = Field(
        description="Per-criterion decomposition; contributions sum to score."
    )
    landed_cost_per_kg_usd: float | None = None
    lpi_overall: float | None = None
    duty_rate_pct: float | None = None
    supply_share_pct: float | None = None
    price_basis: Literal["reported", "caller_supplied", "caller_override"] | None = Field(
        default=None,
        description=(
            "Where the unit value came from. 'reported' is derived from trade this origin "
            "actually did with the importer. 'caller_supplied' is a figure the caller passed in "
            "for an origin with no reported trade -- the only way to cost it at all. "
            "'caller_override' is a figure the caller passed in for an origin that does report "
            "trade, so a measured unit value was available and was displaced; legitimate when the "
            "reported one is too thin to trust, but never quote either as an observation."
        ),
    )


class RankingResult(BaseModel):
    """Ranked shortlist of candidate origins."""

    status: Status
    ranking: list[RankedCountry] = Field(default_factory=list)
    weights_used: CriterionWeights | None = None
    excluded: list[dict[str, str]] = Field(
        default_factory=list,
        description="Candidates dropped before scoring, as {'iso3': ..., 'reason': ...}.",
    )
    caveats: list[str] = Field(
        default_factory=list,
        description="Why the ranking must not be read as a procurement decision.",
    )
    provenance: Provenance | None = None
    errors: list[ToolErrorDetail] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# 5. assess_supply_concentration_risk
# --------------------------------------------------------------------------- #


class RiskFlag(str, Enum):
    """Named risk conditions this tool can raise."""

    SINGLE_SOURCE = "SINGLE_SOURCE"
    HIGH_CONCENTRATION = "HIGH_CONCENTRATION"
    MODERATE_CONCENTRATION = "MODERATE_CONCENTRATION"
    VOLATILE_SUPPLY = "VOLATILE_SUPPLY"
    MIRROR_DISCREPANCY = "MIRROR_DISCREPANCY"
    THIN_DATA = "THIN_DATA"


class YearObservation(BaseModel):
    """Per-year totals used for the volatility calculation."""

    year: int
    total_value_usd: float
    top_partner_iso3: str | None
    top_partner_share_pct: float | None


class ConcentrationRiskResult(BaseModel):
    """Concentration, volatility and mirror-gap assessment for one product."""

    status: Status
    hs_code: str | None = None
    hhi: float | None = Field(
        default=None,
        description=(
            "Herfindahl-Hirschman index over partner value shares, 0..10000. Competition "
            "authorities treat >2500 as highly concentrated; borrowed here as a supply-risk proxy."
        ),
    )
    top_partner_iso3: str | None = None
    top_partner_name: str | None = None
    top_partner_share_pct: float | None = None
    effective_partner_count: float | None = Field(
        default=None, description="10000 / HHI: the equivalent number of equally sized origins."
    )
    yoy_volatility_pct: float | None = Field(
        default=None,
        description="Standard deviation of year-over-year change in total value, percent.",
    )
    mirror_gap_pct: float | None = Field(
        default=None,
        description=(
            "(partner-reported exports - Ukraine-reported imports) / Ukraine-reported imports, "
            "percent. A gap of roughly 10-20 percent is normal because imports are valued CIF "
            "and exports FOB; larger gaps warrant a look."
        ),
    )
    observations: list[YearObservation] = Field(default_factory=list)
    flags: list[RiskFlag] = Field(default_factory=list)
    interpretation: str = Field(default="", description="Plain-language reading of the numbers.")
    provenance: Provenance | None = None
    errors: list[ToolErrorDetail] = Field(default_factory=list)
