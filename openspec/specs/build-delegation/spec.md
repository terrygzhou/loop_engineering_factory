# build-delegation

## Purpose
Delegates the BUILD phase to a remote OpenHands agent-server and contracts the
result as a machine-readable manifest.

## Requirements

### Requirement: OpenHands delegation
BUILD SHALL delegate to OpenHands agent-server via the Gateway conversations
API; the agent image SHALL be pinned to 1.30.0
(ghcr.io/openhands/agent-server:1.30.0-python) because the build-report
contract depends on agent behaviour.

#### Scenario: Gateway unavailable
- **WHEN** the OpenHands gateway is unreachable, the conversation times out,
  or returns an empty response
- **THEN** BUILD falls back to the local LangGraph BUILD subgraph
  (_run_local_subgraph)

### Requirement: build_report.json manifest
The OpenHands agent SHALL write build_report.json
({status: pass|fail|partial, test_results, files, errors}) to the project
root; _parse_build_report SHALL validate it. A missing or invalid manifest
SHALL be a hard failure (BuildReportMissingError) — the system SHALL NOT
downgrade to free-text parsing.

#### Scenario: Missing manifest
- **WHEN** the agent completes without a valid build_report.json
- **THEN** BuildReportMissingError is raised and BUILD is treated as failed

#### Scenario: Path traversal rejected
- **WHEN** a manifest entry has a rel_path that is absolute or contains ..
- **THEN** the entry is rejected

### Requirement: BUILD retry budget
BUILD retries SHALL be counted in artifacts.loop_counts["BUILD"] (max 2).
When the budget is exhausted, next_phase SHALL be set to None and routing SHALL
go to ERROR.

#### Scenario: BUILD retries exhausted
- **WHEN** BUILD fails with loop_counts["BUILD"] already at 2
- **THEN** the workflow routes to ERROR and never re-enters BUILD

### Requirement: BUILD prompt advisory context
The OpenHands build prompt SHALL include, as advisory (non-routing) sections,
exactly those of the following keys that are set in `artifacts`:
`arch_review_answers`, `arckit_product_backlog`,
`arckit_strategy_waves`, `arckit_data_model`,
`arckit_integration_standards`, `arckit_security_controls`,
`arckit_nfr_constraints`. Unset keys SHALL contribute no section: when
none of the keys is set the prompt SHALL be byte-identical to the prompt of a
run with no ArcKit context. Advisory sections SHALL NOT alter the
build_report.json manifest contract (Decision 1) or the BUILD retry budget.

#### Scenario: ArcKit context present
- **WHEN** BUILD runs with `arckit_data_model`,
  `arckit_integration_standards`, and `arch_review_answers` set
- **THEN** the build prompt contains three advisory sections with that
  content and the manifest contract is unchanged

#### Scenario: No ArcKit context
- **WHEN** no ArcKit-related key is set
- **THEN** the prompt is identical to the pre-change prompt (no empty
  sections, no sentinel markers)

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
