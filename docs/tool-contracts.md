# Tool Contracts

Contracts for the five tools exposed by the custom server `trade-sourcing-mcp`, and for the
tool used from the existing Playwright MCP server.

Schemas here are the published MCP contracts, generated from the Pydantic models in
`mcp_server/models.py`. To print them from the running server:

```bash
python scripts/inspect_tools.py --json
```

## Conventions shared by all five custom tools

**Error model.** Every result carries a `status` discriminator, which is how a caller tells a
failure from a legitimately empty answer:

| `status` | Meaning | `errors` |
|---|---|---|
| `ok` | Succeeded, data present | empty |
| `empty` | Succeeded; the source genuinely holds no matching record. **Not a failure** — retrying will not help | empty |
| `error` | The call failed | non-empty, each entry with a machine-readable `code` |

Failures are returned **in band** as structured data rather than raised as MCP protocol
errors. The reasoning is in [`design-rationale.md`](design-rationale.md#in-band-errors).

**Error codes.** `UNKNOWN_HS_CODE`, `UNKNOWN_COUNTRY`, `INVALID_ARGUMENT`,
`YEAR_NOT_AVAILABLE`, `AGGREGATION_TOO_COARSE`, `RATE_LIMITED`, `UPSTREAM_UNAVAILABLE`,
`UPSTREAM_MALFORMED`, `FIXTURE_MISSING`, `INSUFFICIENT_DATA`.

**Provenance.** Every data-bearing result carries a `provenance` object: `source`, `mode`
(`live` or `fixture`), `retrieved_at`, `as_of`, and `measurement` — `measured` for a value the
source reported, `estimated` for a value this server modelled.

**Annotations.** All five tools are `readOnlyHint: true`, `destructiveHint: false`,
`idempotentHint: true`. `validate_sourcing_brief` is `openWorldHint: false` (offline);
the other four are `openWorldHint: true`.

---

## 1. `validate_sourcing_brief`

| Element | Content |
|---|---|
| **Name** | `validate_sourcing_brief` |
| **Purpose** | Turn a vague sourcing request into the exact `hs_code` and `year` the other tools need, and reject an unresolvable one before any API call is spent. Call it first in any flow. |
| **Model-facing description** | "Resolve and validate a sourcing request before any data is fetched. Accepts either an HS commodity code or a free-text product name, checks it against the HS2022 nomenclature, validates candidate origin countries, and reports whether the requested aggregation level supports a price-per-kg comparison. Call this first: it turns a vague request into the exact hs_code and year the other tools need, and it fails fast on an unknown code without spending an API call. When a product name matches several codes it returns ranked candidates instead of guessing." |

**Input schema**

| Field | Type | Required | Constraints | Default |
|---|---|---|---|---|
| `target_volume_kg` | number | **yes** | `> 0` | — |
| `hs_code` | string \| null | no | 2, 4 or 6 digits; must exist in HS2022 | `null` |
| `product_query` | string \| null | no | ≥ 3 characters | `null` |
| `candidate_countries` | array\<string\> \| null | no | ≤ 10 items; ISO3 codes or country names | `null` |
| `year` | integer \| null | no | 2015–2030 | current year − 2 |

At least one of `hs_code` or `product_query` must be supplied.

**Output schema**

| Field | Type | Meaning |
|---|---|---|
| `status` | `"ok"` \| `"empty"` \| `"error"` | See conventions above |
| `normalized_brief` | object \| null | Present when `ok`. Fields: `hs_code`, `hs_description`, `hs_level` (`chapter`/`heading`/`subheading`), `supports_unit_price`, `target_volume_kg`, `year`, `candidate_countries` |
| `hs_candidates` | array\<{`hs_code`, `description`}\> | Ranked candidates when a name or code was ambiguous or unknown |
| `warnings` | array\<string\> | Non-fatal observations to surface to the user |
| `errors` | array\<ToolErrorDetail\> | Non-empty when `error` |

**Error conditions**

| Condition | Representation |
|---|---|
| Neither `hs_code` nor `product_query` given | `status: error`, `INVALID_ARGUMENT` on field `hs_code` |
| Code is not 2/4/6 digits | `status: error`, `INVALID_ARGUMENT` |
| Code is well-formed but absent from HS2022 | `status: error`, `UNKNOWN_HS_CODE`, plus `hs_candidates` |
| A candidate country cannot be resolved | `status: error`, `UNKNOWN_COUNTRY` on field `candidate_countries` |
| Product name matches nothing | `status: empty` with an explanatory warning |
| Product name matches several codes | `status: empty` with `hs_candidates` populated |

**Side effects** — none. Reads only the vendored reference files; makes no network call.

**Example**

```json
// in
{"hs_code": "080610", "target_volume_kg": 120000, "candidate_countries": ["TUR", "IND", "MDA"], "year": 2024}

// out
{
  "status": "ok",
  "normalized_brief": {
    "hs_code": "080610",
    "hs_description": "Fruit, edible; grapes, fresh",
    "hs_level": "subheading",
    "supports_unit_price": true,
    "target_volume_kg": 120000.0,
    "year": 2024,
    "candidate_countries": ["TUR", "IND", "MDA"]
  },
  "hs_candidates": [], "warnings": [], "errors": []
}
```

Invalid input, for contrast:

```json
// in
{"hs_code": "123456", "target_volume_kg": 1000}

// out
{"status": "error", "errors": [
  {"code": "UNKNOWN_HS_CODE", "message": "123456 is not a code in the HS2022 nomenclature.", "field": "hs_code"}
]}
```

---

## 2. `get_import_flows` — primary data-source tool

| Element | Content |
|---|---|
| **Name** | `get_import_flows` |
| **Purpose** | Discover which countries actually supplied a product, rather than assuming. This is the tool that reaches the project's primary data source. |
| **Model-facing description** | "Fetch which countries actually supplied a product to Ukraine in a given year, from UN Comtrade. Returns each origin's weight, value, unit value per kg and share of the total, sorted by value. Use this to discover real suppliers rather than assuming them. Set flow_direction='mirror_export' to instead read what partner countries reported exporting to Ukraine, which is the input to a mirror-gap check. Duplicate rows in the source are collapsed and reporting aggregates such as 'World' are excluded before shares are computed. status='empty' means Comtrade holds no record for that product and year, which is a real answer, not a failure." |

**Input schema**

| Field | Type | Required | Constraints | Default |
|---|---|---|---|---|
| `hs_code` | string | **yes** | 2–6 characters; must exist in HS2022 | — |
| `year` | integer | **yes** | 2015–2030 | — |
| `flow_direction` | string | no | `import` \| `mirror_export` | `import` |
| `top_n` | integer | no | 1–50 | 10 |
| `partner_iso3` | string \| null | no | Required when `flow_direction` is `mirror_export` | `null` |

**Output schema**

| Field | Type | Meaning |
|---|---|---|
| `status` | enum | See conventions |
| `rows` | array\<FlowRow\> | `partner_iso3`, `partner_name`, `net_weight_kg`, `value_usd`, `unit_price_usd_per_kg`, `share_of_total_pct`; descending by value |
| `total_value_usd` | number | Sum across all origins, not only the returned `top_n` |
| `total_net_weight_kg` | number \| null | Null when the source reported no weight |
| `partner_count` | integer | Distinct origins after deduplication |
| `rows_dropped_as_duplicates` | integer | Rows collapsed on the `partner2Code` dimension |
| `truncated` | boolean | True when the 500-record upstream cap may have cut the result |
| `provenance` | object \| null | Source, live/fixture, timestamp, period |
| `notes` | array\<string\> | Caveats about this specific result |
| `errors` | array\<ToolErrorDetail\> | Non-empty when `error` |

**Error conditions**

| Condition | Representation |
|---|---|
| Unknown HS code | `status: error`, `UNKNOWN_HS_CODE` |
| `flow_direction` not one of the two values | `status: error`, `INVALID_ARGUMENT` |
| `mirror_export` without `partner_iso3` | `status: error`, `INVALID_ARGUMENT` |
| Comtrade rate-limited the call (HTTP 429 after retries) | `status: error`, `RATE_LIMITED` |
| Comtrade unreachable or non-JSON | `status: error`, `UPSTREAM_UNAVAILABLE` / `UPSTREAM_MALFORMED` |
| Replay mode with no fixture for the query | `status: error`, `FIXTURE_MISSING` |
| No records reported for that product and year | **`status: empty`** with an explanatory note |

**Side effects** — one outbound HTTPS GET to `comtradeapi.un.org`, throttled to one request
per second. Writes a cache entry under `.cache/`, and in `record` mode a fixture under
`fixtures/`. No writes anywhere else.

**Example** (recorded 2026-08-19, live)

```json
// in
{"hs_code": "080610", "year": 2024, "top_n": 3}

// out (abridged)
{
  "status": "ok",
  "rows": [
    {"partner_iso3": "TUR", "partner_name": "Türkiye", "net_weight_kg": 21036558.0,
     "value_usd": 27833369.0, "unit_price_usd_per_kg": 1.3231, "share_of_total_pct": 64.8},
    {"partner_iso3": "MDA", "partner_name": "Rep. of Moldova", "net_weight_kg": 5394236.0,
     "value_usd": 6806765.0, "unit_price_usd_per_kg": 1.2618, "share_of_total_pct": 15.85},
    {"partner_iso3": "IND", "partner_name": "India", "net_weight_kg": 730600.0,
     "value_usd": 1798869.0, "unit_price_usd_per_kg": 2.4622, "share_of_total_pct": 4.19}
  ],
  "total_value_usd": 42951507.0,
  "partner_count": 20,
  "rows_dropped_as_duplicates": 21,
  "truncated": false,
  "provenance": {"source": "UN Comtrade", "mode": "live", "as_of": "2024", "measurement": "measured"},
  "notes": ["21 duplicate rows collapsed on the partner2Code dimension (country of origin vs consignment); the source repeats every partner."]
}
```

---

## 3. `estimate_landed_cost`

| Element | Content |
|---|---|
| **Name** | `estimate_landed_cost` |
| **Purpose** | Cost one candidate origin so origins can be compared on total delivered cost rather than goods price alone. |
| **Model-facing description** | "Build up the landed cost of importing a given volume from one origin country: goods value, cargo insurance, the applied MFN import duty from WITS assessed on the CIF value, and modelled freight for the chosen transport mode. Returns an itemised breakdown where each line is labelled 'measured' or 'estimated', because no open source publishes freight rates and that component is modelled from distance. The duty is always the MFN rate; when a free-trade agreement such as the EU DCFTA plausibly applies, fta_preference_possible is set so the caller knows the real rate may be lower. Use it to compare origins on cost, not to quote a shipment." |

**Input schema**

| Field | Type | Required | Constraints | Default |
|---|---|---|---|---|
| `hs_code` | string | **yes** | 4 or 6 digits | — |
| `origin_iso3` | string | **yes** | exactly 3 characters | — |
| `volume_kg` | number | **yes** | `> 0` | — |
| `transport_mode` | string | no | `sea` \| `road` \| `rail` \| `air` | `road` |
| `year` | integer \| null | no | 2015–2030 | current year − 2 |
| `unit_price_usd_per_kg` | number \| null | no | `> 0`; overrides the Comtrade unit value | `null` |

**Output schema**

| Field | Type | Meaning |
|---|---|---|
| `status` | enum | See conventions |
| `components` | array\<CostComponent\> | `label`, `amount_usd`, `basis`, `measurement`; the lines sum to `total_landed_cost_usd` |
| `total_landed_cost_usd` | number \| null | Total for the consignment |
| `cost_per_kg_usd` | number \| null | Total divided by volume |
| `duty_rate_pct` | number \| null | Rate used in the calculation |
| `duty_basis` | `"MFN"` \| null | Always MFN; WITS exposes nothing else |
| `fta_preference_possible` | boolean | True when an agreement plausibly undercuts the MFN rate |
| `distance_km` | number \| null | Great-circle distance used for the freight model |
| `confidence` | `"low"` \| `"medium"` \| null | Never `high`: freight is modelled |
| `assumptions` | array\<string\> | Every assumption behind the modelled lines |
| `provenance` | object \| null | `measurement` is `estimated` for this tool |

**Error conditions**

| Condition | Representation |
|---|---|
| Unknown HS code or country | `status: error`, `UNKNOWN_HS_CODE` / `UNKNOWN_COUNTRY` |
| `transport_mode` outside the four values | `status: error`, `INVALID_ARGUMENT` |
| No reference coordinates for the origin | `status: error`, `INSUFFICIENT_DATA` |
| Comtrade unavailable | `status: error`, `RATE_LIMITED` / `UPSTREAM_UNAVAILABLE` |
| No weighted trade to derive a unit value from | **`status: empty`**, with guidance to pass `unit_price_usd_per_kg` |
| WITS holds no rate, or the lookup fails | `status: ok` with `duty_rate_pct: 0.0` and an explicit assumption saying the total is a lower bound |

**Side effects** — up to one Comtrade GET and up to four WITS GETs (the requested year plus
fallback years). Cache and fixture writes as above. No other writes.

**Example** (recorded live; Türkiye → Ukraine, grapes, 120 t by road)

```json
// in
{"hs_code": "080610", "origin_iso3": "TUR", "volume_kg": 120000, "transport_mode": "road", "year": 2024}

// out (abridged)
{
  "status": "ok",
  "origin_iso3": "TUR", "hs_code": "080610", "volume_kg": 120000.0, "transport_mode": "road",
  "components": [
    {"label": "Goods value", "amount_usd": 158790.73, "basis": "unit value x volume", "measurement": "measured"},
    {"label": "Freight (reference only, already inside the CIF unit value)", "amount_usd": 0.0,
     "basis": "modelled 17046.00 USD, excluded to avoid double counting", "measurement": "estimated"},
    {"label": "Import duty", "amount_usd": 15879.07,
     "basis": "10.00% MFN on the CIF value of 158790.73 USD", "measurement": "measured"},
    {"label": "Customs brokerage", "amount_usd": 120.0, "basis": "flat per consignment", "measurement": "estimated"}
  ],
  "total_landed_cost_usd": 174789.80, "cost_per_kg_usd": 1.4566,
  "duty_rate_pct": 10.0, "duty_basis": "MFN", "fta_preference_possible": true,
  "distance_km": 1183.9, "confidence": "medium"
}
```

---

## 4. `rank_sourcing_countries`

| Element | Content |
|---|---|
| **Name** | `rank_sourcing_countries` |
| **Purpose** | Turn several candidate origins into a defensible ranked shortlist, with the reasoning exposed rather than hidden inside a single number. |
| **Model-facing description** | "Score and rank candidate origin countries for one product against four criteria: landed cost per kg, World Bank Logistics Performance Index, applied MFN duty, and demonstrated supply capacity measured as share of reported trade. Each criterion is min-max normalized across the candidates and weighted, and every country's score comes back decomposed into per-criterion contributions that sum to the score, so a ranking can be argued with rather than taken on trust. Weights are caller-supplied and must sum to 1. Call this after get_import_flows has established who the real candidates are." |

**Input schema**

| Field | Type | Required | Constraints | Default |
|---|---|---|---|---|
| `hs_code` | string | **yes** | 4 or 6 digits | — |
| `candidates` | array\<string\> | **yes** | 2–10 ISO3 codes | — |
| `volume_kg` | number | **yes** | `> 0` | — |
| `year` | integer \| null | no | 2015–2030 | current year − 2 |
| `transport_mode` | string | no | `sea` \| `road` \| `rail` \| `air` | `road` |
| `weights` | object \| null | no | `price`, `logistics`, `duty`, `supply`, each 0–1, **summing to 1.0 ± 0.001** | `0.40 / 0.30 / 0.15 / 0.15` |
| `unit_prices` | object \| null | no | Proxy unit values in USD/kg, keyed by candidate ISO3, each `> 0` | none |

**Output schema**

| Field | Type | Meaning |
|---|---|---|
| `status` | enum | See conventions |
| `ranking` | array\<RankedCountry\> | `rank`, `iso3`, `name`, `score` (0–100), `factors`, and the raw `landed_cost_per_kg_usd`, `lpi_overall`, `duty_rate_pct`, `supply_share_pct` |
| `ranking[].price_basis` | enum \| null | `reported` when the unit value was derived from trade this origin actually did with the importer; `caller_supplied` when it came from `unit_prices`; `null` when the cost could not be established at all |
| `ranking[].factors` | array\<FactorContribution\> | Per criterion: `raw_value`, `normalized` (0–1), `weight`, `contribution`. Contributions sum to `score` |
| `weights_used` | object \| null | Weights actually applied |
| `excluded` | array\<{`iso3`, `reason`}\> | Candidates dropped before scoring |
| `caveats` | array\<string\> | Why the ranking is not a decision |

### Pricing an origin that does not ship here yet

A unit value can only be derived from trade that happened, so a candidate with no reported
trade to the importer has no price and no duty — and because an unscorable criterion
contributes nothing, it ranks last for missing data rather than on merit. Measured: an origin
added precisely because the shortlist needed widening scored **1.33 out of 100 on half the
weight**.

`unit_prices` is the way out. Pass the same proxy used for `estimate_landed_cost`, and the
candidate is scored on the full weight. A figure passed for an origin that *does* report trade
overrides the derived unit value — legitimate when the reported one is thin, and marked the
same way. The result never lets a supplied figure pass for an observation: the row carries
`price_basis: "caller_supplied"`, and a caveat names every origin priced that way.

**Error conditions**

| Condition | Representation |
|---|---|
| Weights do not sum to 1.0 | `status: error`, `INVALID_ARGUMENT` on field `weights`, message states the actual sum |
| Weights object malformed | `status: error`, `INVALID_ARGUMENT` |
| Unknown HS code | `status: error`, `UNKNOWN_HS_CODE` |
| Fewer than two resolvable candidates | `status: error`, `INSUFFICIENT_DATA`, with `excluded` populated |
| Comtrade unavailable | `status: error`, `RATE_LIMITED` / `UPSTREAM_UNAVAILABLE` |
| World Bank unavailable | `status: ok`; the logistics criterion normalizes to `null` and a caveat is added — a missing criterion is not fatal |

**Side effects** — one Comtrade GET for supply shares, one World Bank GET for LPI, plus the
per-candidate calls made by `estimate_landed_cost`. Read-only.

**Example** (recorded live; grapes, 120 t, default weights)

```json
// in
{"hs_code": "080610", "candidates": ["TUR", "IND", "MDA"], "volume_kg": 120000, "year": 2024}

// out (abridged)
{
  "status": "ok",
  "ranking": [
    {"rank": 1, "iso3": "TUR", "name": "Türkiye", "score": 90.44,
     "landed_cost_per_kg_usd": 1.3243, "lpi_overall": 3.4, "duty_rate_pct": 10.0, "supply_share_pct": 64.802,
     "factors": [
       {"criterion": "price", "raw_value": 1.3243, "normalized": 0.9484, "weight": 0.4, "contribution": 37.94},
       {"criterion": "logistics", "raw_value": 3.4, "normalized": 1.0, "weight": 0.3, "contribution": 30.0},
       {"criterion": "duty", "raw_value": 10.0, "normalized": 0.5, "weight": 0.15, "contribution": 7.5},
       {"criterion": "supply", "raw_value": 64.802, "normalized": 1.0, "weight": 0.15, "contribution": 15.0}
     ]},
    {"rank": 2, "iso3": "MDA", "name": "Rep. of Moldova", "score": 50.39, "...": "..."},
    {"rank": 3, "iso3": "IND", "name": "India", "score": 37.5, "...": "..."}
  ],
  "weights_used": {"price": 0.4, "logistics": 0.3, "duty": 0.15, "supply": 0.15},
  "excluded": [],
  "caveats": [
    "Scores are relative to this candidate set only: adding or removing a country rewrites every normalized value and can change the order.",
    "The cost criterion contains a modelled freight component, so cost differences smaller than roughly ten percent should not decide anything.",
    "Duty is the MFN rate; candidates with a trade agreement may pay less.",
    "Logistics Performance Index values are as of 2022; it is not an annual series."
  ]
}
```

---

## 5. `assess_supply_concentration_risk`

| Element | Content |
|---|---|
| **Name** | `assess_supply_concentration_risk` |
| **Purpose** | Decide whether a shortlist needs to reach beyond the current suppliers, and whether the underlying figures look trustworthy. |
| **Model-facing description** | "Test whether Ukraine's supply of a product is dangerously dependent on few origins, and whether the reported figures look trustworthy. Computes the Herfindahl-Hirschman index and effective number of origins over partner shares, the top origin's share, year-over-year volatility across several years, and the mirror gap between what Ukraine reported importing and what partners reported exporting. Returns named flags such as SINGLE_SOURCE, HIGH_CONCENTRATION, VOLATILE_SUPPLY and MIRROR_DISCREPANCY against stated thresholds. Use it to decide whether a sourcing shortlist needs to reach beyond the current suppliers." |

**Input schema**

| Field | Type | Required | Constraints | Default |
|---|---|---|---|---|
| `hs_code` | string | **yes** | 2–6 digits | — |
| `years` | array\<integer\> | **yes** | 1–5 items; three or more enable volatility | — |
| `top_partner_threshold_pct` | number | no | 10–100 | 70 |

**Output schema**

| Field | Type | Meaning |
|---|---|---|
| `status` | enum | See conventions |
| `hhi` | number \| null | Herfindahl-Hirschman index over partner value shares, 0–10000 |
| `effective_partner_count` | number \| null | `10000 / hhi` — equivalent number of equally sized origins |
| `top_partner_iso3` / `_name` / `_share_pct` | string / string / number | Largest origin in the most recent year supplied |
| `yoy_volatility_pct` | number \| null | Standard deviation of year-over-year change; null with fewer than three years |
| `mirror_gap_pct` | number \| null | Percentage by which partners' reported exports exceed Ukraine's reported imports, over the largest origins that themselves report |
| `observations` | array\<YearObservation\> | Per year: `total_value_usd`, `top_partner_iso3`, `top_partner_share_pct` |
| `flags` | array\<RiskFlag\> | `SINGLE_SOURCE`, `HIGH_CONCENTRATION`, `MODERATE_CONCENTRATION`, `VOLATILE_SUPPLY`, `MIRROR_DISCREPANCY`, `THIN_DATA` |
| `interpretation` | string | Plain-language reading of the numbers |

**Thresholds** — stated, not hidden: HHI ≥ 2500 → `HIGH_CONCENTRATION`; ≥ 1500 →
`MODERATE_CONCENTRATION`; top share ≥ `top_partner_threshold_pct` → `SINGLE_SOURCE`;
volatility ≥ 35 % → `VOLATILE_SUPPLY`; |mirror gap| > 25 % → `MIRROR_DISCREPANCY`;
fewer than 3 origins → `THIN_DATA`.

**Error conditions**

| Condition | Representation |
|---|---|
| Unknown HS code | `status: error`, `UNKNOWN_HS_CODE` |
| Comtrade unavailable for a requested year | `status: error`, `RATE_LIMITED` / `UPSTREAM_UNAVAILABLE` |
| No imports reported in any requested year | **`status: empty`** with an explanatory `interpretation` |
| No top origin reports its own exports | `status: ok`, `mirror_gap_pct: null`, and the interpretation says the comparison was impossible |

**Side effects** — one Comtrade GET per requested year, plus up to five more for the mirror
comparison. Read-only.

**Example** (recorded live; grapes, four years)

```json
// in
{"hs_code": "080610", "years": [2021, 2022, 2023, 2024]}

// out (abridged)
{
  "status": "ok", "hs_code": "080610",
  "hhi": 4502.7, "effective_partner_count": 2.22,
  "top_partner_iso3": "TUR", "top_partner_name": "Türkiye", "top_partner_share_pct": 64.8,
  "yoy_volatility_pct": 19.49,
  "flags": ["HIGH_CONCENTRATION"],
  "interpretation": "20 origins reported in 2024; HHI 4503 (equivalent to 2.2 equally sized origins). Türkiye holds 64.8 percent. Year-over-year value swings have a standard deviation of 19.5 percent."
}
```

---

## Existing server: Microsoft Playwright MCP

Repository: <https://github.com/microsoft/playwright-mcp>. Started independently with
`node node_modules/@playwright/mcp/cli.js --headless --isolated`, pinned in `package.json`; the agent spawns it and connects over stdio. Not through `npx`: bare `npx` is not an executable on Windows and Node will not spawn `npx.cmd` without a shell, so the server never started and the run went ahead without a browser.

### Why this server belongs in this project

Ukraine's monthly trade turnover for the current year is published by the State Customs
Service **only as a web page** — there is no API and no machine-readable dataset. The
`analyticalInfo` dataset on the national open-data portal turns out to be a catalogue of links
to those news posts, not data (see
[`01-data-sources-verified.md`](01-data-sources-verified.md#5-datagovua-ckan-api-no-authentication)).
Meanwhile UN Comtrade's annual data lags by about two years.

So the agent has a genuine blind spot that only a browser can fill: it can compute a
recommendation from 2024 statistics without knowing whether 2026 trade has moved sharply
since. Playwright MCP reads that figure, and the result changes the agent's recency
assessment and the staleness warning attached to its recommendation. The connection is not
decorative — remove it and the agent loses the only current-year signal it has.

A second reason: the customs site is behind Akamai and returns HTTP 403 to plain HTTP clients
from outside Ukraine, while a real local browser session loads it normally. Playwright is the
sanctioned way to reach it, and no credentials or copied session tokens are involved.

### Contract of the tool used: `browser_navigate`

| Element | Content |
|---|---|
| **Name** | `browser_navigate` |
| **Purpose** | Drive the browser to a URL so the page can then be read. In our flow it opens the customs turnover page before `browser_snapshot` extracts the figure. |
| **Model-facing description** | "Navigate to a URL" (as published by the server). |
| **Input schema** | `{"url": {"type": "string", "description": "The URL to navigate to"}}`, `url` required. |
| **Output schema** | Text content describing the resulting page state: the page URL, its title, and an accessibility snapshot of the loaded content. Playwright MCP returns human/model-readable text rather than a typed structure. |
| **Error conditions** | Unreachable host or DNS failure, navigation timeout, HTTP error status, blocked navigation, and browser launch failure (no Chromium installed, or no display). Each surfaces as a tool result carrying an error, which the agent sees as a failed step rather than as data. |
| **Side effects** | **Substantial, unlike our own tools.** Launches or reuses a Chromium process, performs an outbound network request to the target site, executes page JavaScript, and mutates persistent browser profile state (cookies, storage) unless `--isolated` is passed. This is why the tool is not marked read-only and why the agent is only permitted to navigate to the one allow-listed host. |
| **Example** | in: `{"url": "https://customs.gov.ua/news/zagalne-20/post/..."}` → out: page title plus a snapshot of the article text, from which the monthly turnover figure is read. |

### Failure demonstrated at the defence

Navigation to an unreachable page. The tool returns a navigation error, the agent reports that
the current-year figure is unavailable, marks its recency check as failed, and continues to a
recommendation based on statistical data alone with an explicit staleness warning. See
[`demo-checklist.md`](demo-checklist.md).
