# Feature Specification: Import Sourcing Advisor

**Feature Branch**: `001-import-sourcing-advisor`

**Created**: 2026-08-20

**Status**: Draft

**Input**: User description: "Import sourcing advisor for Ukraine: a custom MCP server exposing five tools over UN Comtrade, WITS TRAINS and the World Bank Indicators API, driven by a Claude Agent SDK agent that also uses the existing Playwright MCP server for a current-year recency check, with a portfolio-style decision screen as the landing view. The system must let a procurement analyst see concentration risk across tracked import lines before asking anything, drill into one line's origin breakdown, and run a full agentic sourcing analysis on demand that ranks alternative origins by landed cost, logistics, duty and supply stability."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - See where the exposure is, before asking anything (Priority: P1)

A procurement analyst responsible for a basket of imported product lines opens the tool and
immediately sees which lines are dangerously dependent on a single country of origin, ranked
worst first. They do not type a question, choose a product, or wait for an analysis to run. Each
line shows how much is imported, which country leads and by how much, how many meaningfully
independent sources exist behind that leader, how much the line has swung year to year, and
which named risk conditions apply. The analyst can narrow the view to one product family, or to
only the lines that carry a serious flag.

**Why this priority**: This is the whole reason to open the tool rather than a spreadsheet. It
answers "where should I look first?" — a question the analyst cannot answer without seeing every
line side by side, and which no per-product report gives them. It is also the only story that
delivers value with zero further interaction, so it is a viable product on its own.

**Independent Test**: Open the landing view with no prior interaction. It is fully testable by
confirming that every tracked line appears with its concentration figures, that the worst line
is first, and that filtering by family and by severity changes which lines are shown. Value is
delivered the moment the screen renders.

**Acceptance Scenarios**:

1. **Given** the analyst has just opened the tool, **When** the landing view finishes loading,
   **Then** every tracked product line is listed with its import value, leading origin and that
   origin's share, the effective number of independent sources, the year-on-year swing, and any
   risk conditions that apply — ordered with the most exposed line first.
2. **Given** the landing view is showing all lines, **When** the analyst filters to only lines
   carrying a serious risk condition, **Then** only those lines remain and the count of shown
   versus total lines is stated.
3. **Given** several independent lines are led by the same country, **When** the landing view
   renders, **Then** that shared dependency is stated explicitly, naming the country and how
   many lines it leads.
4. **Given** a line's import figures were obtained but its risk assessment could not be,
   **When** that line renders, **Then** it is marked as incomplete rather than shown with an
   empty risk figure.

---

### User Story 2 - Understand one line well enough to act (Priority: P2)

Having spotted an exposed line, the analyst opens it and sees every origin that supplies it, not
just the leader: each origin's value, its share, the quantity, and the value-per-unit implied by
those two. Alongside sits the line's concentration reading in plain language, and any caveat the
underlying data carries — duplicate records that had to be collapsed, or a discrepancy between
what Ukraine reports importing and what its partners report exporting.

**Why this priority**: Knowing a line is concentrated is not actionable; knowing who else
already ships it is. This is the step that turns a flag into a shortlist, and it needs no model
reasoning, so it is fast and repeatable.

**Independent Test**: Open any line from the landing view and confirm the full origin table,
the concentration reading and the data caveats appear. Testable without running any analysis.

**Acceptance Scenarios**:

1. **Given** the analyst selects a line, **When** the detail opens, **Then** all reported
   origins are listed in descending order of value, each with its share, quantity and implied
   value per unit.
2. **Given** an implied value per unit is shown, **When** the analyst reads it, **Then** it is
   labelled as a derived statistical figure rather than a market price.
3. **Given** the underlying records required collapsing or disagree with partner reporting,
   **When** the detail opens, **Then** those caveats are stated on screen, not hidden.

---

### User Story 3 - Get a ranked recommendation for one line (Priority: P3)

