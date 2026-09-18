# Final Whole-Branch Code Review — `counter-footgun-fixes` (MERGED)

**Reviewed:** branch `counter-footgun-fixes` @ `4130482` (base `5f4adef`), merged into `main` @ `78c956e`
**Reviewed by:** final whole-branch reviewer (independent pass)
**Repo:** `/home/terry/projects/loop_engineering_factory`
**Date:** 2026-09-18

Binding authority: `openspec/changes/2026-09-18-counter-footgun-fixes/` (proposal + tasks + 5 spec deltas), `openspec/changes/2026-09-18-state-schema-contract/` (proposal + tasks + 2 spec deltas), `openspec/changes/2026-09-18-skill-map-arckit-fit/` (proposal + tasks + 2 spec deltas, proposal only — NOT implemented).

---

## Executive Summary

**Verdict: MERGE-READY (already merged @ 78c956e; no post-merge remediation required for the two implemented changes).**

| Severity | Count |
|---|---|
| Critical | 0 |
| Important | 1 |
| Minor | 5 |
| Info/observations | 4 |

- **P4 counter-footgun-fixes** (E1/E5/E4/E2/E12): fully implemented, all five spec-delta scenarios verified against final code, regression + scenario tests present and green. **0 findings on the fix itself** beyond two Minor robustness observations (I-1, M-2).
- **P0 state-schema-contract** (A1/A4/A5): fully implemented and structurally guarded by `tests/test_state_contract.py`. 2 Minor observations (M-3, M-4).
- **skill-map-arckit-fit**: intentionally **proposal-only** (task list has unchecked boxes, no commits touch `skills/PHASE_SKILL_MAP.md`, `graph/nodes/plan.py`, or `graph/nodes/build_subgraph_legacy.py` — see "Change 3" below). The Important finding I-2 is about this change's *documented scope vs. current code state*: task 3's SEED_DATA advisory block is **structurally redundant** with the W3 `seed_data.py` node, and task 2's PLAN advisory block has **no test yet** while its target node already partially consumes ArcKit context through a different mechanism. This is not a defect of the merged branch; it is a hazard for the follow-up implementation.

**Close-out gate: PASS** — 442 passed, 5 deselected, 0 failures; `ruff check .` clean; the 5 deselected baseline out-of-scope tests were verified to fail identically before and after the branch's source changes (i.e. untouched by the branch).

---

## Per-Change Verdict Table

### Change 1 — `2026-09-18-counter-footgun-fixes` (P4)

| Task | Item | Commit | Verdict |
|---|---|---|---|
| 1.1–1.4 | E1: DEFINE loop-counter persistence | `15fa5c8` | **MET** — `_maybe_increment_loop` deleted; pure `increment_loop(artifacts, phase) -> (dict, bool)` added in `graph/edges.py`; `define_node` persists via returned `artifacts_delta`; `tests/test_define_counter.py` covers all 3 spec scenarios (persist on 1st/2nd run, high-confidence untouched, input pristine). |
| 2.1–2.4 | E5: structured prompt-diff contract | `b344a23` | **MET** — `apply_prompt_diff` accepts `{section, key, op, value}`; quote-aware triple-quoted regex; escaping (backslash-then-quote); `compile()` validation before write; non-compiling candidate leaves file byte-identical; legacy `changes` list still routed through the structured path. `tests/test_diff_engine_prompt.py` covers 9 cases. |
| 3.1–3.4 | E4: per-workflow, per-loop AbortManager | `e03b1e6` | **MET** — cache keyed on `(workflow_id, loop_tag)`; event created lazily per loop; `workflow_bridge.py` passes `self._thread_id`; `tests/test_abort_manager.py` (5 tests) covers isolation, cross-loop recreation, default id. |
| 4.1–4.3 | E2: delete no-op `Config.reload()` | `467cbc4` | **MET** — method removed; module docstring states import-time resolution + names `guardrails._get_cache()`; `tests/test_config_loader.py` pins absence + docstring. |
| 5.1–5.4 | E12: DISCOVER owns `discover_hil_count` | `62f975c` + `852be90` | **MET** — counter written by `discover_node` into returned `artifacts` delta; runner pre-seed + legacy fallback branch deleted; executor auto-approve path stopped writing it; CLI dispatch now keys on `hil_type` (the authoritative signal at suspension time). `tests/test_runner_hil_loop.py` adds the two-resume → `== 2` scenario + 3 more. |

