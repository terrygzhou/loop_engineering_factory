# Tasks — counter-footgun-fixes

Order: E1 (the bug, first — everything else is independent hardening) →
E5 → E4 → E2 → E12. Each task is independently testable and ends with a
commit. Gate for the whole branch: AGENTS.md close-out command
(`pytest tests/ -q` with the 7 hang files `--ignore`d and the 9 health
socket tests `--deselect`ed → 0 failures; `ruff check .` clean).

## 1. E1 — DEFINE loop-counter persistence (the livelock bug)

- [ ] 1.1 Write `tests/test_define_counter.py`:
      - low-confidence DEFINE run (mock `_estimate_spec_confidence` → 0.5)
        persists `artifacts.loop_counts["DEFINE"] == 1`
      - a second low-confidence run (seed `loop_counts["DEFINE"]=1` into the
        incoming state) persists `== 2` and the node logs the "loop limit
        reached, forcing forward" progress event
      - high-confidence run does not touch `loop_counts`
- [ ] 1.2 In `graph/nodes/define.py`: on low confidence, build
      `loop_counts = dict(state.get("artifacts", {}).get("loop_counts", {}))`,
      increment `loop_counts["DEFINE"]`, include it in the returned
      `artifacts` delta; drop the `from graph.edges import _maybe_increment_loop`
      call. Keep the existing two progress events (the "looping back" /
      "forcing forward" wording stays).
- [ ] 1.3 In `graph/edges.py`: delete `_maybe_increment_loop`; add the
      pure helper `increment_loop(artifacts: dict, phase: str) -> tuple[dict, bool]`
      (new dict, `(new_artifacts, exceeded)` where `exceeded =
      new_counts[phase] >= 2`). `define_node` uses it so no node mutates
      state in place anywhere.
- [ ] 1.4 Run `pytest tests/test_define_counter.py tests/test_w2_wayforward.py
      tests/test_edges.py -q`; commit.

## 2. E5 — structured prompt-diff contract (diff_engine)

- [ ] 2.1 Write `tests/test_diff_engine_prompt.py`:
      - structured diff `{"section": "<name>", "key": "template_body",
        "op": "replace", "value": "<new text containing \" quotes and newlines>"}`
        rewrites the template in `config/prompt_templates.py`; the file
        still `compile()`s afterwards
      - `value` containing a `"""` sequence cannot break out of the
        assignment (regex is quote-aware: it matches the existing
        triple-quoted body via `"""..."""` with `re.DOTALL`
        non-greedy-to-closing-quote, not `[^\"]*`)
      - a non-compiling replacement leaves the original file untouched
        (assert file content == original)
- [ ] 2.2 In `feedback/diff_engine.py` `apply_prompt_diff`: accept the
      structured shape `{section, key, op, value}` (keep the legacy
      `diffs["changes"]` list reading but route each change through the
      structured path); locate the template with a quote-aware regex
      (triple-quoted body); build the replacement by writing
      `<name> = """..."""` with the value escaped (`\`, `"`, newline-safe);
      `compile(candidate, template_file, "exec")` before writing; on
      `SyntaxError`, log + return False, file unchanged.
- [ ] 2.3 Find REFLECT's `apply_prompt_diff` call site(s)
      (`grep -rn apply_prompt_diff graph/ feedback/`) and update the
      payload construction to emit the structured shape when it constructs
      diffs; if a caller passes the legacy `changes` list, that shape is
      still accepted (backward compat, no caller change required).
- [ ] 2.4 Run `pytest tests/test_diff_engine_prompt.py -q`; commit.

## 3. E4 — per-workflow, per-loop AbortManager

- [ ] 3.1 Write `tests/test_abort_manager.py`:
      - two managers for two workflow ids on the same loop: signaling one
        does not affect the other
      - `signal()` from a different loop than the one that created the
        event is a no-op returning False (or the manager recreates the
        event on first use in the current loop — pick recreation, test
        that `wait()` on a fresh loop observes a fresh un-aborted state)
      - `AbortManager.get()` with no workflow id keeps working for
        single-workflow callers (module default)
- [ ] 3.2 In `frontend/backend/abort_manager.py`: key the cache on
      `(id(asyncio.get_running_loop()) if running else 0, workflow_id)`;
      lazily create the `asyncio.Event()` on first use inside the owning
      loop (recreate per-loop), so a stale cross-loop event is never
      observed. Keep `get()` → default workflow id.
- [ ] 3.3 Update `frontend/backend/workflow_bridge.py` call sites to pass
      the workflow id (grep `AbortManager.get()` / `.get()` usages);
      `graph/executor.py`'s sync `abort_check()` path keeps using the
      default workflow id unless it already carries one.
- [ ] 3.4 Run `pytest tests/test_abort_manager.py tests/test_ui_bridge.py
      -q` (ui-bridge test may be in the 7 hang files in this env — run it
      with a `timeout`; monkeypatched variants pass without); commit.

## 4. E2 — delete the no-op Config.reload()

- [ ] 4.1 In `config/loader.py`: delete `Config.reload()`; add a module
      docstring line: "Config values are resolved at import time
      (env > config.yaml > default); restart the process to pick up
      changes. `config.guardrails._get_cache()` is the one working
      mtime-reload path (REFLECT guardrails)."
- [ ] 4.2 Grep `\.reload\(\)` repo-wide (excluding node_modules/.venv):
      confirm zero callers; update any docstring/comment that references
      `reload()`.
- [ ] 4.3 Run `pytest tests/ -q -k config` (if a config test file
      exists) + `ruff check .`; commit.

## 5. E12 — DISCOVER owns discover_hil_count

- [ ] 5.1 Grep all `discover_hil_count` sites: `graph/runner.py`
      (pre-seed increment + legacy fallback branch), `graph/executor.py`
      (auto-approve interview write + readers), `graph/nodes/discover.py`
      (reader). Confirm the active Web path always knows `hil_type`
      (hil_type is extracted from the interrupt payload by the bridge).
- [ ] 5.2 Move the increment into `discover_node`'s returned `artifacts`
      delta (increment on every DISCOVER HIL resume — setup AND interview,
      matching the current semantics exactly); delete the runner-side
      `update_data` pre-seed increment and the "unknown DISCOVER type →
      fall back on hil count" branch; stop the executor auto-approve
      interview dict from writing the counter.
- [ ] 5.3 Tests: `tests/test_runner_hil_loop.py` (existing) still green;
      add a case: two sequential DISCOVER resumes (setup, then interview)
      yield `artifacts.discover_hil_count == 2` read from state (the
      reader's source of truth), not from a side channel.
- [ ] 5.4 Run the affected tests + `ruff check .`; commit.
