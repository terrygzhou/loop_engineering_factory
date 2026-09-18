# node-module-seams

## Purpose
The seam rule that keeps `graph/nodes/*` node files thin and each
concerned helper individually testable, so a phase node can be tested in
isolation without importing LLM, network, or HIL surfaces.

## ADDED Requirements

### Requirement: Seam rule for node modules
The node files in `graph/nodes/` SHALL be split such that a function
resides in a sibling module (same directory, `graph/nodes/<name>_*.py`)
when it satisfies ALL four of the following; otherwise it SHALL remain in
the node file:

1. No `interrupt()`, no `invoke_skill`/`invoke_skill_async`, no `httpx`,
   no network/subprocess-LLM in the body (deterministic filesystem
   reads/writes are allowed).
2. No `asyncio.gather` over LLM calls.
3. No audit-log / stream-writer emission that the node file does not
   itself own.
4. Stateless signature — no module-level mutable state, no config read
   at call time that the caller does not already perform.

The node file SHALL retain: the public `*_node` entry point, all HIL
`interrupt()` call sites, LLM orchestration (including Decision-3
None-coercion), audit/writer emissions, and the partial-update delta
construction (`increment_loop` contract).

#### Scenario: Pure helper is in a sibling module
- **WHEN** `graph/nodes/openhands_build.py` exposes
  `_parse_build_report`
- **THEN** the implementation lives in `graph/nodes/openhands_report.py`
  and `openhands_build.py` imports it; the name `BuildReportMissingError`
  remains importable from both modules.

#### Scenario: Node file has no pure helpers
- **WHEN** a function in a node file calls `interrupt()` or
  `invoke_skill` directly
- **THEN** that function stays in the node file and is not split out

### Requirement: Import surface stability
The public import surface of each node module SHALL be unchanged after a
split: `graph.main`, `graph.runner`, and every test continue to import
`discover_node`, `define_node`, `plan_node`, `review_node`,
`openhands_build_proxy_factory`, `seed_data_node`, `verify_node`,
`ship_node`, and `reflect_node` from their current modules. Sibling
modules SHALL only be imported by their owning node file (or by tests
that target the moved helper directly).

#### Scenario: Graph wiring is untouched
- **WHEN** `graph/main.py` is diffed after the split
- **THEN** its imports of node entry points are byte-identical to the
  pre-split state.

#### Scenario: Private helper is re-pointed
- **WHEN** a test previously imported `_extract_use_cases` from
  `graph.nodes.plan`
- **THEN** after the split the same import path still resolves (re-export
  in `plan.py`) or the test imports it from `graph.nodes.plan_diagrams`;
  in either case the test body is unchanged.

### Requirement: No behavior change
A split SHALL NOT change any node's observable behavior: returned
partial-update deltas, state keys written, interrupt payloads, LLM
prompt text (byte-identical — pinned by `tests/test_discover_docs_prefill.py`
and the prompt-snapshot tests), exception types, and side effects
(filesystem writes, audit events, stream events).

#### Scenario: Prefill payload unchanged
- **WHEN** the DISCOVER doc-prefill helper is moved to
  `discover_prefill.py`
- **THEN** `tests/test_discover_docs_prefill.py` passes without body
  edits and the interrupt payload for "no docs" remains byte-identical to
  the pre-prefill behavior.

#### Scenario: LLM-fatal degradation unchanged
- **WHEN** a moved helper previously coerced an LLM-None to `""` with a
  warning event (Decision 3 active-path contract)
- **THEN** after the move the coercion and warning event are emitted at
  the same point (the caller, not the helper) and
  `tests/test_llm_failure_robustness.py` passes unchanged.

### Requirement: Individual testability
Each sibling module SHALL be importable and testable in isolation with
monkeypatching limited to its own inputs (filesystem paths, in-memory
dicts); no LLM, network, or checkpointer monkeypatching SHALL be
required to unit-test a sibling module's pure helpers.

#### Scenario: Seam test imports only the sibling
- **WHEN** a new test in `tests/test_node_seams.py` unit-tests
  `_parse_build_report`
- **THEN** it imports only `graph.nodes.openhands_report` (plus
  standard-library fixtures) and asserts schema validation and the
  `BuildReportMissingError` raise with no monkeypatching of
  `tools.llm`, `httpx`, or `graph.checkpointer`.
