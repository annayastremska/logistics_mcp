---

description: "Task list for Import Sourcing Advisor"
---

# Tasks: Import Sourcing Advisor

**Input**: Design documents from `/specs/001-import-sourcing-advisor/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Tests are included. The specification's integrity requirements (FR-020 to FR-026) are
not demonstrable without them, and the project constitution makes verification non-negotiable.

**Organization**: Grouped by user story, so each story is independently implementable and testable.

> ## Read this before using the list
>
> **This is a retrospective task list.** The system was built before these process artefacts were
> written, so a task is checked `[x]` only where a run in the delivery log proves it, and left
> `[ ]` only where the work is genuinely outstanding. Nothing is checked on the strength of code
> existing — the whole reason this project has a rule about verification is that a plausible-looking
> implementation passed for a working one twice.
>
> **Current state: 68 of 69 tasks complete.** The one open task is T069. Every regression test is mutation-checked -- the behaviour it covers is reverted to confirm
> the test actually fails, because a test that cannot fail is not a test. 47 tests, offline, ~1.6s.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US4)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and structure

- [x] T001 Create the three-layer structure — capability server, agent, read path — per plan.md
- [x] T002 Declare pinned dependencies in requirements.txt (mcp, pydantic, claude-agent-sdk, fastapi, uvicorn, pytest)
- [x] T003 [P] Document configuration surface in .env.example with no real values
- [x] T004 [P] Exclude secrets, caches and browser session artefacts in .gitignore

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The contract and transport layer every user story depends on

**⚠️ CRITICAL**: No user story works until this phase is complete

- [x] T005 Define the three-state status and named error codes in mcp_server/models.py
- [x] T006 Define Provenance and attach it to every data-bearing result in mcp_server/models.py
- [x] T007 Build the single transport boundary — rate limit, cache, fixture record and replay — in mcp_server/sources/http.py
- [x] T008 [P] Vendor the nomenclature and country tables under data/reference/ because the upstream preview returns codes without labels
- [x] T009 [P] Implement nomenclature lookup, country resolution and great-circle distance in mcp_server/sources/reference.py
- [x] T010 Implement the trade-flow client with origin-versus-consignment deduplication in mcp_server/sources/comtrade.py
- [x] T011 [P] Implement the tariff client with year fallback in mcp_server/sources/wits.py
- [x] T012 [P] Implement the logistics-index client in mcp_server/sources/worldbank.py
- [x] T013 [P] Implement concentration, volatility, mirror gap and normalisation in mcp_server/domain/analysis.py
- [x] T014 [P] Implement itemised delivered cost with duty on the CIF base in mcp_server/domain/costing.py
- [x] T015 Register all five tools with declared input **and** output schemas in mcp_server/server.py
- [x] T016 [P] Publish the contracts with no agent present via scripts/inspect_tools.py

**Checkpoint**: Capability layer starts and is inspectable alone — quickstart scenario 1.

---

## Phase 3: User Story 1 — See where the exposure is (Priority: P1) 🎯 MVP

**Goal**: A portfolio of tracked import lines, worst-first, legible before anything is asked.

**Independent Test**: Open the landing view with no interaction; confirm every line renders with
its concentration figures, worst first, and that filters change what is shown.

### Tests for User Story 1

- [x] T017 [P] [US1] Cover concentration and effective-source arithmetic in tests/test_domain.py
- [x] T018 [P] [US1] Cover the asymmetric mirror-gap threshold in tests/test_domain.py
- [X] T019 [P] [US1] Cover portfolio row assembly and severity ordering in tests/test_portfolio.py

### Implementation for User Story 1

- [x] T020 [US1] Implement the concentration tool with named risk flags in mcp_server/server.py
- [x] T021 [US1] Define the tracked lines, chosen against live volume, in web/portfolio.py
- [x] T022 [US1] Build the portfolio over one client session with no model in web/portfolio.py
- [x] T023 [US1] Order rows worst-first by flag severity in web/portfolio.py
- [x] T024 [US1] Mark a row `partial` when flows resolve but risk does not, so absent never reads as low, in web/portfolio.py
- [x] T025 [US1] Serve the portfolio with per-year caching behind a lock in web/app.py
- [x] T026 [US1] Render the portfolio table with share bars and flag pills in web/index.html
- [x] T027 [US1] Add search, group and severity filters with a shown-versus-total count in web/index.html
- [x] T028 [US1] Detect and state a lead supplier shared across several lines in web/index.html
- [x] T029 [US1] Give every severity a glyph as well as a colour in web/index.html

**Checkpoint**: Quickstart scenarios 4 and 5 pass. Türkiye is named as leading three of six lines.

---

## Phase 4: User Story 2 — Understand one line (Priority: P2)

**Goal**: The full origin breakdown for one line, with its caveats visible.

**Independent Test**: Open any line and confirm all origins, the concentration reading and the
source caveats appear, with no analysis run.

### Tests for User Story 2

- [x] T030 [P] [US2] Cover flow deduplication and aggregate-partner exclusion in tests/test_domain.py

### Implementation for User Story 2

- [x] T031 [US2] Implement the flows tool reporting dropped duplicates and truncation in mcp_server/server.py
- [x] T032 [US2] Refuse a unit-value comparison where quantities are unreported in mcp_server/server.py
- [x] T033 [US2] Add the line-detail endpoint in web/app.py
- [x] T034 [US2] Render KPIs, the origin table and the plain-language reading in web/index.html
- [x] T035 [US2] Label unit values as derived, not market prices, at point of display in web/index.html
- [x] T036 [US2] Surface deduplication and mirror-gap caveats on screen in web/index.html

**Checkpoint**: Tomatoes detail shows 17 origins, Türkiye $81.2M / 71.8%, 18 duplicates collapsed.

---

## Phase 5: User Story 3 — Ranked recommendation (Priority: P3)

**Goal**: A full agentic analysis on one line, ending in a ranked, explained recommendation.

**Independent Test**: Request an analysis; confirm it reaches a ranking, that the concentration
finding changed the candidate set, and that every step is recorded.

### Tests for User Story 3

- [x] T037 [P] [US3] Cover duty on the CIF base and no double-counted freight in tests/test_domain.py
- [x] T038 [P] [US3] Cover modelled components carrying an estimated label in tests/test_domain.py
- [x] T039 [P] [US3] Cover partial ranking declaring its scored weight in tests/test_domain.py
- [x] T040 [US3] Assert on substance end to end — both providers attached, all five tools called — in scripts/run_e2e.py

### Implementation for User Story 3

- [x] T041 [US3] Implement brief validation that fails before spending quota in mcp_server/server.py
- [x] T042 [US3] Implement the delivered-cost tool with per-component measurement labels in mcp_server/server.py
- [x] T043 [US3] Implement ranking with full factor decomposition in mcp_server/server.py
- [x] T044 [US3] Declare scored weight and name unscored criteria so a gap never reads as a bad score, in mcp_server/server.py
- [x] T045 [US3] Wire both providers with an empty built-in tool set and no inherited local settings in agent/sourcing_agent.py
- [x] T046 [US3] Spawn the capability server under the running interpreter, not the PATH name, in agent/sourcing_agent.py
- [x] T047 [US3] Order the recency sources and require the agent to name the one it read, in agent/sourcing_agent.py
- [x] T048 [US3] Capture tool results from the message type that carries them, in agent/sourcing_agent.py
- [x] T049 [US3] Make the concentration finding drive candidate widening and reweighting, via the system prompt in agent/sourcing_agent.py
- [x] T050 [US3] Stream the run and render the call trace in web/app.py and web/index.html
- [x] T051 [US3] Add the failure demo — unresolvable host, fallbacks disabled — in agent/sourcing_agent.py and web/index.html

**Checkpoint**: Quickstart scenarios 6 and 7 pass. Failure run still reaches a recommendation and
names the failed check in what would change it.

---

## Phase 6: User Story 4 — Cheap follow-up questions (Priority: P4)

**Goal**: Interpret what is on screen without recomputing it.

**Independent Test**: Ask a comparative question with a portfolio on screen; confirm the answer
cites the displayed figures and returns in seconds.

- [x] T052 [US4] Add the small-model profile — no browser, three read-only tools — in agent/sourcing_agent.py
- [x] T053 [US4] Pass on-screen figures as context so a follow-up does not rerun the flow, in agent/sourcing_agent.py
- [x] T054 [US4] Add the follow-up streaming endpoint in web/app.py
- [x] T055 [US4] Build the context payload and chat panel in web/index.html

**Checkpoint**: Quickstart scenario 8 passes — 1 turn, 19 s, $0.014.

---

## Phase 7: Cross-Cutting (complete)

- [x] T056 [P] Write the five tool contracts and the browser tool contract in docs/tool-contracts.md
- [x] T057 [P] Write the design rationale, trade-offs and limitations in docs/design-rationale.md
- [x] T058 [P] Write the defence walkthrough in docs/demo-checklist.md
- [x] T059 [P] Write installation, verification and layout in README.md
- [x] T060 Record fixtures covering all six lines so the portfolio renders offline
- [x] T061 Write the fixture on a warm cache hit, so a recording set cannot be silently incomplete, in mcp_server/sources/http.py
- [x] T062 Continue the tariff year-fallback past a missing recording, in mcp_server/sources/wits.py
- [x] T063 Run quickstart.md scenarios 0 through 9 and record observed values

---

## Phase 8: Open Work

**Purpose**: Regression cover for defects fixed without a test, plus one limitation found while
writing the quickstart. Ordered by risk of the defect silently returning.

- [x] T064 [P] Add a regression test asserting tool results are captured, so a trace of calls with no outcomes fails a build, in tests/test_agent_trace.py
- [x] T065 [P] Add a regression test asserting a recording is written on a warm cache hit, in tests/test_http_transport.py
- [x] T066 [P] Add a regression test asserting the tariff fallback survives one missing recording and raises when all are missing, in tests/test_http_transport.py
- [x] T067 [P] Add a regression test asserting the capability server is spawned under the running interpreter, in tests/test_agent_config.py
- [X] T068 Record fixtures for a second reference window, so offline is not pinned to one period — the year selector was removed in the interface rebuild, which hid the problem rather than fixing it, in fixtures/
- [ ] T069 Run /speckit-converge to check the delivered system against this specification rather than assuming they agree

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies
- **Foundational (Phase 2)**: depends on Setup — **blocks every user story**
- **User stories (Phases 3–6)**: all depend on Phase 2; independent of each other thereafter
- **Cross-cutting (Phase 7)**: depends on the stories it documents
- **Open work (Phase 8)**: depends on Phase 2 only; every task is independent of the others

### User Story Dependencies

- **US1 (P1)**: needs only Phase 2. This is the MVP and delivers value with zero interaction.
- **US2 (P2)**: needs only Phase 2. Reached from US1 in the interface, but independently testable
  by requesting a line detail directly.
- **US3 (P3)**: needs only Phase 2. Independently testable through `scripts/run_e2e.py` with no
  interface at all.
- **US4 (P4)**: needs Phase 2, and needs figures on screen to be useful — so it is the one story
  that is not independently *valuable*, though it is independently testable.

### Within Each User Story

Contracts and models before tools; tools before endpoints; endpoints before interface. Tests for
the arithmetic go alongside the domain function they cover, not after the interface.

### Parallel Opportunities

- T003, T004 in Setup
- T008, T009, T011, T012, T013, T014, T016 in Foundational — separate modules, no shared state
- All four story phases, once Phase 2 is done
- Every task in Phase 8 except T068, which touches the interface as well as fixtures

---

## Parallel Example: Phase 8

```bash
# Four independent regression tests, four separate files:
Task: "Assert tool results are captured in tests/test_agent_trace.py"
Task: "Assert a fixture is written on a warm cache hit in tests/test_http_transport.py"
Task: "Assert the tariff fallback survives a missing recording in tests/test_http_transport.py"
Task: "Assert the server is spawned under the running interpreter in tests/test_agent_config.py"
```

---

## Implementation Strategy

### MVP first (User Story 1 only)

Phase 1 → Phase 2 → Phase 3, then stop and validate. The portfolio alone is a viable product: it
answers "where should I look first?" with no question asked, no model cost and no waiting. If
nothing else had been built, that screen would still have been worth shipping.

### Incremental delivery

1. Setup + Foundational → capability layer starts and publishes its contracts
2. + US1 → portfolio renders, worst-first, deterministic (**MVP**)
3. + US2 → any line drills to its origins
4. + US3 → a line escalates to a ranked recommendation
5. + US4 → the screen becomes conversational

Each step is demonstrable on its own and none breaks the previous.

### What the sequence got wrong, for the next feature

The interface was built chat-first and rewritten as a portfolio after the first review. Rebuilding
was cheap only because the capability layer was already contract-clean and had no interface
assumptions in it — the rewrite touched `web/` and nothing below it. The lesson is not "plan the
interface harder"; it is that a clean capability boundary is what makes an interface disposable.

One cost of the rewrite is recorded in the delivery log: it silently dropped two demo controls the
defence walkthrough depended on, which was only caught by re-reading that walkthrough against the
new page. A rewrite should end with a pass over every document that describes the thing rewritten.

---

## Notes

- `[P]` means different files and no dependency on incomplete work
- `[Story]` maps a task to a user story for traceability
- Checked tasks are backed by a recorded run; see quickstart.md for the observed values
- Phase 8 exists because four defects were fixed without regression cover. A fix without a test is
  a fix with a return date.