For a line worth acting on, the analyst asks for a full analysis. The system independently
establishes how current its statistical picture is, confirms the product is what the analyst
meant, establishes who supplies it today, judges how concentrated that supply is, and — when
supply proves concentrated — deliberately looks beyond the incumbent leaders rather than
reinforcing the existing dependency. It then estimates what each candidate origin would cost
delivered and ranks the candidates on cost, logistics quality, applicable duty and demonstrated
supply. The analyst sees the recommendation, the few facts it rests on, what would change it,
and a step-by-step record of every action the system took to get there.

**Why this priority**: This is the highest-value output but also the slowest and most expensive,
and it is only worth requesting once the first two stories have identified where to point it.
Making it deliberate rather than automatic is the point.

**Independent Test**: Request an analysis for one line and confirm the run reaches a ranked
recommendation, that the concentration finding visibly changed which candidates were considered,
and that every step is recorded and inspectable.

**Acceptance Scenarios**:

1. **Given** the analyst requests an analysis for a line, **When** the run proceeds, **Then**
   each step is shown as it happens, naming the capability used and whether it succeeded.
2. **Given** the supply for that line proves concentrated, **When** the system chooses candidate
   origins, **Then** it considers origins beyond the current leaders and says why, rather than
   ranking only the incumbents.
3. **Given** the analysis completes, **When** the analyst reads the recommendation, **Then** it
   names the reference year of its data, distinguishes measured figures from modelled ones, and
   states what would change the conclusion.
4. **Given** any figure in the output was modelled rather than observed, **When** it is
   presented, **Then** it is labelled as such at the point of use.

---

### User Story 4 - Ask a follow-up without paying for a rerun (Priority: P4)

The analyst wants to interpret what is on screen — which line to fix first, whether a swing is
seasonal, how two lines compare. They ask in plain language and get a short answer grounded in
the figures already displayed, quickly and cheaply, without the system recomputing an analysis
to restate a number it already has.

**Why this priority**: Useful, but strictly secondary: it interprets what the first three
stories produced and delivers nothing on its own.

**Independent Test**: With a portfolio on screen, ask a comparative question and confirm the
answer references the displayed figures and returns in seconds rather than minutes.

**Acceptance Scenarios**:

1. **Given** figures are on screen, **When** the analyst asks a question answerable from them,
   **Then** an answer arrives without a full analysis being run.
2. **Given** the question needs a figure not on screen, **When** it is answered, **Then** the
   system retrieves that figure rather than guessing it.

---

### Edge Cases

- **A requested period has no data.** The source genuinely holds no record for that product and
  year. This is a valid answer, not a failure: the system reports it as empty, states the latest
  usable period, and does not retry.
- **A product identifier does not exist.** The request is rejected with a named reason before
  any data quota is spent, rather than being silently coerced to a neighbouring product.
- **A product identifier exists but is a residual "not specified" bucket.** It is accepted,
  because it is a real classification, but nothing downstream pretends it is a specific product.
- **A requested aggregation is too coarse for a unit comparison.** Quantities are not reported at
  aggregate level, so a value-per-unit cannot be derived. The system refuses to divide rather
  than reporting a meaningless figure.
- **The current-year reference page refuses automated access.** A source that opens for a person
  can block a program. The system tries alternatives in order, names which one it actually read,
  and if all fail marks the currency check failed and continues on statistical data alone with an
  explicit staleness warning.
- **An external source rate-limits or times out mid-analysis.** The affected step reports an
  error distinct from "no data", and the analysis continues with the remaining candidates rather
  than aborting.
- **Ranking weights that do not sum to a whole.** Rejected with a named reason, because a
  silently renormalised weighting would misrepresent the analyst's stated priorities.
- **A result set exceeds the source's per-request cap.** The result declares that it was
  truncated instead of presenting a partial list as complete.
- **A country's reported imports disagree with its partners' reported exports.** Some gap is
  structurally normal because the two are valued on different bases; only a gap outside the
  expected direction and magnitude is flagged.
- **Adding a candidate changes every score.** Scores are relative to the compared set, and the
  output says so.

## Requirements *(mandatory)*

### Functional Requirements

**Portfolio view**

- **FR-001**: System MUST present, on first load and without any user input, every tracked
  product line with its import value, leading origin, that origin's share, the effective number
  of independent sources, year-on-year variability, and applicable risk conditions.
