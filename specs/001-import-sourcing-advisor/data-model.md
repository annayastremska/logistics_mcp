# Phase 1: Data Model

No database. Every structure here is a **contract** — a validated shape crossing the capability
boundary — or a transient in-memory value. Implemented as Pydantic models in
`mcp_server/models.py`, which is the authoritative source; this document explains the shapes and
the rules they enforce.

## Cross-cutting conventions

These apply to every result and exist to satisfy the constitutional principles rather than any
individual tool's needs.

### Status — three states, never two

```
Status = "ok" | "empty" | "error"
```

`empty` means the source genuinely holds no record for the request. It is a real answer, is not
retried, and is never reported as a failure. Collapsing `empty` into `error` would make "no
imports of this product that year" indistinguishable from "the lookup broke", which is the whole
point of separating them.

### Error codes — named, machine-readable, never a stack trace

| Code | Raised when |
|---|---|
| `UNKNOWN_HS_CODE` | The identifier is well-formed but absent from the nomenclature |
| `UNKNOWN_COUNTRY` | A country token resolves to nothing |
| `INVALID_ARGUMENT` | Malformed input: wrong digit count, non-numeric, weights not summing to one |
| `YEAR_NOT_AVAILABLE` | The reference period cannot be served |
| `AGGREGATION_TOO_COARSE` | A unit comparison was requested where quantities are not reported |
| `RATE_LIMITED` | Upstream throttled the request — distinct from unavailable |
| `UPSTREAM_UNAVAILABLE` | Transport failure |
| `UPSTREAM_MALFORMED` | A response arrived but not in the documented shape |
| `FIXTURE_MISSING` | Offline mode has no recording for this request — refuse, never default |
| `INSUFFICIENT_DATA` | Too few observations for the requested calculation |

Each detail carries the code, a human-readable message, and the offending field where one applies.
Several may be returned at once, so a validation failure reports every problem rather than the
first.

### Provenance — attached to every data-bearing result

Records the source, whether the figures came live or from a recording, the reference period, and
whether the values are `measured` or `estimated`. This is what makes any number on screen
traceable, and it is the mechanism behind principle II.

---

## Entities

### Product line

One tracked import category. `hs_code` (six digits), `label`, `group`.

*Rules*: six digits rather than four, because a four-digit heading mixes fresh and dried forms
whose unit values are not comparable. The set is fixed in code — adding a line is a change to the
system, not a runtime action.

### Normalized brief

A request resolved against the nomenclature before any quota is spent: resolved code, official
description, aggregation level, whether the level supports a unit-price comparison, target volume,
reference year, resolved candidate countries.

*Rules*: the identifier must be 2, 4 or 6 digits and must exist. A product name matching several
codes returns ranked candidates rather than guessing one. `supports_unit_price` is false at
chapter level, and downstream tools refuse rather than divide by a zero quantity.

### Flow row

What one origin supplied: `partner_iso3`, `partner_name`, `net_weight_kg`, `value_usd`,
`unit_price_usd_per_kg`, `share_of_total_pct`.

*Rules*: `unit_price_usd_per_kg` is value over weight and is null when weight is absent — it is a
statistical derivation, never a market price, and is labelled as such wherever displayed.
Aggregate partners such as "World" are excluded, or shares would exceed 100%.

### Import flows result

The origin set for one product and period, plus `total_value_usd`, `partner_count`,
`rows_dropped_as_duplicates`, `truncated`, provenance and notes.

*Rules*: the upstream reports every partner twice — once per value of the origin-versus-
consignment dimension, with identical figures — so summing raw rows double-counts every share.
That dimension is collapsed and **the number of dropped rows is reported**, so the caller can see
it happened. `truncated` is set rather than silently returning a partial list as complete.

### Concentration reading

`hhi`, `top_partner_iso3`/`_name`/`_share_pct`, `effective_partner_count`, `yoy_volatility_pct`,
`mirror_gap_pct`, `observations` per year, `flags`, and a plain-language `interpretation`.