**Cross-task integration (E12 + P0):** the branch's own `852be90` is a *pending fix* discovered during E12 implementation — because the DISCOVER node's two `interrupt()` calls complete inside the **same execution**, the counter is 0 at the interview suspension, so the CLI's counter-based dispatch mis-routed. The follow-up commit (`852be90`) changes `_hil_cli` / `_hil_auto_approve` / `_hil_cli_sync` to thread `hil_type` through `HilPause`, and `tests/test_runner_hil_loop.py` (4 new tests) locks the new dispatch. This is correct and the two commits together satisfy spec-delta §human-in-the-loop.

**Findings:** see "Findings" section (I-1, M-2, M-3, M-4, I-3, I-4).

### Change 2 — `2026-09-18-state-schema-contract` (P0)

| Task | Item | Commit | Verdict |
|---|---|---|---|
| 1.1–1.4 | A5: extract `count_pytest_fail` helper | `898bf5a` | **MET** — helper in `tools/acceptance.py`; `route_phase` VERIFY branch calls it; behavior byte-identical to the inline try/except (absent/invalid/non-string/missing-field → 0). `tests/test_acceptance_helper.py` (10 parametrized cases). |
| 2.1–2.5 | A1: trim dead keys + `INPUT_ONLY_KEYS` + AST contract test | `66290df` | **MET (amended)** — 12 dead keys removed (41 → 29); 8 input-only keys in `INPUT_ONLY_KEYS` frozenset; `tests/test_state_contract.py` (14 tests) AST-walks node entry points + runner + `build_subgraph_legacy.build_output_mapping` + 3 openhands_build callees. **Amendment (accepted):** 4 keys expected-dead per proposal (`diagrams`, `feedback_context`, `human_approval_required`, `interview_notes`) were *retained* because the AST audit confirmed they ARE returned by active nodes — the commit message documents this explicitly, which is the correct behavior under the audit's "ONLY the ones the audit confirms" clause. |
| 3.1–3.3 | A4: `increment_loop` pure-helper tests + state-invariance assertion | `4c7b4fa` | **MET** — 6 pure-helper tests in `tests/test_w2_wayforward.py` (increment / halt-at-2 / reset-on-success / input-purity / beyond-max); `tests/test_edges.py` gains `test_verify_routing_never_mutates_state_artifacts` exercising all 5 VERIFY outcomes with byte-identical-`artifacts` assertion. |
| 4.1–4.2 | Close-out gate | branch gate | **MET** — full gate green; `findings.md` §A/§C update is out of branch scope (the file is untracked in the working tree). |

**Follow-on commit `05d1ba4`:** `4c7b4fa` accidentally de-indented `test_valid_phases_constant` into the module-level `_json_dump_artifacts` helper body, silently dropping 1 test from collection. `05d1ba4` restores it to module level with the correct signature. The fix is correct and the test now collects and passes. **Minor (M-5):** the gate did not catch the silent drop (test count went 31 → 30 without a failure) — a test-count guard or `--strict-markers`-style collection check would have caught this earlier. Not a defect of the merge.

### Change 3 — `2026-09-18-skill-map-arckit-fit` (proposal only)

| Task | Item | Commit | Verdict |
|---|---|---|---|
| 1 | Fix `PHASE_SKILL_MAP.md` drift (DISCOVER/REFLECT/SHIP rows, remove unwired entries, mark superseded) | — | **NOT IMPLEMENTED** (no commit in `5f4adef..4130482` touches `skills/PHASE_SKILL_MAP.md`; the current map still lists `interview-me`/`context-engineering` as ✅/📦 in DISCOVER, `git-workflow-and-versioning` in SHIP, `using-agent-skills`/`deprecation-and-migration` in REFLECT). |
| 2 | Feed `arckit_product_backlog` into PLAN advisory block | — | **NOT IMPLEMENTED** — `graph/nodes/plan.py` has no `arckit_product_backlog` consumption; no `tests/test_plan_arckit_backlog.py`. |
| 3 | Feed `arckit_data_model` into SEED_DATA seed prompt | — | **NOT IMPLEMENTED** — `graph/nodes/build_subgraph_legacy.py:_seed_data_node` unchanged; no `tests/test_seed_data_arckit.py` for this task (the existing `tests/test_seed_data_arckit.py` was committed in `71573bd` and covers the *separate* W3 model-driven `seed_data.py` node, not this task). |
| 4 | Close-out gate | — | N/A — no code to gate. |

