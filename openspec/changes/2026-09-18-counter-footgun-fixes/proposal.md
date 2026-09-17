# Change: fix DEFINE loop-counter livelock & repo footguns

## Why

`findings.md` §E (whole-codebase pass, 2026-09-18) found one true bug and
four footguns:

- **E1 (bug — livelock):** `graph/nodes/define.py` increments the DEFINE loop
  counter via `graph/edges.py:_maybe_increment_loop`, which mutates
  `state["artifacts"]["loop_counts"]` **in place** and never returns the new
  value in the node's update dict. LangGraph's `_dict_merge` reducer only sees
  returned values, so the counter is never persisted. `route_phase`'s
  `loop_count >= 2 → PLAN` forward guard (`graph/edges.py:91-94`) therefore
  never fires: a project whose spec confidence is chronically below the 0.9
  threshold loops DEFINE→DEFINE without bound. `verify.py`, `review.py`, and
  `openhands_build.py` already do this right (fresh `loop_counts` dict in the
  node return; `verify.py:428-431` even documents why the old in-place
  pattern was removed).
- **E2 (footgun):** `config.Config.reload()` re-reads the YAML into the module
  dict but every `Config` attribute was resolved at import time into class
  attributes — nothing re-resolves, so the method silently no-ops. No active
  caller today; it misleads readers into thinking hot-reload works.
- **E4 (footgun):** `frontend/backend/abort_manager.py` caches a single
  `asyncio.Event`-backed singleton. The event is bound to the first event
  loop that runs it; tests or second workflows on a different loop inherit a
  stale event (`is_aborted` / `wait` silently report the wrong state). Two
  concurrent workflows also share one abort flag.
- **E5 (footgun / prompt-injection-shaped):** `feedback/diff_engine.py`
  `apply_prompt_diff` splices the LLM's free-text `change` description
  verbatim into `config/prompt_templates.py` source
  (`new_template = f'{template_name} = """{change_desc}"""'`), and the
  locating regex `[^\"]*` cannot match template bodies containing `"` — so
  it fails on most real templates, and when it does match the replacement is
  unescaped LLM text written straight into a `.py` file. The auto-approve
  path applies it without diff review (Decision 4 targets structured diffs;
  the W3 shape `{section,key,op,value}` already exists for config diffs in
  this module).
- **E12 (footgun):** `discover_hil_count` is dual-written: `graph/runner.py`
  pre-seeds it via checkpoint `update_data` on every DISCOVER resume AND
  `graph/executor.py` writes it on the auto-approve interview path; the
  readers dispatch on the value persisted in `artifacts`. The two write
  paths can disagree, and the "unknown DISCOVER type → fall back on hil
  count" legacy branch is the only consumer of the persisted value — dead in
  the active Web path where `hil_type` is always known.

## What changes

- **E1 (the bug):** `define_node` builds a fresh `loop_counts` dict on low
  confidence and returns it inside its `artifacts` delta, matching the
  `verify.py` / `openhands_build.py` pattern. `_maybe_increment_loop` is
  deleted (last call site; the helper is broken-by-construction);
  `graph/edges.py` keeps `_get_loop_count` (the read-only counter reader)
  and gains a pure `increment_loop(artifacts, phase) -> (dict, bool)`
  helper that nodes use — no in-place mutation anywhere.
  Regression test: a low-confidence DEFINE run persists
  `artifacts.loop_counts["DEFINE"]` (mirror of the BUILD counter tests in
  `tests/test_w2_wayforward.py`).
- **E2:** delete `Config.reload()` — no callers exist (grep-verified);
  replacing it with a docstring-only note in `config/loader.py`
  ("config values are resolved at import time; restart the process to pick
  up env/yaml changes") so readers aren't misled.
- **E4:** `AbortManager` keeps one `asyncio.Event` per running-loop +
  workflow-id key: `get(workflow_id=None)` returns a per-(loop, workflow)
  manager; the module keeps `get()` for single-workflow callers and the Web
  bridge passes its workflow id. A plain-module `is_aborted` check from a
  non-owning loop returns False instead of stale state.
- **E5:** `apply_prompt_diff` switches to the structured-diff contract:
  callers pass `{"section": <template_name>, "key": "template_body",
  "op": "replace", "value": <new text>}` (same shape REFLECT already emits
  for config diffs); the body is written through
  `ast.literal_eval`-safe escaping (the value is repr-wrapped as a
  module-level string constant), the locating regex is made quote-aware
  (matches triple-quoted bodies containing `"`), and the write is
  validated by compiling the resulting file (`compile()`) before it lands
  on disk — a failing compile leaves the original file untouched.
- **E12:** `discover_hil_count` ownership moves to the DISCOVER node: the
  node writes the counter into its returned `artifacts` delta; the
  runner-side `update_data` pre-seed increment and the legacy
  "unknown type → dispatch on hil count" fallback branch are deleted;
  the executor auto-approve interview dict stops writing it.

## Non-goals

- No routing change: `route_phase` semantics, `_forward_paths`, and the
  VERIFY gate (Decision 2) are untouched except that DEFINE's counter
  finally works.
- No new `artifacts.*` top-level keys read back from a different node
  (SPEC §7 ask-first rule) — `loop_counts`, `discover_hil_count`, and the
  prompt-diff shape are existing keys/contracts.
- No P0/P1/P2 work from `findings.md` (state schema contract, typed
  artifacts, skill dedupe) — separate change `2026-09-18-state-schema-contract`
  covers P0; P1/P2 are not converted.
- No change to the OpenHands API surface, build_report.json schema,
  ChromaDB collection names, or compose ports.

## Impact

- Code: `graph/nodes/define.py`, `graph/edges.py` (helper delete + add),
  `config/loader.py`, `frontend/backend/abort_manager.py`
  (+ `workflow_bridge.py` if it calls `get()` without a workflow id),
  `feedback/diff_engine.py` (+ REFLECT call site), `graph/runner.py`,
  `graph/executor.py`, `graph/nodes/discover.py` (owns the counter now).
- Tests: new `tests/test_define_counter.py` (E1 regression), extend
  `tests/test_w2_wayforward.py` only if the shared helper changes its
  contract (it doesn't — `_maybe_increment_loop` is deleted, not
  re-specified), new `tests/test_abort_manager.py`, new
  `tests/test_diff_engine_prompt.py`, extend `tests/test_runner_hil_loop.py`
  for E12.
- Spec deltas: `workflow-orchestration` (loop counters are node-owned,
  pure-helper increment), `pattern-memory` (structured prompt-diff
  contract, Decision 4), `human-in-the-loop` (DISCOVER owns
  `discover_hil_count`), `web-frontend` (per-workflow abort signal),
  `engineering-conventions` (no in-place state mutation; config is
  import-time-resolved).
