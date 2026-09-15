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
