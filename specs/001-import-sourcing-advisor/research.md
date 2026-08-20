# Phase 0: Decisions and What They Cost

There were no unresolved unknowns to research: every decision below was taken, implemented and
exercised before this document was written. So rather than record expected trade-offs, each entry
records the **measured** outcome, and the alternatives are the ones actually rejected — several of
them rejected only after being tried.

---

## D1. Agent framework: Claude Agent SDK, not a graph library

**Decision**: Drive the agent with the Claude Agent SDK, configuring providers declaratively.

**Rationale**: The SDK lets the capability surface be closed completely. An empty built-in tool
set means the agent has no shell, no filesystem and no general web access, so every figure in an
answer must have arrived through a declared contract. Providers, their allow-lists, the model, the
effort level and the turn ceiling are all one configuration object, which is what makes a run
reproducible on another machine.

**Alternatives considered**:

- **LangGraph with an MCP adapter and a third-party model gateway** — the original plan, recorded
  in the project brief. Rejected on reaching implementation: reaching the same closed capability
  surface needed a separate adapter plus manual control over what the model could see, which is
  more moving parts for the property that matters most here.
- **A hand-written tool loop.** Rejected: it would have re-implemented provider lifecycle,
  allow-listing and trace extraction, none of which is this project's contribution.

**Cost, measured**: One non-obvious failure mode. The SDK reports tool *results* on a separate
message type from the assistant turn that requested them; watching only the assistant turn yields
a trace of calls with no outcomes, in which every call appears to have succeeded. See D7.

---

## D2. Two model tiers, split by question shape

**Decision**: A capable model at high effort with both providers for a full analysis; a small
model at low effort, three read-only tools and no browser for questions about an already-computed
result, handed the on-screen figures as context.

**Rationale**: A long multi-step analysis and "which of these lines would you fix first" are not
the same problem. In the first, a wrong turn wastes rate-limited upstream calls. In the second,
the numbers are already on screen and the work is interpretation.

**Cost, measured**: Full analysis 20 turns, 620 s, **$0.547**. Follow-up question 1 turn, 19 s,
**$0.014** — a fortieth of the cost, against a target of a twentieth. The follow-up ran without
recomputing anything, which is the point: passing the screen's figures as context is what stops a
one-number question from re-running a ten-minute flow.

**Alternatives considered**: One tier for everything. Rejected once the portfolio existed — the
most natural question a portfolio provokes is comparative, and comparative questions would each
have cost a full analysis.

---

## D3. The landing screen calls the capability layer directly, with no model

**Decision**: Compute the portfolio over a client session against the same capability server the
agent uses, with no model in the loop.

**Rationale**: Three properties the first screen needs and a model cannot give: it is instant, it
is free, and it returns identical figures on every run. A screen that opens before any question is
asked has to be all three.

**Cost, measured**: 2.3 s warm. Cold is bounded by the upstream one-request-per-second limit over
roughly eighteen requests, so tens of seconds — which is why the result is cached per reference
year and a refresh is an explicit action.

**Alternatives considered**:

- **Ask the agent to build the portfolio.** Rejected: six lines of arithmetic per load, paid for
  every time, with a different wording each run.
- **Import the tool functions in-process** rather than going over a client session. Rejected: it
  would put the read path *around* the contract boundary instead of through it, and the claim that
  every figure on screen came from a declared contract would stop being literally true. The
  in-process import is used only in the offline smoke script, which is a test harness.

---

## D4. Six product lines, chosen for signal rather than symmetry

**Decision**: Track bananas, tomatoes, mandarins, grapes, kiwifruit and shelled almonds, all at
six-digit classification level.

**Rationale**: Six digits rather than four because a four-digit heading mixes fresh and dried
forms of the same fruit, whose unit values differ enough to make a price comparison meaningless.
The specific six were selected by checking candidates against live data and keeping the ones with
enough import volume to be worth screening.

**What the data changed**: Apples and walnuts-in-shell were in the first draft and were dropped
after measurement — apples import at $0.5M and walnuts at essentially zero, because Ukraine grows
and exports both. Their import lines are noise. The replacements were chosen partly for lead-
supplier diversity: the final six have four different leading origins.