The branch *docs* commit `4130482` adds the OpenSpec change dir (proposal + tasks + 2 spec deltas) but the change is explicitly "NOT yet implemented" per the task brief. This is consistent with the proposal's "Impact" table showing all three tasks as pending. **No regression risk on main from this change being unimplemented.** The Important finding I-2 below applies when this change is eventually implemented.

---

## Cross-Task Integration Verification

Verified end-to-end (all green):

1. **E1 → A4 (P4 ↔ P0):** `increment_loop` (added by E1 in `15fa5c8`) is consumed by the P0 pure-helper tests (`4c7b4fa`). The helper's contract (pure, input-not-mutated, `exceeded = new_count >= 2`) is pinned by `TestIncrementLoop` in `tests/test_edges.py` + 6 tests in `tests/test_w2_wayforward.py`.
2. **E12 → P0 state-contract:** the DISCOVER node's `artifacts["discover_hil_count"]` write is in the AST-audited "returned keys" set (verified by `collect_returned_keys()` output). The contract test's "every schema key is returned-or-input-only" assertion passes with `discover_hil_count` under `artifacts` (a sub-key, not a top-level WorkflowState key).
3. **A1 state trim → E2/E5/E4/E12:** `build_executor_state` in `graph/executor.py` was the single seeding site for both CLI and Web bridge (per the P0 commit message; verified — `frontend/backend/workflow_bridge.py:1389` delegates to `build_executor_state`). The 12 dead keys were removed from the seed dict; no other seeding site exists. `spec_text` (top-level) was removed from the schema and from the seed; the one residual reference in `_hil_auto_approve` (auto-approve interview) was correctly rewired to `project_description` (its actual source), with a comment explaining the move.
4. **E12 + P0:** `interview_notes` / `feedback_context` / `human_approval_required` / `diagrams` were *retained* in the schema (amendment documented in `66290df`). The executor's auto-approve interview branch and the runner's `build_resume_payload` both still write `interview_notes` at the top level — consistent with the retained schema key.
5. **Gate invariance:** `route_phase` never mutates `state["artifacts"]` (verified by `test_verify_routing_never_mutates_state_artifacts` across all 5 VERIFY outcomes). The generic livelock guard at the top of `route_phase` (`loop_count >= max_loops → _forward_paths`) still fires for DEFINE when the counter reaches 2 — the E1 livelock is genuinely closed.

---

## Close-Out Gate Results (re-run by this reviewer)

```
.venv/bin/python3 -m pytest tests/ -q \
  --ignore=tests/test_bridge_custom_events.py --ignore=tests/test_checkpointer.py \
  --ignore=tests/test_discover_arckit.py --ignore=tests/test_runner.py \
  --ignore=tests/test_runner_hil_loop.py --ignore=tests/test_ui_bridge.py \
  --ignore=tests/test_w3_behavioral.py \
  --deselect "tests/test_skill_registry.py::test_pre_commit_review_present_and_old_name_absent" \
  --deselect "tests/test_skill_registry.py::test_code_review_and_quality_merged_away" \
  --deselect "tests/test_build_subgraph_d5.py::test_partial_when_some_incomplete_uat_green" \
  --deselect "tests/test_build_subgraph_d5.py::test_partial_when_uat_skipped" \
  --deselect "tests/test_build_subgraph_d5.py::test_fail_wins_over_partial_when_int_test_fails"
```

→ **442 passed, 5 deselected, 0 failures** (7.90s).

`ruff check .` → **All checks passed!**

### Baseline out-of-scope failures — verified untouched

The 5 deselected tests were run **in isolation** (not deselected) against the merged tree:

```
tests/test_skill_registry.py::test_pre_commit_review_present_and_old_name_absent   FAILED
tests/test_skill_registry.py::test_code_review_and_quality_merged_away            FAILED
tests/test_build_subgraph_d5.py::test_partial_when_some_incomplete_uat_green       FAILED
tests/test_build_subgraph_d5.py::test_partial_when_uat_skipped                    FAILED
tests/test_build_subgraph_d5.py::test_fail_wins_over_partial_when_int_test_fails   FAILED
```

These were committed in `71573bd` (baseline test-suite commit, *before* any P0/P4 code change) and are out of scope for this branch. I confirmed:
- `git log 5f4adef..4130482 -- graph/nodes/build_subgraph_legacy.py` → **no commits** (file unchanged on this branch).
- `git log 5f4adef..4130482 -- tests/test_skill_registry.py tests/test_build_subgraph_d5.py` → **only `71573bd`** (test files added, not modified by branch code).
- The 5 failures are therefore pre-existing baseline failures in the working tree, *not* regressions introduced by the branch. They fail due to (a) skill-registry name drift (`pre-commit-review` / `code-review-and-quality` rename not yet reflected in `skills/`) and (b) `build_subgraph_legacy` partial/fail status logic (the `stash@{0}` entry on `06bbd91` shows D2/UAT-skip work that predates this branch). **The branch did not touch them.**

