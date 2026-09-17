# Spec Delta: workflow-orchestration

## MODIFIED: PLAN consumes `arckit_product_backlog` as advisory context

When `artifacts["arckit_product_backlog"]` is set and non-empty, the PLAN
node's task-breakdown LLM call MUST include an advisory block carrying the
backlog JSON, capped by `bounds.context.arckit_advisory_max_chars` (4000).
The block is advisory — it constrains task ordering but does not change the
plan's schema or the phase's routing.

### Scenarios

**Backlog present**
- `artifacts["arckit_product_backlog"]` = valid JSON string → the
  `planning-and-task-breakdown` prompt context contains a
  `## PRODUCT BACKLOG` header + the (possibly capped) JSON.

**Backlog absent**
- `artifacts["arckit_product_backlog"]` missing or empty → the prompt
  context is byte-identical to the pre-change behavior (spec + interview +
  rejection feedback only). No header, no placeholder.

## ADDED: SEED_DATA consumes `arckit_data_model` as advisory context

When `artifacts["arckit_data_model"]` is set and non-empty, the SEED_DATA
seed-script LLM call MUST include an advisory block carrying the DATA model
JSON. When absent, the seed prompt is byte-identical to the pre-change
behavior.

### Scenarios

**DATA model present**
- `artifacts["arckit_data_model"]` = JSON string with entities → seed
  prompt context contains an `ArcKit DATA model` advisory header + JSON.

**DATA model absent**
- key missing or empty → seed prompt context is byte-identical to today's
  (`spec_text + data_models + api_specs`).

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
