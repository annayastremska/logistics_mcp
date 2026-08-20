# Phase 1: Interface Contracts

This project publishes contracts at two boundaries. The **capability boundary** is the important
one and is already documented in full at [`docs/tool-contracts.md`](../../../docs/tool-contracts.md)
— 458 lines covering every input field, output field, error mode and side effect for all five
custom tools plus the browser tool actually used. That document is authoritative and is not
duplicated here.

What follows is an index of it, plus the **read-path boundary**, which had no written contract
before this document.

---

## Capability boundary — five published tools

Transport is stdio. Every tool declares an input schema **and** an output schema; a tool declaring
only inputs would be incomplete, because a caller cannot then know what it is receiving. All five
are read-only and none requires a credential.

| Tool | Purpose | Reaches the network |
|---|---|---|
| `validate_sourcing_brief` | Resolve and validate a request against the nomenclature before any quota is spent | No — `openWorldHint: false` |
| `get_import_flows` | Who actually supplies a product, with values, quantities, unit values and shares | Yes |
| `assess_supply_concentration_risk` | Concentration, effective source count, volatility, mirror gap, named risk flags | Yes |
| `estimate_landed_cost` | Itemised delivered cost for one origin and volume, each line marked measured or estimated | Yes |
| `rank_sourcing_countries` | Composite score per candidate with full factor decomposition | Yes |

**Contract properties that hold across all five**, and are the reason these are tools rather than a
generic HTTP wrapper:

- Three-state `status` (`ok` / `empty` / `error`); `empty` is an answer, not a failure.
- Named error codes with the offending field; never a stack trace, never a silently corrected value.
- `Provenance` on every data-bearing result: source, live-or-recorded, reference period, and
  whether values are measured or estimated.
- Upstream quirks are handled inside the contract, not exposed. The most consequential: the trade
  source repeats every partner once per value of the origin-versus-consignment dimension, so a
  generic wrapper would hand the caller double-counted shares. The tool collapses that dimension
  and reports how many rows it dropped.

Inspect the published contracts with no agent present:

```bash
python scripts/inspect_tools.py           # summary of all five
python scripts/inspect_tools.py --json    # full input and output JSON schemas
```

---

## Existing provider boundary — browser automation

One tool is load-bearing: `browser_navigate`. One required string argument (`url`); returns page
state and an accessibility snapshot as **text, not structured data**; fails on unreachable host,
timeout, HTTP error, blocked navigation, or browser launch failure.

Its side effects are substantially unlike the custom tools' — it launches a browser process, makes
a real network request and executes page JavaScript — which is why it runs with a fresh isolated
profile and why the browser is pointed at a short, fixed list of hosts. Full contract in
[`docs/tool-contracts.md`](../../../docs/tool-contracts.md#existing-server-microsoft-playwright-mcp).

---

## Read-path boundary — HTTP endpoints

Consumed only by this project's own interface page. Documented because the interface depends on
these shapes, and because two of them stream.

| Method | Path | Returns |
|---|---|---|
| `GET` | `/` | The interface page |
| `GET` | `/api/health` | Data mode, analysis model, credential source, and both providers with their declared tools |
| `GET` | `/api/tracked` | The tracked product lines and their groups, for filter controls |
| `GET` | `/api/portfolio?year&refresh` | Every tracked line with its concentration reading, ordered worst-first |
| `GET` | `/api/commodity/{hs_code}?year` | Full origin breakdown and risk detail for one line |
| `GET` | `/api/run?question&replay&playwright&break_playwright` | **Server-sent events**: one full agent analysis, streamed |
| `GET` | `/api/chat?question&context` | **Server-sent events**: one follow-up answer on the small model |

**Contract notes**

- `/api/portfolio` is computed with **no model in the loop** and is cached per reference year in
  process. Identical inputs return identical figures. `refresh=true` bypasses the cache. A build
  is serialised behind a lock so a page reload cannot start a second one.
- The two streaming endpoints emit one JSON object per event with a `kind` field: `status`,
  `tool_call`, `tool_result`, `text`, `thinking`, `error`, `done`. A `tool_call` and its
  `tool_result` are separate events. The stream terminates with a named `end` event.
- Streaming is one-way server-to-client, which is why server-sent events rather than a bidirectional
  socket: the client sends one request and then only reads, and the transport reconnects on its own.
- `break_playwright=true` points the browser at an unresolvable host **and disables the fallback
  chain**, so the failure demonstrated is the provider's own rather than one a fallback quietly
  rescues. The failure is produced by changing the input, never by faking an error.
- Errors are emitted as an `error` event on the stream rather than as an HTTP status, because the
  response has already begun by the time most failures occur.