*Rules*: `effective_partner_count` is 10000/HHI and exists because a concentration index is not
readable by a non-specialist while "1.9 equally sized sources" is. Volatility needs at least three
observations or it is not reported. The mirror-gap threshold is **asymmetric**: exports are valued
free-on-board and imports cost-inclusive, so a shortfall around a quarter is structurally expected
and only a gap outside that direction and magnitude is flagged. A symmetric threshold flagged the
normal case.

### Risk flag

`SINGLE_SOURCE`, `HIGH_CONCENTRATION`, `MODERATE_CONCENTRATION`, `VOLATILE_SUPPLY`,
`MIRROR_DISCREPANCY`, `THIN_DATA` — with an explicit severity ordering, so lines are comparable
without interpreting raw indices, and so the interface can sort worst-first without knowing what
the names mean.

### Cost component and landed cost result

Each component carries `label`, `amount_usd`, `basis` and `measurement` (`measured` or
`estimated`). The result adds the total, cost per kg, `duty_rate_pct` with `duty_basis`,
`fta_preference_possible`, `distance_km`, `confidence` and `assumptions`.

*Rules*: duty is assessed on the cost-inclusive value, not the goods value. Where the unit value
is already cost-inclusive, modelled freight is shown for reference and **not** added to the duty
base, or freight would be counted twice. `confidence` is never `high`, because freight is always
modelled. Duty is the generally applicable rate; where a preference is possible that is flagged,
never applied.

### Criterion weights

`price`, `logistics`, `duty`, `supply`. Must sum to 1.0 within 0.001.

*Rules*: weights that do not sum are rejected with a named reason rather than renormalised —
silently rescaling would misrepresent the priorities the caller stated.

### Factor contribution and ranked country

Per criterion: `raw_value`, `normalized`, `weight`, `contribution`. Per country: `rank`, `score`,
`scored_weight_pct`, `unscored_criteria`, the decomposition, and the raw inputs behind it.

*Rules*: contributions sum to the score, so a reader can see what moved it. Normalisation is
min-max **within the candidate set**, so scores are relative and adding a candidate rewrites every
value — stated as a caveat on the result.

`scored_weight_pct` and `unscored_criteria` exist because a weighted sum treats a missing term as
a zero term: a candidate whose cost could not be priced would otherwise score like an expensive
one. The score is deliberately **not** renormalised over the scorable weight — that would
manufacture a comparison the data cannot support — so the shortfall travels alongside it instead,
and a partially scored set raises a caveat where the scores are read.

### Portfolio row

The landing-screen projection of a product line: identity, `status`, value, partner count, lead
partner and share, `hhi`, `effective_partner_count`, volatility, mirror gap, `flags`, computed
`severity`, `interpretation`, `notes`.

*Rules*: `status` is `partial` when flows resolved but the risk assessment did not. A row is never
rendered with an empty risk figure alongside rows whose figures are real — an absent value must not
read as a low one. `severity` is the maximum severity among the flags, which is what the
worst-first ordering sorts on.

### Analysis record (trace event)

One observable step: `kind` (status, tool call, tool result, text, thinking, error, done),
`server`, `tool`, and payload.

*Rules*: a tool call and its result are separate events, correlated by call identifier. Results
arrive on a different message type than the requesting turn, and watching only the requesting turn
produces a trace of calls with no outcomes in which every call appears to have succeeded.

### Recorded source response

An envelope: the exact request URL, the retrieval timestamp, and the verbatim response body.

*Rules*: substitution happens at the transport boundary only, so every parser and calculation
above it runs unchanged and offline figures equal live ones. A request with no recording is
refused with `FIXTURE_MISSING` rather than defaulted. A recording is written even when the
response came from the warm cache — omitting that write is how the most-exercised value in the
project ended up with no recording at all.
