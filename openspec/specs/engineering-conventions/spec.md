# engineering-conventions

## Purpose
Cross-cutting code-style and testing rules that keep the pipeline
deterministic, auditable, and testable without live services.

## Requirements

### Requirement: Node update discipline
Nodes SHALL return partial-update dicts that the LangGraph reducer merges;
the only permitted in-place state mutation is the loop-counters pattern
(increment then replace the whole state["artifacts"]["loop_counts"] dict).

#### Scenario: Loop counter increment
- **WHEN** a node retries a phase
- **THEN** it increments the counter and returns the replaced artifacts dict,
  never a top-level mutation

### Requirement: Logging and streaming
Production paths SHALL log through module-scoped loggers (no print() outside
main.py CLI) and user-facing progress SHALL go through
tools/stream_writer.safe_stream_writer; every node SHALL emit
AuditLog.log_node_input / log_node_output.

#### Scenario: Progress outside a runnable
- **WHEN** safe_stream_writer is called where no stream consumer exists
- **THEN** the writer is a no-op and the call is safe

### Requirement: LLM routing and prompt capping
All LLM traffic SHALL route through tools/llm.py (never direct ChatOpenAI
in nodes); prompts SHALL be built from tools/distiller.distill_skill output
and capped by config/bounds.yaml limits via
tools/context_manager.prepare_context_for_llm.

#### Scenario: Skill prompt
- **WHEN** a node invokes a skill
- **THEN** the prompt is the distilled SKILL.md content trimmed to the
  bounds.yaml token/char limits

### Requirement: State hygiene
State SHALL use typed error: Optional[str] plus LLMError (tools/llm.py);
untyped sentinel strings (e.g. "__ERROR__") SHALL NOT be placed in state.

#### Scenario: Fatal LLM error
- **WHEN** an LLM call fails fatally
- **THEN** error carries a typed message and invoke_skill returned None —
  no magic sentinel string

### Requirement: Test independence
The test suite (.venv/bin/python3 -m pytest tests/ -q, 312 tests) SHALL pass
with LLM_BASE_URL unset (invoke_skill → None), and without a live OpenHands
server or ChromaDB; a failing test SHALL always be a state-invariant failure,
never an LLM-content assertion.

#### Scenario: CI with no services
- **WHEN** pytest runs with no external services configured
- **THEN** all tests pass and invoke_skill-dependent paths hit the None /
  dry-run branches

### Requirement: Branch test coverage
Every state-machine branch — including `loop_count >= max_loops` livelock
paths and the ERROR halts — SHALL have a dedicated test; test layout is flat
under tests/ with conftest at tests/conftest.py.

#### Scenario: Livelock branch
- **WHEN** the suite is inspected
- **THEN** each route_phase branch (VERIFY loop/halt, BUILD budget, generic
  livelock guard) has a named test (tests/test_edges.py,
  tests/test_w2_wayforward.py)

### Requirement: HIL pause placement
A node that has already resumed in a step SHALL NOT add a new interrupt
(LangGraph 1.x suppresses it); multiple HIL pauses SHALL be merged into one
node (as DISCOVER's setup + interview are).

#### Scenario: Second pause suppressed
- **WHEN** a second interrupt() is hit in a step that already resumed
- **THEN** LangGraph 1.x suppresses it, which is why pauses are merged per
  node
