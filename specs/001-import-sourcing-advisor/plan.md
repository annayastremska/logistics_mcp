# Implementation Plan: Import Sourcing Advisor

**Branch**: `001-import-sourcing-advisor` | **Date**: 2026-08-20 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-import-sourcing-advisor/spec.md`

> **Standing on built code.** This plan was written after the system was implemented, to close a
> gap in process artefacts. Every technical decision below is a decision already taken and
> exercised, so there is nothing to research and no unknown to resolve — Phase 0 records what the
> choices turned out to cost rather than what they were expected to cost. The value of writing it
> now is the Constitution Check, which found and forced two real fixes; those are recorded in
> Complexity Tracking.

## Summary

Give a procurement analyst a portfolio view of concentration risk across tracked Ukrainian import
lines that is legible before they ask anything, drillable to the origin level, and escalatable to
a full agentic sourcing analysis on one line at a time.

The approach separates three layers by what they are good at. A **capability layer** — a separate
process publishing five contract-declared tools over open trade data — owns every retrieval and
every calculation. A **deterministic read path** drives that layer directly, with no model, to
compute the landing screen: the first screen a user sees must be instant, free and identical on
every run. An **agentic path** drives the same layer plus an existing browser-automation provider
for the analysis that genuinely needs judgement: sequencing, candidate selection, weighting and
explanation.

The load-bearing design choice is that the agent has no built-in tools at all. Its entire
capability surface is the two providers, so the contract boundary is the real boundary and every
figure in an answer is traceable to a declared tool call.

## Technical Context

**Language/Version**: Python 3.13.3

**Primary Dependencies**: `mcp` 2.0.0 (capability server and client), `pydantic` ≥2.12 (input and
output contracts), `claude-agent-sdk` ≥0.2.140 (agent and provider wiring), `fastapi` + `uvicorn`
(read path and streaming), `python-dotenv`. Node.js 24.19 is required only to run the existing
browser-automation provider, distributed via npm.

**Storage**: None. No database and no persistent application state. Two file-backed caches only:
a time-to-live response cache outside version control, and a committed fixture set of verbatim
recorded source responses that makes offline operation possible. Reference nomenclature and
country tables are vendored as data files because the upstream preview endpoint returns codes
without labels.

**Testing**: `pytest` — 38 tests over the domain arithmetic, the transport boundary and the agent wiring, offline, 1.7 s.
Above that, three purpose-built checks: a tool-level smoke run (live and offline), a browser-
rendered check of the interface, and an end-to-end agent run that fails unless both providers
attached and all five capabilities were actually invoked.

**Target Platform**: Local developer machine, Windows 11 verified. Three processes started
independently; the interface is served on localhost.

**Project Type**: Web application with a separate capability server — three cooperating processes
rather than a single deployable.

**Performance Goals**: Landing screen under 5 s warm, under 60 s cold. Full analysis under 15
minutes. Follow-up question under 60 s. Upstream is rate limited to one request per second, which
sets the floor on all three.

**Constraints**: No credential for any data source. Must run with no network access from recorded
responses and produce identical figures. Severity legible without colour. Cost per follow-up
question must be a small fraction of a full analysis.

**Scale/Scope**: Six tracked product lines, up to twenty origins each, three reference years per
line. Single analyst, single session, no concurrency or access control. Roughly 2,900 lines of
Python across the capability server, agent and read path, plus one interface page.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Checked against [constitution v1.0.0](../../.specify/memory/constitution.md).

| Principle | Verdict | Evidence |
|---|---|---|
| **I. Open data only** (non-negotiable) | **PASS** | No credential for any data source; the capability server needs none at all. Secret scan over all 79 tracked files before publication found nothing, and no reference to any employer or internal system. |
| **II. Measured and modelled never confused** | **PASS** | Every cost component carries a measured/estimated marker. Unit values carry their disclaimer inline. Confidence is capped below "high" whenever a modelled component is present. |
| **III. Absent is not zero, empty is not an error** | **PASS after remediation** | Three-state status on every result; a future year returns empty, not error. Two violations were found by this check and fixed — see Complexity Tracking rows 1 and 2. |
| **IV. Capability boundary is the whole surface** | **PASS** | Empty built-in tool set, explicit allow-list, no inherited local settings or plugins. All five tools declare input *and* output schemas. The deterministic read path goes through a client session, not around it. |
| **V. Verified, not asserted** (non-negotiable) | **PASS** | Every claim in the artefacts is backed by a run recorded in this session: full agent run, failure-path run, offline run, browser render, 38 tests. The end-to-end check asserts on substance, not on completion — and the four regression tests added for previously untested fixes were each mutation-checked by reverting the fix to confirm the test fails. |

| Additional constraint | Verdict | Evidence |
|---|---|---|
| Offline parity | **PASS after remediation** | The whole portfolio now renders offline with figures identical to live on all six lines. Before this check it was true of one line in six — Complexity Tracking row 2. |
| Determinism where a model is not needed | **PASS** | Landing screen and line detail contain no model call. Repeat runs return identical figures. |
| Cost proportional to the question | **PASS** | Measured: full analysis $0.55 / ~10 min; follow-up question $0.014 / 19 s — a fortieth of the cost, against a target of a twentieth. |
| Legibility without colour | **PASS** | Every severity carries a glyph as well as a colour. |
| Screening, not procurement | **PASS** | Stated in the README, the rationale and every analysis output, which closes with what would change the conclusion. |

**Gate result: PASS.** Two remediations were required and are complete; both are recorded below
rather than absorbed silently, because the mechanism of each generalises.

## Project Structure

### Documentation (this feature)

```text
specs/001-import-sourcing-advisor/
├── plan.md              # This file
├── research.md          # Phase 0: what the decisions cost in practice
├── data-model.md        # Phase 1: entities and validation rules
├── quickstart.md        # Phase 1: runnable validation scenarios
├── contracts/           # Phase 1: the published capability contracts
└── tasks.md             # Phase 2 output (/speckit-tasks — not created here)
```

### Source Code (repository root)

```text
mcp_server/                  # Capability layer. Separate process, stdio transport.
├── server.py                # Five tool registrations with declared input and output schemas
├── models.py                # Pydantic contracts, three-state status, named error codes
├── sources/
│   ├── http.py              # THE transport boundary: rate limit, cache, fixture record/replay
│   ├── comtrade.py          # Trade flows; collapses the origin/consignment duplication
│   ├── wits.py              # Applied duty, with year fallback
│   ├── worldbank.py         # Logistics quality index
│   └── reference.py         # Vendored nomenclature, country resolution, distances
└── domain/
    ├── analysis.py          # Concentration, volatility, mirror gap, normalisation
    └── costing.py           # Itemised delivered cost, duty on the CIF base

