# Import Sourcing Advisor

A domain-specific data agent for **macro-level import sourcing screening for Ukraine**.
Ask it which countries a product group should be sourced from, and it works the question
through open trade data: which origins actually supply it, how concentrated that supply is,
what each candidate would cost landed, and how the candidates rank against one another.

The agent is extended through two MCP connections:

| | Server | Role |
|---|---|---|
| Existing | [Microsoft Playwright MCP](https://github.com/microsoft/playwright-mcp) | Reads the current-year trade turnover figure that Ukrainian authorities publish only as a web page, so the agent knows how stale its statistical data is |
| Custom | `trade-sourcing-mcp` (this repo, `mcp_server/`) | Five tools over UN Comtrade, the World Bank Indicators API and WITS TRAINS |

Everything runs on public data with no confidential inputs, and the custom server needs no
API credentials of any kind.

## What you see first

A worklist, not a chat box. Six tracked import lines, one row each, ordered by risk band and
then by money: lead supplier, its share, **what that share is worth**, how many effective
origins sit behind it, and a one-word status. Opening a row expands its origin detail in
place; the agent run is a deliberate action from there.

Above the list, a strip of aggregates. On the current window: **554m USD imported, 346m of it
concentrated in a single origin per line (62%), and Türkiye leading 3 of the 6 lines — 183m of
the exposure.** That last figure is the one no per-product report can show: lines that would
fail together.

The list is computed, not reasoned about. `web/portfolio.py` opens one MCP stdio session to the
same custom server the agent uses and calls the tools directly, with no model in the loop. The
first screen a visitor loads should not wait on an agent or cost anything.

**Currency.** The annual trade series lags by about two years, so the list runs on a rolling
twelve-month window built from monthly reports, ending at whatever month the source has actually
published to — currently **Oct 2024 to Sep 2025**, roughly eleven months ahead of the latest
complete annual year. That is not cosmetic: on annual 2024 data fresh tomatoes read 71.8 percent
Turkish and carried a single-source flag; on the window they read 64.6 percent and do not.

---

## Prerequisites

| Requirement | Version tested | Why |
|---|---|---|
| Python | 3.13.3 | Custom MCP server, agent, web app |
| Node.js | 22 LTS | Only for Playwright MCP, which is distributed via npm |
| Claude Code CLI **or** an Anthropic API key | CLI 2.1.232 | The agent runs on the Claude Agent SDK |
| git | 2.49 | — |

No key, token or account is needed for any of the three data APIs.

---

## Installation

```bash
git clone <repository-url> logistics_mcp
cd logistics_mcp

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

Install the browser server and a Chromium build once (Node 18+ on the PATH):

```bash
npm install
npx -y playwright install chromium
```

`npm install` pins `@playwright/mcp`, and the agent then starts it as
`node node_modules/@playwright/mcp/cli.js`. It does not go through `npx`: there is no
executable called `npx` on Windows, and Node refuses to spawn `npx.cmd` without a shell, so
launching the server by that name failed silently — the run continued and the model reported
it had no browser tool. Without `npm install` the agent falls back to `npx -y
@playwright/mcp@latest`, which works where a POSIX shell resolves it.

---

## Configuration

```bash
cp .env.example .env
```

`.env` is git-ignored. Nothing in it is required for the custom MCP server; the values only
affect the agent and the data transport mode.

| Variable | Default | Meaning |
|---|---|---|
| `ANTHROPIC_API_KEY` | unset | Model credential for the agent. If unset, the Claude Agent SDK falls back to the local Claude Code login (`claude` → `/login`). Only one of the two is needed. |
| `SOURCING_ANALYSIS_MODEL` | `claude-sonnet-5` | Model for a full sourcing run. Measured against Opus on the same run: both pass, 595s vs 620, $0.398 vs $0.547, and Sonnet walked the whole recency fallback chain to a usable figure where Opus stopped partway |
| `SOURCING_CHAT_MODEL` | `claude-haiku-4-5` | Model for follow-up questions about an already-computed result: no browser, three read-only tools |
| `SOURCING_MODE` | `live` | `live` calls the open APIs, `record` also writes fixtures, `replay` serves from fixtures with no network access |
| `SOURCING_CACHE_TTL` | `86400` | Seconds to keep the local response cache (`.cache/`, git-ignored) |

---

## Running the pieces independently

The custom MCP server is a **separate process** and is started on its own. Nothing about it
depends on the agent.

### 1. Custom MCP server

```bash
python -m mcp_server.server
```

It serves MCP over stdio and prints its transport and data mode to stderr on startup. To
inspect the contracts it publishes without an agent at all:

```bash
python scripts/inspect_tools.py           # summary of all five tool contracts
python scripts/inspect_tools.py --json    # full input and output JSON schemas
```

Or drive it with the official inspector:

```bash
npx -y @modelcontextprotocol/inspector python -m mcp_server.server
```

### 2. Playwright MCP server

The agent spawns this itself; run it by hand only to inspect it.

```bash
node node_modules/@playwright/mcp/cli.js --headless --isolated
```

### 3. Agent and web application

```bash
python -m web.app          # serves http://127.0.0.1:8000
```

The web app launches both MCP connections as child processes and shows which tools each one
exposed.

---

## Verifying the install

```bash
python -m pytest tests -q        # 47 unit tests, no network, ~2s
python scripts/smoke_tools.py    # calls every tool end to end against the live APIs
REPLAY=1 python scripts/smoke_tools.py   # the same run, offline, from fixtures
python scripts/run_e2e.py        # the whole agent flow, both MCP servers, live
python scripts/run_failure_demo.py       # the same flow with the browser server broken
```

`run_e2e.py` is the check the demo rests on. It fails the run unless **both** servers
attached and **all five** custom tools were actually called — a run where the custom server
failed to start still produces a fluent answer, because the model simply reports it has no
tools. Every event is written to `scripts/last_e2e_trace.jsonl` so the run can be inspected
afterwards rather than taken on trust. A full run is roughly 10 minutes, 20 turns and about
$0.55. A failed navigate on a *fallback* recency URL is tolerated once another page in the chain
has loaded — the chain is ordered and the agent stops at the first page that answers — but a
chain where nothing loaded, and every error from the custom server, still fail the run.

`run_failure_demo.py` is the other half: it points the browser at an unresolvable host with no
fallbacks and passes only if the navigate reports as an error, nothing else errors, and a
recommendation still comes out with the failed check named in it. The requirement is not that
nothing fails — it is that a failure is distinguishable from an empty answer.

---

## Offline / replay mode

The custom server calls three network APIs, so genuine responses are recorded under
`fixtures/` and can be replayed with no network access:

```bash
# Offline
SOURCING_MODE=replay python -m mcp_server.server

# Re-record after changing a query
SOURCING_MODE=record python scripts/smoke_tools.py
```

Substitution happens at the **transport boundary** (`mcp_server/sources/http.py`): replay
hands back the same raw JSON the network returned, and every parser, deduplication step and
calculation above it runs unchanged. No code path returns a prepared answer.

Each fixture is an envelope recording the exact URL, the retrieval timestamp and the verbatim
response body.

---

## Data sources

| Source | Endpoint | Auth | What it provides |
|---|---|---|---|
| UN Comtrade (preview) | `comtradeapi.un.org/public/v1/preview` | none | Reported trade by HS code, partner and year: weight, value, unit value |
| World Bank Indicators | `api.worldbank.org/v2` | none | Logistics Performance Index and sub-indices, container port traffic |
| WITS TRAINS | `wits.worldbank.org/API/V1/SDMX/V21` | none | Applied MFN import duty by HS6 |
| Comtrade reference files | vendored in `data/reference/` | none | HS2022 nomenclature, country codes — the preview API returns codes only |
| State Customs Service | web page, via Playwright MCP | none | Current-year turnover, published only as HTML. **Returns 403 to automated clients**, so it is tried first and usually fails |
| National Bank of Ukraine | web page, via Playwright MCP | none | External-sector statistics index — the reachable fallback for the recency check |

Verified endpoint behaviour, rate limits and quirks are documented in
[`docs/01-data-sources-verified.md`](docs/01-data-sources-verified.md).

---

## Repository layout

```
mcp_server/          Custom MCP server (separate process)
  server.py          Five tool registrations, stdio entry point
  models.py          Pydantic input/output contracts
  sources/           http (rate limit, cache, fixtures), comtrade, worldbank, wits, reference
  domain/            costing and analysis calculations
agent/               Claude Agent SDK wiring, two model tiers, trace events
web/                 FastAPI application, portfolio over MCP, single-page UI
  app.py             Endpoints: portfolio, commodity detail, agent run, chat
  portfolio.py       The tracked lines, queried over an MCP stdio session
  index.html         Portfolio screen, line detail, MCP trace, chat panel
data/reference/      Vendored HS2022 and country reference data
fixtures/            Recorded genuine API responses for replay mode
scripts/             inspect_tools, smoke_tools, run_e2e
tests/               Unit tests
docs/                Requirements digest, verified sources, contracts, rationale, demo script
```

---

## Documentation

| Document | Contents |
|---|---|
| [`docs/00-assignment-requirements.md`](docs/00-assignment-requirements.md) | What the assignment requires, condensed |
| [`docs/01-data-sources-verified.md`](docs/01-data-sources-verified.md) | Every source probed live: endpoints, real values, limits, gotchas |
| [`docs/tool-contracts.md`](docs/tool-contracts.md) | Full contract for each custom tool and for the Playwright tool used |
| [`docs/design-rationale.md`](docs/design-rationale.md) | Why these servers, why each tool sits at the MCP boundary, trade-offs, limitations |
| [`docs/demo-checklist.md`](docs/demo-checklist.md) | Defence script |

---

## Known limitations

Stated up front rather than buried:

- **Freight cost is modelled, not quoted.** No open source publishes freight rates. Every
  modelled figure is labelled `estimated` in the tool output.
- **Duty is the MFN rate.** WITS returns HTTP 404 for preferential rates, so agreements such
  as the EU DCFTA are flagged as possible but not applied.
- **The annual series lags by about two years.** In August 2026 Ukraine had reported 2024 but
  not 2025. The monthly series reaches September 2025, which is what the worklist uses. The
  landed-cost and ranking tools still run on the annual basis, and duty comes from an older
  observation again — each result names the basis it used.
- **Unit values are not prices.** A Comtrade unit value is total value over total weight, not
  a quotation.
- **The Logistics Performance Index is not an annual series.** 2022 is the latest observation.
- **The customs page blocks automated clients.** `customs.gov.ua` answers HTTP 403 at its
  Akamai edge to anything that is not a human browser, while opening normally for a person.
  The recency step therefore falls through to the National Bank's external-sector page, and
  the agent names which page it actually read. That confirms the publication vintage but not
  a turnover figure, so the recency check is partial by design rather than by accident.
- **The portfolio is six lines, chosen for signal.** Apples (HS 080810, $0.5M) and walnuts in
  shell (HS 080231, near zero) were dropped: Ukraine grows and exports both, so their import
  lines are noise.
- **This is a screening tool.** It narrows a list of countries worth investigating; it does not
  replace a tender.
