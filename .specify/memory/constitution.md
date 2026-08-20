# Import Sourcing Advisor Constitution

This project gives procurement decisions to a person who will act on them. Every principle below
exists to keep a number the analyst trusts from being a number the system invented.

## Core Principles

### I. Open data only (NON-NEGOTIABLE)

Every input is publicly available and requires no credential. No internal company data enters
this system at any point — not in code, not in fixtures, not in a prompt, not in an example.

This is a hard boundary rather than a v1 limitation. It is what makes the tool shareable at all,
and it is the reason the tool is macro-level: the moment a decision needs proprietary volumes or
contracted prices, it belongs in a different system.

*Enforced by*: no credential of any kind for any data source; a secret scan over every tracked
file before publication.

### II. Measured and modelled are never confused

Any figure the system did not observe is labelled at the point where it is displayed, not in a
footnote and not only in logs. Freight is modelled. A duty rate is the generally applicable rate,
not necessarily the rate paid. A value per unit derived from value over quantity is a statistical
derivation, not a market price.

A confidence level is never "high" for an output containing a modelled component.

*Enforced by*: every cost component carries a measured/estimated marker; unit values carry their
disclaimer inline; the ranking discloses each factor's contribution so a reader can see what a
modelled input did to a score.

### III. Absent is not zero, and empty is not an error

Every retrieval has exactly three outcomes: it succeeded, it is genuinely empty, or it failed.
These are distinct and are never collapsed.

A source with no record for a period is answering, not failing — such a result is not retried and
not reported as an error. Conversely, a value that could not be obtained is never rendered in a
way that reads as a low value: a missing concentration figure is marked missing, not shown blank
next to lines whose figures are real, and a missing tariff is never substituted with zero without
saying so.

*Enforced by*: a three-state status on every tool result; portfolio rows marked incomplete rather
than blank; a recording gap raising explicitly rather than defaulting.

### IV. The capability boundary is the whole capability surface

The agent has no built-in tools — no shell, no filesystem, no general web access. Its entire
ability to affect or observe anything arrives through declared capability providers with declared
contracts. Local developer configuration is prevented from injecting itself into a session, so a
run is reproducible on another machine.

Every capability declares both its input and its output contract. A capability that only declares
inputs is incomplete.

*Enforced by*: an empty built-in tool set, an explicit allow-list, no inherited settings or
plugins, and a declared output schema on every published tool.

### V. Verified, not asserted (NON-NEGOTIABLE)

No claim that something works is made without a run that shows it. A verification that cannot
fail is not a verification.

This principle exists because of a specific incident: a run of this system once produced a
fluent, well-reasoned answer explaining that its own tools were unavailable, while every step in
its trace appeared to succeed. Two silent failures had compounded into a plausible output. A
check that asserted only "the run finished" passed it.

Every end-to-end check therefore asserts on substance: that both providers actually attached,
that every expected capability was actually called, and that failures were actually captured.

*Enforced by*: an end-to-end script that fails a run unless both providers attached and all five
capabilities were invoked; unit tests over the domain arithmetic; a browser-rendered check of the
interface rather than an HTTP status.

## Additional Constraints

**Offline parity.** The system must run with no network access from recorded source responses,
and must produce figures identical to a live run. Substitution happens at the transport boundary
only: every parser, deduplication step and calculation above it runs unchanged. No code path
returns a prepared answer. A request with no recording is refused, never defaulted.

**Determinism where a model is not needed.** Anything that can be computed is computed. A model
is used for judgement, sequencing and explanation — not for arithmetic, and not for the first
screen a user sees.

**Cost proportional to the question.** A long multi-step analysis and a question about a number
already on screen do not deserve the same resources. Interpretation of displayed figures must not
recompute what produced them.

**Legibility without colour.** Severity is conveyed by more than colour. Any ranking must survive
greyscale reproduction and colour-vision deficiency.

**Screening, not procurement.** Output narrows a list of origins worth investigating. It does not
price a shipment, verify that a capable supplier exists, or replace a tender. Every conclusion
states the reference period of its data and what would change it.

## Development Workflow

**Failures are documented, not buried.** A defect found in this project's own behaviour is written
up with its mechanism and its lesson, because the mechanism generalises and the fix does not. Two
such write-ups already exist in the design rationale.

**Limitations are stated up front.** Known limitations appear at the top level of the README and
the rationale, not discovered by a reader. A limitation that was designed around and a limitation
that was found by accident are both disclosed, and which is which is stated.

**Commits explain the why.** A commit message records what was wrong and how it was verified, not
only what changed.

## Governance

This constitution supersedes convenience. Where a principle and a deadline conflict, the
principle holds and the scope shrinks — an output that is smaller is recoverable, an output that
is quietly wrong is not.

Principles I and V are non-negotiable and cannot be waived. The remaining principles may be
departed from only with the deviation stated in the affected artefact, in the same place a reader
would look for the claim it qualifies.

Amendments require a version bump, the reason recorded here, and a pass over existing artefacts
for statements the amendment falsifies.

**Version**: 1.0.0 | **Ratified**: 2026-08-20 | **Last Amended**: 2026-08-20
