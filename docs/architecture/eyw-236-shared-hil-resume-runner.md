# EYW-236 — Shared HIL/resume runner (Refactor C)

**Status:** complete — commit `da62642` (pushed to `main`), 2026-08-24
**Source:** EYW-232 — LangGraph Server evaluation, Refactor C of 4 (see `eyw-232-langgraph-server-evaluation.md`)

## What changed

The stream→interrupt→resume cycle previously existed twice — once in
`WorkflowRunner._astream_with_hil` (CLI, `graph/executor.py`) and once in
`WorkflowBridge.run_real` (Web, `frontend/backend/workflow_bridge.py`) —
each re-implementing LangGraph's resume quirks:

- `__interrupt__` detection in values chunks (LangGraph 1.x: `interrupt()`
  yields into the stream instead of raising `GraphInterrupt`),
- suspended-vs-complete discrimination,
- phase / HIL-type resolution from node name,
- DISCOVER (4-field dict), ARCH_REVIEW (approval) and generic (y/n) resume
  payload rules,
- `Command(resume=..., update=...)` re-entry and the stale-node re-stream
  quirk,
- auto-approve handling per HIL type.

**Now:** one shared async generator, `graph/runner.py::run_workflow`, owns
the entire cycle. Adapters are thin and only supply:

| Adapter | File | Input handler | Event sink |
|---|---|---|---|
| CLI | `graph/executor.py` `WorkflowRunner._astream_with_hil` | auto-approve + interactive prompt | `_CliEvents` (OTEL, phase transitions, artifact dedup, log) |
| Web | `frontend/backend/workflow_bridge.py` `run_real` | `_handle_hil` (WS form broadcast + poll) | `_BridgeEvents` (WS events, OTEL, artifact dedup) |

The legacy helpers `WorkflowBridge._parse_formatted_input` /
`_build_resume_data` are removed; their logic lives in
`graph/runner.py::parse_formatted_input` / `build_resume_payload`
(shared rules, DISCOVER setup fallbacks applied by the bridge's
`_hil_input` closure via `_project_name` / `_project_description` /
`_context_folder`).

## Contracts preserved (bit-for-bit behavior)

- **First values chunk** is the input-echo state; both adapters see it.
- **Bridge pre-seeding** — `_build_executor_state` sets
  `discover_setup_done=True`, `auto_approve_override=False`,
  `force_hil=True`; the runner's `update_data` pre-seeding
  (`discover_setup_done`, `discover_interview_done`) composes with it.
- **OTEL `hil.pause`** is emitted in both `_BridgeEvents.on_interrupt`
  and `_handle_hil` (duplicate, matching pre-refactor behavior).
- **Error path** — bridge/CLI `on_error` re-raises so the outer
  `except Exception` handler in `run_real` / `_astream_with_hil` runs
  legacy side effects exactly once (status=error, SYSTEM error event, OTEL).
- **Abort** — `abort_check` at loop top + after handler; task
  cancellation (CancelledError) handles mid-stream aborts as before.

## Verification

- `tests/test_runner_hil_loop.py` — 3 contract tests against a real
  compiled LangGraph state graph (`MemorySaver`, nodes named to match
  `_NODE_PHASE_MAP`): interrupt/resume cycle, abort gate, error
  propagation.
- Full suite: **273 passed** (`.venv/bin/python3 -m pytest tests/`),
  excluding pre-broken `tests/test_services.py`.
- Live smoke (`PAPERCLIP_SCRATCH_DIR/eyw236_smoke.py`, run-scoped):
  drove both adapters through the shared runner with a fake compiled
  graph — CLI auto-approve HIL cycle (4 chunks, final phase PLAN) and
  Web form-broadcast + poll + resume + completion (13 events, status
  complete).

## Notes

### Resume-Command drop bug (found & fixed post-unification)

The shared loop initially **never resumed on LangGraph 1.x**: after an
`__interrupt__` values chunk the async-for simply ended, control fell
through to the stale-node check (`graph_state.next` is non-empty for a
suspended task), and the loop re-streamed `input=None` instead of the
pending `Command(resume=..., update=...)` — an infinite HIL loop
(reproduced empirically: input handler re-invoked on the same gate
forever). The pre-refactor CLI/Web loops had the same latent defect —
the unification had no E2E coverage, which is how it shipped.

Fix: a `resumed` flag is set in both interrupt branches (values
`__interrupt__` and legacy raise path); when set, the stale-node check
is skipped and the pending resume Command is re-streamed on its own
iteration (`graph/runner.py`, L~394/445/482/492). Regression-pinned by
`tests/test_runner_hil_loop.py::test_interrupt_resume_cycle` and
`tests/test_runner.py::TestRunWorkflowLoop::test_resume_value_reaches_rerun_node`.

Side observation (pre-existing, documented in tests): re-streaming with
`input=None` echoes the last persisted state snapshot as the first
values chunk of that iteration — both old loops observed this; the
runner tests pin it.

### LangGraph 1.x `interrupt()` semantics

- no `GraphInterrupt` raise;
- resume value is returned on node re-run via
  `Command(resume=[...], update=...)` — **list-wrapped**; nodes unwrap
  per the existing `graph/nodes/review.py` pattern.
- pi-lens (system Python, no `langgraph`) flags on this diff are
  environmental false positives; the venv suite is the authoritative
  check.
