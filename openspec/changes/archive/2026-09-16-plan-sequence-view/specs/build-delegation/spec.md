# build-delegation (delta)

## ADDED Requirements

### Requirement: BUILD prompt diagram context
The OpenHands build prompt SHALL include the contents of
`artifacts.diagrams` — the four base views and any `sequence_*` use-case
views — as advisory diagram context, emitted only for keys that are present.
When no diagrams are present the prompt SHALL be identical to the pre-change
prompt. Diagram content SHALL NOT alter the build_report.json manifest
contract (Decision 1).

#### Scenario: Sequence views present
- **WHEN** BUILD runs with `diagrams` containing two `sequence_*` views
- **THEN** the build prompt's diagram section includes both views
