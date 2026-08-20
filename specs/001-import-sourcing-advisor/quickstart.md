# Phase 1: Validation Quickstart

Every command below has been run, and every expected outcome is a value that was actually
observed — not a value the design predicts. Where a figure could drift with fresh upstream data,
that is said.

Install and configure per the [README](../../../README.md). Then work down this list: each scenario
validates a specific requirement group, and the cheap ones come first.

---

## 0. Prerequisites check (5 seconds)

```bash
python -m pytest tests -q
```

**Expect**: `38 passed` in under 3 seconds, with no network access. If this is slow, something is
reaching the network that should not be.

---

## 1. The capability layer stands alone (30 seconds)

*Validates FR-027 and SC-016 — the capability layer is startable and inspectable with no analysis
layer present.*

```bash
python -m mcp_server.server
```

**Expect**: `trade-sourcing-mcp starting (transport=stdio, data mode=live)` on stderr, then it
waits on stdin. Ctrl-C to stop. Nothing about this depends on an agent.

```bash
python scripts/inspect_tools.py
```

**Expect**: five tools, each with an input schema **and** a declared output schema.

---

## 2. Every capability works, live (2–4 minutes)

*Validates FR-020, FR-021 and the three-state status convention.*

```bash
python scripts/smoke_tools.py
```

**Expect**: eight checks, all `OK`, ending in `all tool checks passed`. The checks that matter most
are the ones asserting on *failure* behaviour:

| Check | Expected outcome |
|---|---|
| Invalid identifier | `status=error`, code `UNKNOWN_HS_CODE` |
| Future reference year | `status=empty` — **not** an error, and not retried |
| Weights not summing to one | `status=error`, code `INVALID_ARGUMENT` |
| Delivered cost | duty `10.0%` on the cost-inclusive base, `fta_possible=True` |

---

## 3. Offline produces the same numbers as live (2 minutes)

*Validates FR-024, FR-025 and SC-013 — the claim is parity, not merely "there is an offline mode".*

```bash
REPLAY=1 python scripts/smoke_tools.py
```

**Expect**: the same eight checks pass, and the delivered cost is **duty 10.0%, $1.4566/kg** —
identical to the live run to the last decimal. Before the transport-layer fixes this reported 0%,
which is the whole reason this scenario exists.

Then prove the guard rather than assert it:

```bash
SOURCING_MODE=replay python -c "from mcp_server.server import get_import_flows; print(get_import_flows(hs_code='0902', year=2019).errors)"
```

**Expect**: `FIXTURE_MISSING`. Offline refuses a request it has no recording of; it does not
substitute a default.

---

## 4. The worklist, offline and deterministic (1 minute)

*Validates FR-001, FR-006 and SC-004.*

```bash
SOURCING_MODE=replay python -m web.portfolio
```

**Expect** `basis: trailing_12m covering 202410-202509`, then all six lines worst-first, matching
these figures exactly — offline they are fixed, so any difference is a regression:

| Line | Imports | Lead | HHI | Effective | Flags |
|---|---|---|---|---|---|
| Mandarins 080521 | $98M | TUR 73.4% | 5,516 | 1.8 / 19 | `SINGLE_SOURCE`, `HIGH_CONCENTRATION` |
| Almonds 080212 | $19M | USA 98.2% | 9,641 | 1.0 / 9 | `SINGLE_SOURCE`, `HIGH_CONCENTRATION`, `VOLATILE_SUPPLY`, `MIRROR_DISCREPANCY` |
| Bananas 080390 | $231M | ECU 54.1% | 3,728 | 2.7 / 17 | `HIGH_CONCENTRATION`, `MIRROR_DISCREPANCY` |
| Tomatoes 070200 | $126M | TUR 64.6% | 4,469 | 2.2 / 16 | `HIGH_CONCENTRATION` |
| Grapes 080610 | $50M | TUR 58.0% | 3,624 | 2.8 / 23 | `HIGH_CONCENTRATION` |
| Kiwifruit 081050 | $29M | GRC 65.7% | 4,758 | 2.1 / 15 | `HIGH_CONCENTRATION`, `VOLATILE_SUPPLY` |

Run it twice: the figures must be identical. Drop `SOURCING_MODE=replay` and they must match live
as well.

**Then check the basis is doing something.** The same six lines on the annual year they replaced:

```bash
SOURCING_MODE=replay python -c "import asyncio,sys; sys.path.insert(0,'.'); from web.portfolio import build_portfolio; r=asyncio.run(build_portfolio(2024, window=False)); [print(x['hs_code'], x['top_partner_iso3'], round(x['top_partner_share_pct'],1), x['flags']) for x in r['rows']]"
```

**Expect** tomatoes at **71.8%** with `SINGLE_SOURCE`, against 64.6% and no such flag on the
window. If the two bases agree exactly, the window is not being applied.

---

## 5. The interface (2 minutes)

*Validates FR-001 to FR-009, FR-026, SC-001, SC-002, SC-005, SC-015.*

```bash
python -m web.app          # http://127.0.0.1:8000
```

**Expect on the landing screen**, with nothing typed:

- A summary strip reading **6 lines · $554m imports · $346m concentrated in one origin (62%) ·
  Türkiye, 3 lines, $183m · 2 of 6 need attention**. The Türkiye cell is SC-003 — the shared
  dependency no single row reveals.
- Six rows, one per line, ordered by risk band then by money at stake. Mandarins first (largest
  single-source exposure), then almonds; bananas above tomatoes on money.