**The finding that justified the portfolio at all**: three of the six lines lead back to Türkiye.
That is a shared point of failure invisible in any single line, and it is the strongest argument
for a portfolio view over a per-product report.

---

## D5. Ordered fallbacks for the currency check, and naming the source read

**Decision**: Try the customs page first, then the central bank's external-sector page, then a
third source; require the agent to name which one it actually read.

**Rationale**: Forced by measurement. The customs page returns **HTTP 403** to automated clients
at its edge while opening normally in a human browser — verified for the page, the site root, and
with a browser user agent, all 403. The first end-to-end run failed this step for exactly this
reason.

**Alternatives considered**:

- **Drive the user's own logged-in browser profile** to inherit their session. Rejected on
  principle: touching a person's real browser session and cookies is disproportionate for a figure
  whose only job is to qualify staleness.
- **Drop the currency check.** Rejected: the two-year lag on annual statistics is the single
  largest weakness in the output, and an independent check on it is worth having even partial.
- **Silently substitute the fallback.** Rejected: which source a number came from is part of the
  number.

**Cost**: The check is *partial* by design. The fallback confirms the publication frontier but
carries no headline turnover figure, so the vintage is established and the magnitude is not. The
agent says so.

---

## D6. Fixture substitution at the transport boundary only

**Decision**: Record verbatim source responses and replay them at the single function where
network access happens, so every parser, deduplication step and calculation above it runs
unchanged. A request with no recording is refused, never defaulted.

**Rationale**: The property worth having is not "there is an offline mode" but "offline produces
the same numbers". Substituting anywhere higher would mean the offline path exercises different
code than the live path, and the equality would be a coincidence.

**Verified**: Delivered cost for the grape case returns duty 10.0% and $1.4566/kg in both modes,
identical to the last decimal. All six portfolio lines match live offline.

**Cost, measured**: 61 recorded responses, committed. Two defects found on the way — see D7.

---

## D7. Four defects this project found in itself

Recorded because in each case the mechanism generalises and the fix does not.

1. **A server spawned under the wrong interpreter looked like a server with no tools.** The
   capability server was started with the bare interpreter name, which resolves to the system
   interpreter without this project's dependencies. That process died on import. The agent saw
   only the browser provider and correctly refused to invent an answer — producing a fluent,
   well-reasoned, completely useless response. *Lesson: a total failure can present as a
   competent answer.* Now spawned under the running interpreter, and the end-to-end check fails
   unless both providers attached and all five capabilities were called.

2. **Tool results were never captured, so every call looked successful.** Results arrive on a
   different message type than the requesting turn. The trace showed calls with no outcomes, and
   the end-to-end check that read it reported "no errors" on a run containing a rate-limited call.
   *Lesson: a verification that cannot fail is not a verification.*

3. **Recording on a warm cache silently skipped the fixture write.** The cache-hit branch returned
   before writing, so any response already cached was absent from the recorded set. This is how
   the most-exercised value in the whole demo — the grape tariff — ended up with no recording at
   all, and offline consequently reported 0% duty where live reported 10%. *Lesson: a cache is a
   correctness surface, not only a speed one.*

4. **An unscorable ranking criterion scored exactly like a bad one.** A weighted sum treats a
   missing term as a zero term, so a candidate whose cost could not be priced scored 15 out of 100
   beside a fully priced candidate's 90. The per-factor decomposition carried its nulls correctly;
   nobody had checked what the *aggregate* of a null does. *Lesson: nulls handled correctly at the
   leaves can still be wrong at the root.*

The common thread in all four: an absent thing quietly becoming a present-but-wrong thing. That
is why it is a constitutional principle rather than four separate bug fixes.

---

## D8. Rejected outright

- **Any internal company data.** A hard boundary, not a scoping decision. It is what makes the
  tool shareable and it is why the tool is macro-level.
- **A charting library.** Cut deliberately: a share bar next to a printed number carries the
  scanning value, and the number stays the fact. No build step survives in the project as a
  result.
- **Renormalising a partial ranking score.** See the Complexity Tracking table in the plan.
- **Quoted freight rates.** No open source publishes them, so the choice was between a labelled
  model and no cost comparison at all.