- **FR-002**: System MUST order the portfolio by severity of exposure, most exposed first.
- **FR-003**: Users MUST be able to narrow the portfolio by product name or identifier, by
  product family, and by minimum severity.
- **FR-004**: System MUST identify and state when one origin leads several otherwise independent
  lines, naming the origin and the number of lines affected.
- **FR-005**: System MUST distinguish a line whose risk assessment is unavailable from a line
  whose risk is low, and MUST NOT render an absent figure in a way that reads as a low one.
- **FR-006**: System MUST produce the portfolio deterministically — identical inputs yield
  identical figures — and without incurring per-use model cost.

**Line detail**

- **FR-007**: System MUST list, for a selected line, every reported origin with its value,
  share, quantity and derived value per unit, in descending order of value.
- **FR-008**: System MUST label any derived value per unit as a statistical derivation rather
  than a market price, at the point where it is displayed.
- **FR-009**: System MUST surface data-quality caveats attached to a line — collapsed duplicate
  records, partner-reporting discrepancies, truncated result sets — on screen rather than only
  in logs.

**Analysis**

- **FR-010**: System MUST establish how current its statistical picture is by reading an
  independent current-period source, and MUST name which source it actually read.
- **FR-011**: System MUST validate and resolve the requested product before spending any data
  quota, and MUST stop with a named reason rather than guessing when it cannot.
- **FR-012**: System MUST let the concentration finding change the subsequent analysis: when
  supply is concentrated, the candidate set MUST reach beyond the current leading origins, and
  the reason MUST be stated.
- **FR-013**: System MUST estimate a delivered cost per candidate origin, itemised, with every
  component labelled as measured or modelled.
- **FR-014**: System MUST rank candidates on cost, logistics quality, applicable duty and
  demonstrated supply, and MUST disclose each factor's contribution to each score.
- **FR-015**: System MUST record every step of an analysis — which capability was used, with
  what inputs, and whether it succeeded — and MUST make that record inspectable by the user.
- **FR-016**: System MUST state the reference period of the data behind any conclusion.
- **FR-017**: System MUST close an analysis with the recommendation, the few facts supporting
  it, and what would change it.

**Follow-up questions**

- **FR-018**: Users MUST be able to ask a question about the figures currently displayed and
  receive an answer without a full analysis being rerun.
- **FR-019**: System MUST answer such questions from the displayed figures where possible, and
  retrieve rather than invent any figure not displayed.

**Integrity and failure handling**

- **FR-020**: System MUST distinguish three outcomes for every retrieval — succeeded, genuinely
  empty, and failed — and MUST NOT treat an empty result as an error.
- **FR-021**: System MUST reject malformed or contradictory inputs with a named, machine-readable
  reason rather than a stack trace or a silently corrected value.
- **FR-022**: System MUST NOT present a modelled figure as an observed one anywhere in its output.
- **FR-023**: System MUST continue to a useful answer when a non-essential input is unavailable,
  degrading the answer and saying so, rather than aborting.
- **FR-024**: System MUST be operable with no network access, serving previously recorded source
  responses, and MUST produce the same figures in that mode as with live access.
- **FR-025**: System MUST refuse to answer from recorded responses for a request it has no
  recording of, rather than substituting a default.
- **FR-026**: System MUST convey severity through more than colour alone, so the ranking remains
  readable without colour perception.

**Operational independence**

- **FR-027**: The capability layer MUST be startable and inspectable independently of the
  analysis layer, and MUST publish a declared contract for each capability it offers.
- **FR-028**: System MUST report which external capability providers it connected to and which
  capabilities each provided, as observed at connection time rather than as configured.
- **FR-029**: System MUST operate entirely on publicly available data and MUST require no
  credential for any data source.

### Key Entities

- **Product line**: One tracked import category — an identifier, a display name and a family.
  The unit of the portfolio.
- **Origin flow**: What one country supplied of one product line in one period: value, quantity,
  derived value per unit, and share of the period total.
- **Concentration reading**: How dependent a product line is on few origins — a concentration
  measure, the effective number of independent sources, the leading origin and its share,
  year-on-year variability, the gap against partner reporting, and the named risk conditions
  that follow.