- Warm load under 5 seconds. Cold is bounded by the upstream one-request-per-second limit.

**Then check what should *not* be there**: no question box as the entry point, and no prose
explaining the screen. The list is the entry point and the figures are the argument.

**Filter**: *Needs attention* must actually narrow — 2 of 6, the two single-source lines. A filter
matching every row is a filter doing nothing, which is what "any flag" did.

**Progressive disclosure**: click a row. Detail opens **in place**, not on another screen: the top
five origins with shares and unit values, and the conditions kept off the list row. The status
cell shows one word plus `+n` for the rest rather than stacking four badges.

**Accessibility**: view in greyscale, and check contrast. Status is a coloured rule plus a word, so
severity survives without colour. Every text token clears 4.5:1 on both surfaces in both modes;
interactive boundaries clear 3:1 (3.33 light, 4.16 dark) while row rules stay deliberately lighter,
being decorative.

**Full line view**: from the expanded row, *Open full analysis*. Expect every reporting origin with
share, value, weight and unit value, and the source caveats behind one disclosure.

---

## 6. A full analysis, both providers (10 minutes, about $0.55)

*Validates FR-010 to FR-017, SC-006, SC-007, SC-009.*

```bash
python scripts/run_e2e.py
```

**Expect** the verdict line `PASS  both servers attached, all five custom tools called, no errors`.
Observed on the reference run: both providers attached, 19 tool calls, 20 turns, 620 s, $0.547.

This check exists because a run where the capability server failed to start still produces a
fluent, well-reasoned answer — the model simply reports that it has no tools. **A check that only
asserts "the run finished" passes that run.** So assert on the verdict line, not the exit code
alone.

Then read `scripts/last_e2e_trace.jsonl` and confirm:

1. **The browser step is first**, and its result is `is_error: true` for the customs page — that
   host returns 403 to automated clients. The next event must be a navigation to the fallback, and
   the final answer must **name which page it actually read**. This is FR-010.
2. **Every `tool_call` has a matching `tool_result`.** A trace of calls with no outcomes means
   result capture has regressed, and every call will appear to have succeeded.
3. **The concentration finding changed the candidate set.** At least one recommended origin must
   sit outside the current leaders, with the widening explained. This is SC-007.
4. **The answer names its reference year** and labels every modelled figure at the point of use.

---

## 7. A realistic provider failure (10 minutes)

*Validates FR-023 and SC-014 — degrade, do not crash.*

In the interface: open a line, then press **Demo: break Playwright**. This points the browser at an
unresolvable host and disables the fallback chain, so the failure shown is the provider's own. The
input changes; nothing is faked.

**Expect**, as observed on the reference run:

- `browser_navigate` fails with `net::ERR_NAME_NOT_RESOLVED`, and it is the **only** failing step.
- All five custom capabilities are still called.
- A complete ranked recommendation is still produced.
- The failed currency check appears in *what would change it* — on the reference run, as: *"a real
  2025–26 Ukrainian customs turnover figure — my recency check failed, so if Türkiye's share has
  already collapsed or grown, the diversification premium is mispriced."*

That last point is the requirement: the failure degraded the answer and was disclosed, rather than
aborting the run or being silently absorbed.

---

## 8. A follow-up question is cheap (1 minute, about $0.014)

*Validates FR-018, FR-019, SC-010.*

With a portfolio on screen, ask in the side panel: *"Which line would you fix first, and why?"*

**Expect**: an answer in under 60 seconds that reasons over the displayed figures and names
specific lines and shares. Observed: 1 turn, 19 s, $0.014 — a fortieth of a full analysis, with no
recomputation.

---

## 9. A partially scored ranking says so (30 seconds)

*Validates the absent-is-not-zero rule at the point it was violated.*

```bash
SOURCING_MODE=replay python -c "from mcp_server.server import rank_sourcing_countries as r; x=r(hs_code='070200', candidates=['TUR','POL','MAR','NLD'], volume_kg=120000, transport_mode='road', year=2024); [print(c.iso3, c.score, c.scored_weight_pct, c.unscored_criteria) for c in x.ranking]; print(x.caveats[-1][:120])"
```

**Expect**: each candidate reporting `scored_weight_pct` of `15.0` with `price`, `logistics` and
`duty` named as unscored, and a caveat beginning *"Partially scored candidates are NOT comparable
with fully scored ones"*.

The scores themselves are low (15.0 and below) and that is deliberate: they are **not**
renormalised, because rescaling would present a one-criterion judgement on the same scale as a
four-criterion one. The declared shortfall is what makes the low number readable as *unknown*
rather than as *bad*.

Contrast with a fully scored set:

```bash
SOURCING_MODE=replay python -c "from mcp_server.server import rank_sourcing_countries as r; x=r(hs_code='080610', candidates=['TUR','MDA','IND'], volume_kg=120000, transport_mode='road', year=2024); [print(c.iso3, c.score, c.scored_weight_pct) for c in x.ranking]"
```

**Expect**: TUR 90.44, MDA 50.39, IND 37.50 — all at `scored_weight_pct` 100.0, and no partial
caveat.

---

## What is not covered here

- **No load or concurrency validation.** Single analyst, single session, by design.
- **No cross-year regression suite.** The offline figures above pin 2024 only.
- **Upstream drift.** Live figures can move when the source revises a year. The offline scenarios
  are the stable reference; a live-versus-offline mismatch means either a revision upstream or a
  regression here, and the recorded envelopes carry retrieval timestamps to tell those apart.