agent/                       # Agentic path.
└── sourcing_agent.py        # Provider wiring, two model tiers, ordered source fallback, trace

web/                         # Read path and interface.
├── app.py                   # Portfolio, line detail, analysis stream, follow-up stream
├── portfolio.py             # Deterministic portfolio over one client session, no model
└── index.html               # Portfolio screen, line detail, call trace, follow-up panel

scripts/                     # Verification, not application code.
├── inspect_tools.py         # Publish the contracts with no agent present
├── smoke_tools.py           # Every capability, live or offline
└── run_e2e.py               # Full agent run; fails unless both providers and all five tools

tests/                       # 38 offline tests: domain arithmetic, transport boundary, agent wiring
data/reference/              # Vendored nomenclature and country tables
fixtures/                    # 61 verbatim recorded source responses
docs/                        # Requirements digest, verified sources, contracts, rationale, demo
```

**Structure Decision**: Three top-level packages matching the three layers, because they have
genuinely different lifecycles: `mcp_server/` runs as its own process and is startable and
inspectable with nothing else present; `web/` holds both the deterministic read path and the
interface, because the read path exists only to serve that interface; `agent/` holds only the
provider wiring and trace translation, and deliberately contains no domain logic — anything it
knew how to calculate would be a calculation living outside a declared contract.

`scripts/` is separated from `tests/` on purpose: `tests/` is the offline arithmetic suite, while
`scripts/` holds the checks that need the real thing running and cannot be part of a fast suite.

## Complexity Tracking

> Filled because the Constitution Check found real violations. Both are fixed; both are recorded
> because the mechanism generalises where the fix does not.

| Violation | Why it happened | Simpler alternative rejected because |
|-----------|-----------------|--------------------------------------|
| **Principle III — an unscorable ranking criterion scored as a bad one.** A candidate whose delivered cost could not be priced scored 15 out of 100 beside a fully priced candidate's 90, because an unscorable criterion contributes zero, which is precisely what a bad value contributes. The per-factor detail was honest — raw value and normalised value were both null — but the headline score conflated "unknown" with "poor". | The decomposition was designed to carry nulls correctly and it did. Nobody checked what the *aggregate* of a null does, and a weighted sum silently treats a missing term as a zero term. | Renormalising the score over the scorable weight was rejected: it would manufacture a comparison the data does not support, presenting a one-criterion judgement on the same scale as a four-criterion one. Instead each candidate now declares the share of weight actually scored and names what is missing, and a partially scored set raises a caveat where the scores are read. The score is left alone. |
| **Offline parity held for one line in six.** The portfolio rendered offline for grapes only; the other five refused with an explicit missing-recording error. The refusal was correct behaviour, but the claim "runs offline" was true of a sixth of the screen. | Fixtures had been recorded for the originally rehearsed product only. The portfolio was widened to six lines later, and nothing re-derived what the recording set now needed to cover. | Narrowing the offline claim to "one line works offline" was rejected as an artefact edit standing in for a fix. Recording the missing responses cost one command, and the underlying recording defect it exposed — a warm cache silently skipping the fixture write — was itself a latent correctness bug worth fixing on its own. |