- **Risk condition**: A named, ordered severity, so lines are comparable without interpreting
  raw measures.
- **Delivered cost estimate**: For one origin and one quantity, an itemised cost with each
  component marked measured or modelled, plus a stated confidence and the assumptions used.
- **Candidate ranking**: An ordered set of origins with scores, each score decomposed into the
  contribution of every factor, the weights applied, and any candidate excluded with its reason.
- **Analysis record**: The ordered sequence of steps one analysis took, each naming the provider,
  the capability, the inputs and the outcome.
- **Recorded source response**: A stored external response with the exact request it answered
  and when it was retrieved, enabling operation without network access.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An analyst can identify the most exposed product line within 10 seconds of the
  landing view rendering, without typing anything or making a selection.
- **SC-002**: The landing view renders every tracked line on a warm cache in under 5 seconds,
  and on a cold cache in under 60 seconds.
- **SC-003**: A shared dependency spanning multiple lines is stated on the landing view whenever
  one exists, and is found in 100% of cases where one origin leads more than one line.
- **SC-004**: Repeating the landing view for the same period returns identical figures on every
  run.
- **SC-005**: An analyst reaches the full origin breakdown for any line in one interaction.
- **SC-006**: A full analysis completes and produces a ranked recommendation in under 15 minutes.
- **SC-007**: In an analysis of a concentrated line, at least one recommended origin is not among
  the current leading origins, and the reason for widening is stated.
- **SC-008**: 100% of modelled figures in any output carry a modelled label at the point of use.
- **SC-009**: Every conclusion states the reference period of its underlying data.
- **SC-010**: A follow-up question about displayed figures is answered in under 60 seconds and at
  under one twentieth the cost of a full analysis.
- **SC-011**: Every retrieval outcome is classified as succeeded, empty or failed, with zero
  cases of an empty result being reported as a failure.
- **SC-012**: Malformed input produces a named reason in 100% of cases and a stack trace in none.
- **SC-013**: With no network access, the system produces figures identical to a live run for
  every request it has a recording of, and an explicit refusal for every request it does not.
- **SC-014**: A failure of a non-essential input still yields a usable recommendation, with the
  degradation stated, in 100% of cases.
- **SC-015**: Every severity level is distinguishable without colour.
- **SC-016**: The capability layer starts, lists its capabilities and reports their contracts
  with no analysis layer present.
- **SC-017**: The system runs end to end with no data-source credential of any kind.

## Assumptions

- **The analyst is a domain professional, not a data analyst.** They read shares, ranks and
  named risk conditions fluently; they should not have to interpret a raw concentration index
  unaided, which is why the effective number of sources is shown alongside it.
- **Screening, not procurement.** The output narrows a list of origins worth investigating. It
  does not price a shipment, verify a supplier exists, or replace a tender. Nothing here needs to
  be contract-grade.
- **Macro-level open data only.** No internal company data of any kind is used, which is what
  makes the tool shareable. This is a hard boundary, not a v1 limitation.
- **Annual statistics lag by roughly two years.** The most recent complete reporting year is
  assumed to be about two years back, resolved from observed source behaviour rather than
  assumed, which is why an independent current-period check exists at all.
- **A fixed set of tracked lines is acceptable for this version.** Lines are chosen for having
  enough real import volume to be worth screening; adding one is a change to the system, not a
  runtime action.
- **Freight rates are not publicly available.** Any delivered-cost comparison must therefore
  contain a modelled component, so the requirement is that it be labelled rather than avoided.
- **Only most-favoured-nation duty rates are publicly retrievable.** Preferential rates under
  trade agreements can be flagged as possible but not applied.
- **Logistics quality is a structural, slow-moving factor**, and a periodic published index is an
  acceptable proxy even when its latest observation is several years old.
- **Single analyst, single session.** No multi-user access control, sharing or collaboration is
  in scope.
- **Some public sources block automated access.** At least one current-period source is expected
  to refuse a program while serving a person, so ordered fallbacks and naming the source actually
  read are requirements rather than defensive extras.
