# Defence Checklist

Individual defence, 10–15 minutes. Every numbered item the assignment requires is covered
below, in the order it is easiest to demonstrate.

## Before you start

```bash
cd logistics_mcp
.venv\Scripts\activate            # Windows
python -m pytest tests -q          # 38 passing, no network
```

Have three terminals ready and both browser tabs closed. Check that `.env` exists and that
either `ANTHROPIC_API_KEY` is set or `claude` is logged in (`claude` → `/login`).

Rehearse once end to end before recording or presenting — the first live run of the day warms
the cache and is slower than the rest.

---

## Segment 1 — Independent startup and architecture (2 min)

> Requirement 1: start the custom MCP server independently from the agent.

**Terminal 1** — the custom server, on its own, with no agent anywhere:

```bash
python -m mcp_server.server
```

It prints `trade-sourcing-mcp starting (transport=stdio, data mode=live)` to stderr and waits
on stdin. Say: *this is a separate OS process; the agent will launch its own copy over stdio.*
Then Ctrl-C.

> Requirement 7: show evidence that at least three custom tools are exposed.

```bash
python scripts/inspect_tools.py
```

Five tools, each with an input schema and a **declared output schema**. Point at
`get_import_flows` and note `readOnly=True`. If asked for the raw contract:

```bash
python scripts/inspect_tools.py --json | head -60
```

**Terminal 2** — the existing server, also independently:

```bash
node node_modules/@playwright/mcp/cli.js --headless --isolated
```

**Terminal 3** — the application:

```bash
python -m web.app
```

Open <http://127.0.0.1:8000>. The badge top right shows data mode, and the *MCP connections*
panel on the right shows both servers, their transport, their tool counts, the analysis model
and which credential source is in use.

The landing screen is the **worklist**: six import lines, one row each, ordered by risk band and
then by money at stake. Lead with the summary strip, not the architecture:

> *554m dollars imported over the last twelve months. 346m of that — 62 percent — sits with a
> single origin per line. And Türkiye leads three of the six, 183m of the exposure: lines that
> would fail together. You cannot see that by looking at any one product.*

Then say where the numbers came from: *this screen is computed by the custom MCP server over a
plain stdio session — no model in the loop. The agent is what you press afterwards, on one row,
deliberately.*

**If asked why not the latest calendar year:** the annual series lags about two years, so the
list runs on a rolling twelve-month window from monthly reports, ending at the month the source
has actually published to. It matters — on annual 2024 tomatoes read 71.8 percent Turkish and
carried a single-source flag; on the window they read 64.6 percent and do not.

Architecture in one breath: *three processes. The agent has no built-in tools at all — no shell,
no filesystem — so its whole capability surface is these two MCP servers.*

---

## Segment 2 — Existing server inside an agent flow (2–3 min)

> Requirements 2, 3, 4, 5.

Open the top row (**Mandarins** — the largest single-source exposure), then **Open full
analysis** and **Run**.

- **Requirement 2 — both connections discovered.** The *MCP connections* panel fills in from the
  live session: `trade-sourcing` with 5 tools, `playwright` with 3. Say that this is read from
  the session's init message, not from our own config file.
- **Requirement 3 — a tool from the existing server is called successfully.** The first trace
  entry is `playwright → browser_navigate`. Expand its payload to show the URL, then the result.
- **Requirement 4 — its result affects a later step.** The agent reads a current-year turnover
  signal and uses it to judge how stale its statistical data is. The recommendation ends with an
  explicit staleness statement.

  **Say this before they notice it.** The customs page is tried first and returns **HTTP 403** —
  its Akamai edge blocks automated clients, though it opens normally in a human browser. The
  agent falls through to the National Bank's external-sector page and **names which page it
  actually read**. Frame it as the honest outcome, because it is the interesting one:

  > *The first source refuses us. The agent says so, uses the fallback, and tells you which page
  > the number came from. It does not report a figure it could not read — and it marks the
  > recency check partial, because the NBU page confirms the publication vintage but not a
  > turnover figure.*

  That is a stronger answer than a clean pass: it is the existing server's result genuinely
  changing what the agent does next, twice over.
