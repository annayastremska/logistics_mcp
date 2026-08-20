# Specification Quality Checklist: Import Sourcing Advisor

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-08-20
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [~] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [~] No implementation details leak into specification

## Validation Detail

Counted: 29 functional requirements, 17 success criteria, 4 prioritised user stories,
10 edge cases, 0 unresolved clarification markers.

**Implementation-detail scan.** A case-insensitive sweep for stack terms (server transport,
named data providers, named model vendor, web framework, language, classification-system
identifiers, index abbreviations) returns exactly one hit in the document body: the `Input`
field on line 9, which the template exists to preserve verbatim. Every other hit was a
substring false positive. The body uses "capability layer" and "capability provider" in place
of the concrete server and protocol names throughout.

**Ambiguity check on the requirements that most invite it.** Each of the following was
rewritten until a tester could fail it: FR-005 (absent versus low risk — testable by
withholding the risk retrieval and asserting the line is marked incomplete rather than blank),
FR-012 (the concentration finding must change the candidate set — testable by asserting at
least one recommended origin is outside the current leaders, which SC-007 restates as a
measurable), FR-022 (no modelled figure presented as observed — testable by asserting every
modelled component carries a label, which SC-008 restates as 100%), FR-024 (offline figures
must equal live figures — testable by comparing the two runs numerically).

## Two accepted deviations

Both are marked `[~]` above rather than passed, because they are real deviations rather than
judgement calls, and a later reader should see them stated:

1. **FR-027, FR-028 and SC-016 constrain architecture, not only outcomes.** They require the
   capability layer to start and be inspectable independently of the analysis layer, and require
   connected providers to be reported as observed rather than as configured. That is an
   architectural constraint in a document that should describe outcomes. It is kept deliberately:
   these are externally imposed requirements on this project, not internal design preferences, so
   omitting them from the specification would misrepresent the actual scope. They are phrased in
   role terms ("capability layer", "provider") rather than naming any protocol or product.

2. **SC-010 references relative cost.** "Under one twentieth the cost of a full analysis" is an
   operating-cost ratio, which is a business measure, but it only exists because the
   implementation has two cost tiers. It is retained because per-question cost is genuinely a
   user-facing constraint on how freely the analyst can ask questions.

## Notes

- No spec updates are outstanding. The specification passed content and completeness review on
  the first iteration; the two `[~]` items are documented deviations, not defects to fix.
- One point of order for the reader: this specification was written **after** the system was
  built, to close a gap in process artefacts. It therefore describes a system that already
  exists. Requirements were derived from the original assignment and the delivered behaviour
  rather than the reverse, and `/speckit-converge` is the correct next step to check the two
  against each other rather than assuming they agree.