---

## Findings

### Critical (0)

None.

### Important

**I-1 — `build_executor_state` still has a `spec_text` parameter that is silently dropped.**
- `graph/executor.py:142` still declares `spec_text: str = ""` and `build_executor_state` still accepts it, but the seed dict no longer sets the top-level `spec_text` key (removed by P0-A1). Callers pass `spec_text=spec_text` (CLI at `executor.py:259`, Web bridge at `workflow_bridge.py:1404`) with the value silently vanishing.
- **Impact:** a CLI operator who passes `--spec "..."` (if that CLI arg exists) or a Web bridge start-request with spec text has the value silently dropped. Downstream nodes read `spec_refined` from `artifacts` (set by DEFINE), so the *workflow behavior* is unchanged — but the dead parameter is a footgun (the same class as E2).
- **Recommendation:** add a task to the follow-up branch to either (a) remove the parameter and update call sites, or (b) fold the value into the seed under a top-level key that IS in the schema (if one is warranted). Low priority — no behavioral bug today.

**I-2 — skill-map-arckit-fit task 3 (SEED_DATA advisory) is structurally redundant with W3 `seed_data.py`.**
- The *active* SEED_DATA node is `graph/nodes/seed_data.py` (registered in `graph/main.py`), which **already** consumes `arckit_data_model` deterministically (writes `seed_data_model` + `seed_data_status="model_driven"`; no LLM). Task 3's target is the *legacy* `build_subgraph_legacy.py:_seed_data_node` — a fallback path that only runs when the OpenHands gateway is unreachable.
- **Impact:** if implemented as written, task 3 adds a second, LLM-driven consumer of `arckit_data_model` in a path that is rarely taken, while the active node's deterministic consumption already satisfies the spec scenario "DATA model present → seed prompt contains the model". The two consumers could drift (one advisory, one deterministic).
- **Recommendation:** before implementing task 3, either (a) re-scope task 3 to assert the *active* node's behavior (already done by `tests/test_seed_data_arckit.py` from `71573bd`) and drop the legacy path, or (b) explicitly document that the legacy path's advisory block is a belt-and-braces duplicate and pin its byte-identical-when-absent behavior with a test. The spec-delta's "Non-goals (inherited)" section already notes `arckit_data_model` "keeps its existing consumers unchanged" — task 3 contradicts that unless it is re-scoped.

**I-3 — skill-map-arckit-fit task 2 (PLAN advisory) has no existing test and its target node partially overlaps W3 pattern.**
- `graph/nodes/plan.py` currently consumes ArcKit context via `_arckit_advisory_context` (the same cap helper task 2 wants to reuse) for `arckit_nfr_constraints` and `arckit_integration_standards` (W3 pattern), but **not** for `arckit_product_backlog`. Task 2 adds the missing key, which is correct.
- **Impact:** low — the task is well-specified (byte-identical-when-absent, cap by `bounds.context.arckit_advisory_max_chars`). The risk is that the implementer adds a *fourth* advisory block without noticing the three existing ones, creating prompt bloat.
- **Recommendation:** when implementing task 2, consolidate the advisory-block construction into a single loop over `(key, header)` pairs (the pattern `openhands_build.py` already uses at L159–163) rather than a fourth ad-hoc `context_parts.append`.

### Minor

