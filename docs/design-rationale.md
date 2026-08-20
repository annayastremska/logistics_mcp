# Design Rationale

Why this system is shaped the way it is, and what it cannot do.

---

## 1. Why Playwright MCP is the right existing server here

The agent has one genuine blind spot that only a browser can fill.

UN Comtrade — the primary data source — lags by about two years. Verified in August 2026:
Ukraine had reported 2024 in full and 2025 not at all. So an agent working purely from
statistics can produce a confident recommendation without knowing whether trade has moved
sharply since.

The current-year figure exists, but only as prose on a web page. The State Customs Service
publishes monthly turnover as news posts; the `analyticalInfo` dataset on the national
open-data portal turns out to be a catalogue of links to those posts rather than data (8 rows,
3.2 KB — see [`01-data-sources-verified.md`](01-data-sources-verified.md#5-datagovua-ckan-api-no-authentication)).
There is no API and no machine-readable release.

That makes the browser a data source rather than a convenience:

- **It changes the answer.** The turnover figure sets the recency assessment attached to every
  recommendation, and the staleness warning the agent must state. Remove the connection and the
  agent loses its only current-year signal.
- **It is the sanctioned access path.** The customs site sits behind Akamai and returns HTTP 403
  to plain HTTP clients from outside Ukraine, while a real local browser session loads it
  normally. Playwright reaches it the way a person does. No copied cookies, no bot-detection
  tokens, no credentials — those were explicitly rejected during development.
- **It fails in interesting ways.** A scrape can fail through an unreachable host, a changed
  page, or a browser that will not launch. Each is a realistic failure worth demonstrating,
  and each surfaces differently from our own tools' structured errors.

The alternatives were weaker. OpenWeather has no coherent role in macro import sourcing —
weather would have had to be bolted on. Obsidian would have been a vault we populate ourselves,
which means the agent reads back what we already wrote: stable, but circular, and it adds no
information the agent could not have been handed directly.

## 2. Why each custom tool sits at the MCP boundary

The test applied to each: **would the agent be worse off if this were not a tool?**

| Tool | Why it is a tool rather than agent prose |
|---|---|
| `validate_sourcing_brief` | Resolving "fresh grapes" to HS 080610 requires the 6,939-entry HS2022 nomenclature. A model guessing a code is a plausible-looking wrong answer that poisons every later step, and each wrong guess costs a rate-limited API call. The tool makes the resolution checkable and returns ranked candidates instead of one confident guess. |
| `get_import_flows` | The primary data-source tool. Beyond fetching, it carries three pieces of knowledge the model cannot have: descriptive fields come back `null` and must be joined against vendored reference tables; every partner is duplicated on the `partner2Code` dimension, so naive summing double-counts every share; and reporting aggregates such as "World" must be excluded before shares mean anything. A generic HTTP tool would hand the model raw rows and let it get all three wrong. |
| `estimate_landed_cost` | An ordered domain calculation: goods value, then freight and insurance to reach CIF, then duty **assessed on that CIF value**, then brokerage. Getting the order wrong understates cost, which a model asked to "add up the costs" does routinely. It also encodes that a Comtrade import unit value is already CIF, so adding modelled freight to the duty base would double-count. |
| `rank_sourcing_countries` | Min-max normalization across a candidate set, then weighting. Arithmetic a language model should not be doing in its head, and the decomposition it returns is what makes the ranking arguable rather than an oracle. |
| `assess_supply_concentration_risk` | HHI, effective origin count, volatility across years, and the mirror gap, each against a stated threshold. The mirror comparison in particular requires knowing to **swap reporter and counterpart** — asking Ukraine what Ukraine exported to Ukraine returns nothing and makes every gap look like −100 %. That is exactly the kind of trap a tool should absorb. |

Three of the five perform no retrieval at all, and the assignment's floor is two.

## 3. How the tool set supports one agentic flow

The tools are ordered so that each one's result can change the next decision:

```
browser: read current-year turnover ──► recency assessment, staleness warning
                │
validate_sourcing_brief ──► hs_code + year   (status=error ⇒ stop, do not guess)
                │
get_import_flows ──► who actually supplies it
                │
assess_supply_concentration_risk ──► HHI, flags
                │
      ┌─────────┴──────────┐
 concentrated          not concentrated
      │                     │
 widen candidates      keep incumbents
 reweight: supply ↓         │
 logistics ↑                │
      └─────────┬───────────┘
                │
estimate_landed_cost per candidate
                │
rank_sourcing_countries with justified weights
```

The feedback is real, not narrated. Step 4 changes both the candidate list and the weights
used in step 6: on a concentrated product the point of the exercise becomes diversification,
so demonstrated supply capacity — which by definition favours the incumbent — is weighted down
and logistics quality up. On the live demo case, grapes, HHI comes out at 4,503 with Türkiye at
64.8 %, which triggers exactly that path.

## 4. Design decisions worth defending

### In-band errors

Every tool returns `status: "ok" | "empty" | "error"` inside a normal result rather than raising
an MCP protocol error.

The reason is that the agent is the consumer. A protocol-level error arrives as an exception the
model can only retry or abandon; a structured `errors[]` with a machine-readable `code` is
something it can reason about — `RATE_LIMITED` means wait, `UNKNOWN_HS_CODE` means re-resolve
the product, `FIXTURE_MISSING` means the demo is misconfigured. The three-way discriminator also
makes the assignment's hard requirement explicit rather than implied: `empty` is a successful
call over a period the source has no record for, and the model is told in the server
instructions not to retry it.

The cost is that a careless client could ignore `status` and treat a failure as data. Making the
field required on every model, and documenting it first in the contracts, is the mitigation.

### Fixtures at the transport boundary

Record and replay live in `mcp_server/sources/http.py`, below every parser. In replay mode the
same raw JSON the network returned is handed to the same deduplication, joining and arithmetic
code. Nothing anywhere returns a prepared answer, and the demo therefore exercises the real
processing path. It also means a bug in parsing shows up identically online and offline.

### Modelled freight, labelled as such

No open source publishes freight rates. Rather than omit transport — which would flatter nearby
origins — or quote a made-up rate as fact, the cost is modelled from distance and mode, every
line carries `measurement: "measured" | "estimated"`, the coefficients are surfaced in
`assumptions`, and `confidence` is never `high`. The UI repeats the caveat next to the number.
An honest estimate beats both a missing component and a false precision.

### Asymmetric mirror-gap threshold

Imports are valued CIF and exports FOB, so partners systematically report *less* than the
importer: a moderately negative gap is the expected reading. A symmetric ±25 % threshold flagged
the normal case — the live grapes figure of −25.6 % — as an anomaly. The threshold is now
asymmetric: above +25 % (partners report more than arrived) or below −50 % (a shortfall too
large for valuation alone). Partners that do not report to Comtrade are excluded from the
comparison rather than counted as zero, which is what produced the original −100 % artefact.

### The agent gets no built-in tools

`tools=[]` in the agent options. No Bash, no file editing, no general web access. Its entire
capability surface is the two MCP servers, so the MCP boundary is the real boundary. Coupled
with `setting_sources=[]` and `plugins=[]`, which stop the developer's own Claude Code
configuration from injecting itself into the session — without it, a locally installed plugin
appeared inside the agent's context during testing and would have made the demo
non-reproducible on another machine.

### Data vintage resolved, not hardcoded

The default year is the current year minus two, based on observed reporting behaviour rather
than an assumption that last year is available. Every result carries `as_of`, and a query for a
year the source has not reported returns `empty` with a note naming the latest usable year.

### The server is spawned under `sys.executable`

Not under `python` from the PATH. The interpreter on the PATH is the system one, without this
project's dependencies, so a server started with it dies on `import mcp` — and from the agent's
side that is indistinguishable from a server with no tools. It happened: the first end-to-end
run produced a fluent, well-reasoned answer explaining that the sourcing tools were unavailable,
and every tool call in the trace looked fine because tool *results* were not being captured
either. Two silent failures compounding into a plausible output is the failure mode worth
guarding against, so `scripts/run_e2e.py` now fails a run unless both servers attached and all
five custom tools were actually called.

### A missing fixture is not a zero

Replay reported 0 percent duty where live reported 10, because a recording run on a warm cache
never wrote the tariff fixture, and a missing fixture then aborted the year-fallback chain
instead of moving to the next year. Both are fixed, and a chain with no fixture in *any* year
now raises explicitly. The general rule the incident illustrates: an absent value must never
reach the user as a low value, which is also why a portfolio row whose risk call failed is
marked `partial` rather than shown with a blank HHI.

## 5. Trade-offs taken knowingly

| Decision | Gained | Given up |
|---|---|---|
| Unit values from Comtrade instead of quoted prices | Free, no auth, every origin covered | A unit value is total value over total weight, not a price. Product mix inside an HS code moves it. |
| Great-circle distance from country reference points | Deterministic, no routing API, offline | Ignores actual routes, borders and corridors. A road distance can be 30 % longer. |
| MFN duty only | The only rate WITS exposes without auth | Preferential rates are the ones actually paid on a large share of trade. Flagged, not applied. |
| Min-max normalization within the candidate set | Scores are comparable and easy to explain | Scores are relative: adding a candidate rewrites every value. Stated as a caveat in the output. |
| HHI thresholds borrowed from competition policy | A recognisable, defensible bar | They were written for market concentration, not supply dependency. The analogy is deliberate and disclosed. |
| Five tools rather than three | Validation and risk each earn their own contract | More surface to document and keep correct. |
| One page, no framework | No build step, readable source, fast to review | No component library; charts were cut. |
| The landing screen calls the MCP server directly, with no model | The first screen is deterministic, instant and free; identical inputs give identical numbers, which a demo needs | It cannot answer anything not designed in. Interpretation is a separate, explicit action. |
| Portfolio fixed at six lines | Each line is a real Ukrainian import with enough volume to be worth screening | Not configurable at runtime. Adding a line is a code change. |
| Two model tiers instead of one | The long analysis run gets the capable model; a follow-up question costs $0.014 instead of $0.55 | Two configurations to keep correct, and the small tier can only answer from what is on screen. |
| Sequential portfolio queries, not concurrent | Six concurrent bursts is how a demo earns a 429 from Comtrade | A cold first load takes about 40 seconds. |

## 6. Known limitations

1. **Screening, not procurement.** The output narrows a list of countries worth investigating.
   It does not price a shipment, check supplier capability, or replace a tender.
2. **Freight is modelled.** Cost differences below roughly ten percent should not decide
   anything.
3. **Duty is MFN.** The EU DCFTA and other agreements are flagged, never applied.
4. **Two-year data lag** on annual trade, softened but not solved by the browser reading a
   current-year aggregate.
5. **Unit values are not prices**, and are unavailable at chapter level because Comtrade
   reports zero weight for aggregates. The tools refuse rather than divide by zero.
6. **LPI is static** at 2022 and treated as a structural factor.
7. **No quotas, TRQs, or non-tariff measures.** For food these can matter more than duty:
   sanitary and phytosanitary requirements can rule out an origin the score ranks first.
8. **Country-level, not supplier-level.** Nothing here says a capable exporter exists.
9. **The 500-record cap** can truncate a broad query; the result flags it rather than hiding it.
10. **Demo scope.** Six lines exercised end to end on live data: bananas 080390, tomatoes
    070200, mandarins 080521, grapes 080610, kiwifruit 081050, almonds 080212. Grapes is the
    most rehearsed and has the fullest fixture set. Other products work but are less proven.
11. **The customs page blocks automated clients.** `customs.gov.ua` answers HTTP 403 at its
    Akamai edge to anything that is not a human browser. The recency step therefore reaches its
    fallback, the National Bank's external-sector page, which confirms the publication vintage
    but carries no headline turnover figure — so the recency check is *partial* by design. The
    alternative, driving the user's own logged-in browser profile, was rejected: it would mean
    touching their real session and cookies for a figure that only qualifies staleness.

## 7. Credential configuration

The custom MCP server needs **no credentials at all** — all three APIs are open.

The agent needs a model credential, and the Claude Agent SDK resolves one of two:
`ANTHROPIC_API_KEY` if set, otherwise the local Claude Code login. `.env.example` documents both;
`.env` is git-ignored and no key appears anywhere in the repository or in source. The health
endpoint reports which of the two is in use, without revealing the value.