- **Requirement 5 — explain the contract.** `browser_navigate`: one required string argument
  `url`; returns page state and an accessibility snapshot as text, not structured data; fails on
  unreachable host, timeout, HTTP error, blocked navigation, or browser launch failure. Side
  effects are **substantial and unlike our own tools** — it launches a Chromium process, makes a
  real network request and executes page JavaScript, which is why it runs `--isolated` and why
  the browser is allowed exactly one host. Full contract in
  [`tool-contracts.md`](tool-contracts.md#existing-server-microsoft-playwright-mcp).

---

## Segment 3 — Custom MCP end to end (3–4 min)

> Requirements 6 and 8.

Let the same run finish. Walk the trace top to bottom:

Figures below are for **Tomatoes, fresh (HS 070200)** over the rolling window Oct 2024 to Sep
2025 — the line Segment 2 opened. The grape case (HS 080610: 23 origins, Türkiye 58.0 %, 50m USD,
HHI 3,624) is the fully rehearsed fallback if the live run misbehaves.

One thing to say before they spot it: the **analysis** still runs on the annual basis, so the
agent's own figures are the 2024 ones and will differ from the screen. That is deliberate — the
window is the currency view, the annual year is the settled one, and every result names which
basis produced it.

| Step | What to say |
|---|---|
| `validate_sourcing_brief` | Resolved the request to HS 070200 against the 6,939-entry HS2022 nomenclature. Offline — `openWorldHint: false`. |
| `get_import_flows` | 16 origins, Türkiye 64.6 %, about 126m USD on the window. Duplicate rows are reported dropped, never silently collapsed. |
| `assess_supply_concentration_risk` | HHI 4,469 — equivalent to **2.2** equally sized origins, on a 126m USD line. `HIGH_CONCENTRATION`. Volatility comes from the annual series and the result says so. |
| **the decision** | This flag is what changes the next step: the agent widens its candidate list beyond the incumbents and reweights, because on a concentrated product the goal is diversification. Point at the weights it chose and its stated reason — and at the run record row **"Concentration changed the candidate set"**, which names the origins that are not current suppliers. That row read *"ranking used incumbents only — no"* until the prompt made widening a requirement rather than a suggestion. |
| `estimate_landed_cost` | Itemised: goods, freight, duty **on the CIF value**, brokerage. Each line labelled measured or estimated. |
| **the obstacle worth showing** | A widened origin has no trade with Ukraine, so there is no unit value to derive and the call returns `empty` — with the remedy in its own response: pass `unit_price_usd_per_kg`. Without it the origin is unscored on price and duty and lands last for missing data rather than on merit; measured at **1.33 out of 100 on half the weight** for Morocco. The agent passes the proxy, the ranking takes the same figures as `unit_prices`, and Morocco scores **26.08 on the full weight**. |
| `rank_sourcing_countries` | The score decomposition. Contributions sum to the score. Any row priced on a proxy is marked `proxy` on the figure itself and named in a caveat — a supplied number is never allowed to read as an observed one. |

> Requirement 8: explain one important contract and design decision.

Use `get_import_flows`, and make the design decision the **deduplication**:

> Comtrade returns every partner twice, once per value of the `partner2Code` dimension —
> country of origin versus country of consignment — with identical figures. Summing the raw rows
> double-counts every share and halves every percentage. The tool collapses that dimension and
> reports how many rows it dropped, so the caller can see it happened. A generic HTTP wrapper
> would have handed the model the raw rows and let it get this wrong silently.

Then the error convention: `status` is `ok`, `empty` or `error`. `empty` means the source
genuinely has no record for that period — a real answer, not a failure — and the server's own
instructions tell the model not to retry it.

---

## Segment 4 — Failure and offline mode (2 min)

> Requirement 9: demonstrate a realistic failure of the existing MCP server.

Open a row, press **Open full analysis**, then **Break browser server**. This points the browser
at an unresolvable host — the *input* changes, nothing is faked.

What to show: the `browser_navigate` step turns red with a navigation error; the agent states
that the current-year figure is unavailable, marks the recency check as failed, and **still
produces a recommendation** from the statistical data with an explicit staleness warning. Say:
*the failure degrades the answer, it does not crash the run — the recency check is a
contributing input, not a precondition.*

If asked for a second failure mode, stop the Playwright process in terminal 2 and re-run: the
connection itself fails rather than the navigation.

**Offline mode.** Tick **offline** in the analysis block and re-run, or in a terminal:

```bash
REPLAY=1 python scripts/smoke_tools.py
```

Say: replay substitutes at the transport boundary in `sources/http.py`, so the same raw JSON
goes through the same deduplication and arithmetic. Nothing returns a prepared answer. Show a
fixture file — it records the exact URL, the retrieval timestamp and the verbatim body.

To prove the guard rather than assert it:

```bash
SOURCING_MODE=replay python -c "from mcp_server.server import get_import_flows; print(get_import_flows(hs_code='0902', year=2019).errors)"
```

`FIXTURE_MISSING` — replay refuses to invent an answer for a query it has no recording of.

---

## Segment 5 — Questions and variations (3–4 min)

**A different valid input.** Change the question to another product, e.g.
*"Where should we source dried grapes (HS 080620) from? 40 tonnes."* Different HS code,
different origins, different concentration.

**An invalid input.**

```bash
python -c "from mcp_server.server import validate_sourcing_brief as v; print(v(target_volume_kg=1000, hs_code='123456').model_dump(exclude_none=True))"
```

`status: error`, code `UNKNOWN_HS_CODE`. Note that `999999` is *not* a good example — it is a
real HS2022 bucket, "Commodities not specified according to kind", which a unit test caught.

Weights that do not sum to 1 are a second invalid case:

```bash
python -c "from mcp_server.server import rank_sourcing_countries as r; print(r(hs_code='080610', candidates=['TUR','IND'], volume_kg=1000, weights={'price':0.9,'logistics':0.9,'duty':0.1,'supply':0.1}).errors)"
```

**Trace one value from source to output.** Take Türkiye's 64.8 % share:

1. `get_import_flows` trace entry → expand the payload → `share_of_total_pct: 64.8`, and
   `value_usd: 27,833,369` against `total_value_usd: 42,951,507`.
2. That came from `comtradeapi.un.org/public/v1/preview/C/A/HS?cmdCode=080610&flowCode=M&period=2024&reporterCode=804`,
   after collapsing 21 duplicate rows and excluding the `World` aggregate.
3. The corresponding fixture is `fixtures/comtradeapi_C_A_HS_cmdCode-080610_...json` — open it
   and find the same figure in the raw recorded response.
4. That share becomes the `supply` criterion in `rank_sourcing_countries`, normalized to 1.0 and
   contributing 15.0 of Türkiye's 90.4 score.
5. And the same share drives HHI 4,503 and the `HIGH_CONCENTRATION` flag that changed the
   candidate list.

**Name a side effect.** `get_import_flows` makes one throttled outbound GET and writes a cache
entry under `.cache/`; in `record` mode it also writes a fixture. `validate_sourcing_brief` has
none at all. `browser_navigate` launches a browser process — by far the largest side effect in
the system.

---

## Requirement coverage

| # | Requirement | Where |
|---|---|---|
| 1 | Custom server started independently | Segment 1, terminal 1 |
| 2 | Agent discovers both connections | Segment 2, connections panel |
| 3 | Existing server's tool invoked successfully | Segment 2, `browser_navigate` |
| 4 | Its result affects a later step | Segment 2, staleness assessment |
| 5 | That tool's contract and role explained | Segment 2 |
| 6 | Complete workflow using the custom server | Segment 3 |
| 7 | ≥3 custom tools exposed | Segment 1, `inspect_tools.py` |
| 8 | One custom contract and design decision explained | Segment 3, deduplication |
| 9 | Realistic failure of the existing server | Segment 4 |
| — | Changed valid input | Segment 5 |
| — | Invalid input | Segment 5 |
| — | Value traced source → output | Segment 5 |

## If something goes wrong live

| Symptom | Do this |
|---|---|
| Agent fails to authenticate | `claude` → `/login`, or set `ANTHROPIC_API_KEY` in `.env`. The badge shows which source is in use. |
| Comtrade returns `RATE_LIMITED` | Tick **offline** in the analysis block and re-run; explain the 1 req/s limit and the retry with backoff. |
| WITS times out | Expected; it is slow. The tool records the assumption and continues with the duty as a lower bound. |
| browser server absent from the run record | `npm install` has not been run, so the pinned `node_modules/@playwright/mcp/cli.js` is missing and the fallback to `npx` cannot start either. Run `npm install`. If Node is unavailable altogether, demonstrate the failure path instead and explain the Playwright contract from the docs. |
| Nothing renders in the UI | Fall back to `python scripts/smoke_tools.py` — the same tools, in the terminal. |
| The worklist is slow on first load | Expected: six lines over a twelve-month window is roughly eighty throttled Comtrade calls on a cold cache. Cached per year afterwards — warm it is about 3 s — and **Refresh** forces a re-query. |
| A row shows `incomplete` | Flows resolved but the risk call did not. Say so — the row is deliberately marked rather than shown with a blank figure, because a missing number must not read as a low one. |
