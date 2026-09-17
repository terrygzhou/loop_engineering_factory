# Tasks — state-schema-contract

Depends on `2026-09-18-counter-footgun-fixes` task 1.3
(`_maybe_increment_loop` deleted, `increment_loop` added) landing first —
that change is on the same branch and is sequenced before this one.
Gate for the whole branch: AGENTS.md close-out command
(`pytest tests/ -q` with the 7 hang files `--ignore`d and the 9 health
socket tests `--deselect`ed → 0 failures; `ruff check .` clean).

## 1. A5 — extract the test_results parse into a helper

- [ ] 1.1 Write `tests/test_acceptance_helper.py` (or extend an
      existing acceptance test file): `count_pytest_fail(artifacts)`
      returns `artifacts.test_results`'s `pytest_fail` int when the
      JSON is valid; returns 0 when `test_results` is absent, empty,
      or invalid JSON; returns 0 when `pytest_fail` is missing or null.
- [ ] 1.2 Add `count_pytest_fail(artifacts: dict) -> int` to
      `tools/acceptance.py` (next to `parse_acceptance_block`).
- [ ] 1.3 In `graph/edges.py` VERIFY branch: replace the inline
      `json.loads(...)` try/except with `test_errors =
      count_pytest_fail(state.get("artifacts", {}))`.
- [ ] 1.4 Run `pytest tests/test_edges.py tests/test_w2_wayforward.py
      -q` (VERIFY routing paths must stay green: pass/fail/acceptance/
      budget-exhausted); commit.

## 2. A1 — trim the dead top-level schema + contract test

- [ ] 2.1 Run the AST audit the finding describes (a throwaway script
      is fine, not committed): for every active node in
      `graph/nodes/{discover,define,plan,review,openhands_build,seed_data,verify,ship,reflect}.py`
      + `graph/runner.py`, collect the top-level keys of the dicts
      they `return` / build as partial updates. Cross-check against the
      41 declared `WorkflowState` keys.
- [ ] 2.2 In `graph/state.py`: delete the dead top-level keys the audit
      confirms are never returned (expected: `tasks`, `tasks_text`,
      `backlog`, `solution_md`, `plan`, `status`, `retry_count`,
      `spec_text`, `spec_refined`, `project_context`, `interview_notes`,
      `diagrams`, `diagram_pngs`, `feedback_context`,
      `human_approval_required` — but ONLY the ones the audit confirms;
      if a key IS returned by an active node, it stays). Add
      `INPUT_ONLY_KEYS: frozenset[str]` = the 8 input-only keys
      (`skip_discover`, `improve_mode`, `force_hil`,
      `auto_approve_override`, `arckit_artifacts`, `trace_id`,
      `cycle_id`, `config_version`) as an explicit allowlist next to
      the TypedDict.
- [ ] 2.3 Update initial-state seeding: `graph/runner.py` and
      `frontend/backend/workflow_bridge.py` build their initial
      WorkflowState dicts; remove any key not in the trimmed schema
      (grep for each deleted key name to catch the seed sites).
- [ ] 2.4 Write `tests/test_state_contract.py`: AST-walk
      `graph/nodes/*.py` + `graph/runner.py`, collect returned
      top-level keys; assert every `WorkflowState` key is in
      (returned-keys ∪ INPUT_ONLY_KEYS); assert every
      INPUT_ONLY_KEYS entry is actually declared in the TypedDict.
      (This is the structural guard: a new top-level key added by a
      future node that isn't on the schema and isn't input-only fails
      the suite.)
- [ ] 2.5 Run `pytest tests/test_state_contract.py tests/test_edges.py
      tests/test_workflow_lifecycle.py -q`; commit.

## 3. A4 follow-on — pure-helper tests (after counter-footgun task 1.3)

- [ ] 3.1 Extend `tests/test_w2_wayforward.py` with `increment_loop`
      tests: increment (0→1, not exceeded), halt-at-2 (1→2, exceeded
      True), reset-on-success (caller passes a fresh dict → back to 0),
      and "returns a new dict, input unchanged" (the helper is pure).
- [ ] 3.2 Add the state-invariance assertion to `tests/test_edges.py`:
      after `route_phase(state)` for VERIFY, `state["artifacts"]` is
      byte-identical (edges never mutate).
- [ ] 3.3 Run `pytest tests/test_w2_wayforward.py tests/test_edges.py
      -q` + `ruff check .`; commit.

## 4. Close-out

- [ ] 4.1 Full close-out gate: `pytest tests/ -q` with the 7 hang
      files `--ignore`d and the 9 health socket tests `--deselect`ed →
      0 failures; `ruff check .` clean.
- [ ] 4.2 Update `findings.md` §A/§C: mark A1/A4/A5 + Phase 0
      complete; note P1 typed-artifacts is intentionally out of scope
      for this branch.
