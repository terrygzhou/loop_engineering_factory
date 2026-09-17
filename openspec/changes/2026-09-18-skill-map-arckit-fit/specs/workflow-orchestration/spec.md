# Spec Delta: workflow-orchestration

## ADDED: ArcKit advisory block consolidated into `tools/arckit_context.py`

A new shared helper `tools/arckit_context.py::arckit_advisory_block(
artifacts: dict, max_chars: int = 4000) -> str` MUST provide a single
entry point for building the consolidated ArcKit advisory block from the
state's `artifacts` dict.

Keys it checks (in order): `arckit_product_backlog`,
`arckit_strategy_waves`, `arckit_integration_standards`,
`arckit_nfr_constraints`, `arckit_security_controls`,
`arckit_data_model`.

For each key present and non-empty, the block includes one
`## <KEY_NAME>` section with the JSON value. Total output is capped at
`max_chars`.

When no advisory keys are set, the helper returns `""` — callers that
append the result to `context_parts` produce a byte-identical prompt to
the pre-change behavior.

### Scenarios

**No ArcKit advisory keys**
- `artifacts = {}` → `arckit_advisory_block(artifacts)` returns `""`.

**Backlog set**
- `artifacts["arckit_product_backlog"]` = valid JSON string → the
  returned block contains `## arckit_product_backlog` + JSON.

**Multiple keys set**
- Two or more advisory keys present → block contains one section per
  key, in the fixed key order, total output ≤ `max_chars`.

**Larger than cap**
- A single key's JSON exceeds `max_chars` → output is truncated to
  `max_chars`.

## MODIFIED: PLAN consumes ArcKit advisory block via shared helper

The PLAN node's `context_parts` construction MUST call
`arckit_advisory_block(state.get("artifacts", {}))` and append the result
to `context_parts` when non-empty. When no ArcKit advisory keys are set,
the prompt context is byte-identical to the pre-change behavior
(spec + interview + rejection feedback only).

### Scenarios

**Backlog present**
- `artifacts["arckit_product_backlog"]` = valid JSON string → the
  `planning-and-task-breakdown` prompt context contains an
  `## arckit_product_backlog` advisory header + JSON.

**Backlog absent**
- No ArcKit advisory keys set → prompt context is byte-identical to
  pre-change behavior. No header, no placeholder.

## MODIFIED: `define.py::_arckit_advisory_context` delegates to shared helper

`graph/nodes/define.py` MUST replace its inline `_arckit_advisory_context`
logic with a call to `arckit_advisory_block`. The DEFINE node's prompt
context for `arckit_nfr_constraints` + `arckit_integration_standards`
remains byte-identical when those keys are absent.

### Scenarios

**NFR constraints absent**
- No `arckit_nfr_constraints` / `arckit_integration_standards` in
  `artifacts` → DEFINE prompt context unchanged.

**NFR constraints present**
- Keys set → DEFINE prompt context includes the consolidated advisory
  block (same as pre-refactor, but now via the shared helper).

## ADDED: Dead `spec_text` parameter removed from `build_executor_state`

`graph/executor.py::build_executor_state` MUST NOT have a `spec_text`
parameter. The parameter was dead after P0-A1 removed `spec_text` from
`WorkflowState`; nodes read `artifacts["spec_refined"]` instead.
`run_interactive` MUST NOT pass `spec_text` to `build_executor_state`.

### Scenarios

**Call `build_executor_state` without `spec_text`**
- `build_executor_state(cycle_id="1", project_name="x")` → works
  without error; `WorkflowState` is constructed correctly.

**Signature inspection**
- `inspect.signature(build_executor_state).parameters` does not contain
  `"spec_text"`.

## Non-goals (inherited)

- No new top-level `artifacts` key is read from a different node than the
  one that writes it: `arckit_product_backlog` is written by DISCOVER,
  read by PLAN (same-node-ownership rule preserved — PLAN is a distinct
  node but the key already flows through state, which is the sanctioned
  cross-node mechanism; this adds a *prompt* consumption, not a state
  read from a node that doesn't own it).
- No routing / Decision-2 / loop-budget change.
- `arckit_strategy_waves`, `arckit_open_questions`, `oaal_sprint_map`, and
  the four W3 build-context keys keep their existing consumers unchanged.
- SEED_DATA already consumes `arckit_data_model` deterministically in the
  active seed node; no change needed to the seed path.