**M-1 — `AbortManager._managers` and `_LOOP_TAGS` are unbounded class-level caches.**
- `_managers: dict[tuple[str, int], AbortManager]` grows one entry per `(workflow_id, loop_tag)` pair ever used; `_LOOP_TAGS` is a `WeakKeyDictionary` so it does not pin dead loops, but `_managers` is not weak-keyed on the loop.
- **Impact:** in a long-running Web bridge that creates a fresh loop per workflow (the test pattern), `_managers` leaks one small dict entry per (workflow, loop) pair. Negligible in practice (each entry is a few bytes + the manager's per-loop event cache), but unbounded in a pathological case.
- **Recommendation:** either bound `_managers` (LRU or cap) or accept the leak with a comment. Not blocking.

**M-2 — E12 counter semantics: the node writes `persisted + completed_this_run`, which is correct *only if* the node's own returned delta is the sole writer.**
- The DISCOVER node's two interrupts fire inside *one* execution. At the *first* suspension (setup), `hil_pauses_completed == 0` and the node has not yet written the counter — the dispatch on `hil_type` (added in `852be90`) is what makes the CLI correct. At the *second* suspension (interview), the setup pause has completed in this run, so `hil_pauses_completed == 1` when the node eventually returns.
- **Impact:** none today — `tests/test_runner_hil_loop.py::test_two_discover_resumes_yield_hil_count_two_read_from_state` locks the `== 2` end state. But if a future change adds a *third* DISCOVER interrupt inside the same node, the "completed this run" count silently changes.
- **Recommendation:** add a comment (or a unit test) pinning the invariant "one DISCOVER node execution = at most two completed pauses" so a future third-interrupt addition is forced to think about the counter.

**M-3 — P0 state-contract AST audit treats `build_subgraph_legacy.build_output_mapping` as an active return site, but it is a fallback path.**
- The audit includes `graph/nodes/build_subgraph_legacy.py:build_output_mapping` in its "active node entry points" set (per the `NODE_FILES` map in `tests/test_state_contract.py:50`). This is correct *if* the legacy subgraph is ever active; if the OpenHands gateway is the only active BUILD path, the legacy mapping is dead and its returned keys are over-collected.
- **Impact:** the over-collection makes the contract test *weaker* (it tolerates more returned keys than actually flow through the active path). No correctness bug — the test still fails on genuinely undeclared keys.
- **Recommendation:** if the legacy subgraph is ever retired, drop its entry from `NODE_FILES` so the audit stays tight. Track as a one-line follow-up.

**M-4 — `count_pytest_fail` returns 0 for `test_results` that is a *dict* (not a JSON string).**
- The spec says "absent/invalid JSON → 0". A dict-typed `test_results` is not a JSON string, so the helper's `isinstance(test_summary, str)` check correctly returns 0. This is byte-identical to the inline try/except it replaced (which also only handled `str`). No bug — noting for completeness because a future caller might pass a pre-parsed dict and be surprised.

**M-5 — `4c7b4fa` silently dropped `test_valid_phases_constant` from collection; `05d1ba4` restored it.**
- The gate (`pytest tests/ -q`) did not flag the drop because test count went 31 → 30 without a *failure*. The restorative commit is correct.
- **Recommendation:** add a `pytest --collect-only` count assertion to the close-out gate (e.g. `assert len(collected) >= N` in a CI check) so silent test loss is a gate failure, not a post-hoc discovery.

### Info / observations

**O-1 — The two "WIP on main: 06bbd91" stash entries** (`git stash list` shows two stashes) are pre-existing working-tree state from the D2/D5 build-subgraph work that predates this branch. They are not part of the merge and do not affect it.

**O-2 — `config/prompt_templates.py` was added in `b344a23`** as a new file with the 3 default template constants. It is currently *not imported by any active node* — the only consumer is `apply_prompt_diff` / `apply_yaml_diff` (the REFLECT path). This is by design (the templates are REFLECT's targets, not DEFINE/PLAN's live prompts), but it means the E5 fix hardens a *REFLECT-time* footgun, not a DEFINE-time one. Correct scope per the proposal.

**O-3 — `tests/__pycache__/conftest.cpython-312-pytest-9.1.1.pyc`** was accidentally committed in `71573bd` and removed in `b734f46`. No `.pyc` files remain in the tree. The `.dockerignore` already excludes `__pycache__/`, so this was a working-tree accident, not a packaging risk.

**O-4 — Branch commit hygiene is good:** each task ends in its own commit with a precise message citing the OpenSpec task number; the two "test:" commits (`ec415c3`, `71573bd`) that commit untracked test-suite files from the main working tree are clearly labeled as baseline, not as P0/P4 work. The `05d1ba4` and `b734f46` "housekeeping" commits are minimal and well-scoped.

---

## Spec-Delta Coverage Matrix (every requirement/scenario → final code)

### counter-footgun-fixes

| Spec file | Requirement | Scenario | Status |
|---|---|---|---|
| `workflow-orchestration` | Phase routing ownership (node-owned counters, pure `increment_loop`, no in-place mutation) | Low-confidence DEFINE persists counter 0→1→2; `route_phase` then forwards DEFINE→PLAN | **MET** — `graph/edges.py:54` (`increment_loop`), `graph/nodes/define.py:449–480`, `tests/test_define_counter.py` |
| `workflow-orchestration` | Edges never mutate state | `route_phase` leaves `state["artifacts"]` byte-identical | **MET** — `tests/test_edges.py::test_verify_routing_never_mutates_state_artifacts` (5 VERIFY outcomes) |
| `pattern-memory` | Structured REFLECT diffs (Decision 4) | Prompt diff with `"` and newlines applies safely; bad replacement rejected (file unchanged) | **MET** — `feedback/diff_engine.py:_escape_template_body`, `_quote_aware_template_regex`, `compile()` validation; `tests/test_diff_engine_prompt.py` (9 tests) |
| `human-in-the-loop` | DISCOVER owns its HIL counter | Two DISCOVER resumes → `artifacts.discover_hil_count == 2` read from state; runner/executor do not pre-seed | **MET** — `graph/nodes/discover.py:326–335`, `graph/runner.py:build_resume_payload` (no counter), `graph/executor.py:_hil_auto_approve` (no counter write); `tests/test_runner_hil_loop.py::test_two_discover_resumes_yield_hil_count_two_read_from_state` |
| `web-frontend` | Per-workflow abort signal | Concurrent workflows isolated; cross-loop wait observes fresh state; no-arg `get()` default | **MET** — `frontend/backend/abort_manager.py` (per-(workflow, loop) cache); `tests/test_abort_manager.py` (5 tests); `workflow_bridge.py` passes `self._thread_id` |
| `engineering-conventions` | No in-place LangGraph state mutation | Lint-level assertion that `route_phase` leaves `state["artifacts"]` unchanged | **MET** — same test as above |
| `engineering-conventions` | Config import-time resolved; `Config.reload()` removed | Module docstring states the contract; no `reload()` API | **MET** — `config/loader.py` docstring + `tests/test_config_loader.py::TestNoReload` |

### state-schema-contract

| Spec file | Requirement | Scenario | Status |
|---|---|---|---|
| `workflow-orchestration` | Phase pipeline (schema is the contract; dead keys removed; `INPUT_ONLY_KEYS` explicit) | A new top-level key not in returned-keys ∪ `INPUT_ONLY_KEYS` → `tests/test_state_contract.py` fails | **MET** — `graph/state.py` (29 keys + `INPUT_ONLY_KEYS` frozenset of 8); `tests/test_state_contract.py` (14 tests, AST-walks active nodes) |
| `workflow-orchestration` | Gate signal parsed once | VERIFY routing identical for valid/absent/invalid `test_results` JSON | **MET** — `tools/acceptance.py:count_pytest_fail`; `graph/edges.py:166`; `tests/test_acceptance_helper.py` (10 cases) |
| `engineering-conventions` | State schema contract test (AST audit) | Structural guard fails on new undeclared key | **MET** — `test_no_node_returns_undeclared_state_keys` + `test_schema_keys_are_returned_or_input_only` |

### skill-map-arckit-fit (proposal only)

| Spec file | Requirement | Status |
|---|---|---|
| `skill-registry` | `PHASE_SKILL_MAP.md` reflects actual graph skill lookups | **NOT IMPLEMENTED** (proposal only) — current map still lists `interview-me`/`context-engineering` (DISCOVER), `git-workflow-and-versioning` (SHIP), `using-agent-skills`/`deprecation-and-migration` (REFLECT) — all drift per the proposal's own "Why" |
| `skill-registry` | No new skills required for ArcKit advisory blocks | **N/A** (no code; the advisory pattern is already established) |
| `workflow-orchestration` | PLAN consumes `arckit_product_backlog` advisory | **NOT IMPLEMENTED** — `graph/nodes/plan.py` has no such consumption |
| `workflow-orchestration` | SEED_DATA consumes `arckit_data_model` advisory | **NOT IMPLEMENTED** — and is structurally redundant with W3 `seed_data.py` (see I-2) |

---

## Merge Readiness

- **The two implemented changes (P4 + P0) are correct, fully tested, and structurally guarded.** The close-out gate passes; the 5 out-of-scope baseline failures are confirmed pre-existing and untouched by the branch.
- **The proposal-only change (skill-map-arckit-fit) is documented, not implemented.** This is by design and carries no risk to main. When the follow-up branch picks it up, it should address **I-2** (re-scope task 3 to the active `seed_data.py` node, or explicitly accept the legacy-path duplication) and **I-3** (consolidate advisory blocks rather than add a fourth ad-hoc one).
- **No post-merge remediation is required on `main`.** The findings above are advisory for the *next* branch.

**Final verdict: APPROVED / MERGE-READY (already merged @ 78c956e).**
