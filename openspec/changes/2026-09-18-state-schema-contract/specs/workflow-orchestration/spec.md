# workflow-orchestration (delta)

## MODIFIED Requirements

### Requirement: Phase pipeline
`WorkflowState` SHALL be the single source of truth for the state
schema. Every top-level key SHALL be either (a) returned by some active
phase node (DISCOVER/DEFINE/PLAN/ARCH_REVIEW/BUILD/SEED_DATA/VERIFY/
SHIP/REFLECT) or the shared runner, or (b) on the explicit
`graph/state.py:INPUT_ONLY_KEYS` allowlist (keys seeded by the runner
or Web bridge and read by nodes but never returned). No other
top-level key SHALL exist in the schema. Dead top-level keys (values
that live under `artifacts.*`) are removed from the schema; their
initial seeding is removed from the runner and the Web bridge.

The dead-key list this change removes (subject to the AST audit in
task 2.1 confirming each is never returned by an active node):
`tasks`, `tasks_text`, `backlog`, `solution_md`, `plan`, `status`,
`retry_count`, `spec_text`, `spec_refined`, `project_context`,
`interview_notes`, `diagrams`, `diagram_pngs`, `feedback_context`,
`human_approval_required`.

#### Scenario: A new top-level key is introduced
- **WHEN** a future node returns a top-level key that is in neither the
  node-return set nor `INPUT_ONLY_KEYS`
- **THEN** `tests/test_state_contract.py` fails, forcing an explicit
  schema update (no silent drift)

### Requirement: Gate signal parsed once
`route_phase` SHALL NOT parse `artifacts.test_results` JSON inline. The
parse SHALL live in `tools/acceptance.py:count_pytest_fail(artifacts)
-> int` (returns 0 on absent/invalid/missing-field input), and the
VERIFY branch calls it. Behavior is identical to the inline
try/except it replaces (absent → 0, invalid JSON → 0).

#### Scenario: VERIFY routing unchanged
- **WHEN** the VERIFY gate runs with a valid `test_results` JSON
  (`pytest_fail` set), with it absent, or with invalid JSON
- **THEN** routing matches the pre-change behavior exactly
  (pass → SHIP; fail → BUILD / ERROR per Decision 2; absent/invalid
  JSON counts as 0 errors)
