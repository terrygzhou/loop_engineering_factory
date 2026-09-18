# Tasks — node-module-split

Order: S0 (seam conventions + re-export shim) → S1..S8 (one split per
file, ordered smallest→largest so the convention is proven on
`review.py`/`ship.py`-class files before the big ones) → S9 (docs +
gate). Every task ends with a green gate run and a commit.

**Seam rule** (per `specs/node-module-seams/spec.md`): a function moves to
a sibling module only when it has no `interrupt()` / `invoke_skill*` /
`httpx` / LLM-`asyncio.gather`, no owned audit/writer emission, and a
stateless signature. What stays: the `*_node` entry, HIL calls, LLM
orchestration (incl. Decision-3 None-coercion at the call site), audit /
stream-writer emissions, partial-update delta construction.

**Re-export shim (S0):** after a move, the original node module keeps a
re-export (`from graph.nodes.<sibling> import _helper`) for every moved
private name so existing test imports (e.g. `from graph.nodes.plan import
_extract_use_cases`) keep resolving. The re-export is the seam; tests may
later migrate to the sibling import as each sibling task lands.

Gate for the whole change: AGENTS.md close-out command — `pytest tests/ -q`
with the 7 hang files `--ignore`d (`test_bridge_custom_events`,
`test_checkpointer`, `test_discover_arckit`, `test_runner`,
`test_runner_hil_loop`, `test_ui_bridge`, `test_w3_behavioral`) and the 9
`test_health` socket tests `--deselect`ed → 0 failures; `ruff check .`
clean.

## 1. S0 — seam conventions

- [ ] 0.1 Create `tests/test_node_seams.py` with the seam-test fixtures
      (tmp dir + state-dict builder, no LLM/network/checkpointer
      monkeypatches).
- [ ] 0.2 No code changes; this task lands the test file + commit.
      Verify: `pytest tests/test_node_seams.py -q` passes (empty/fixture
      pass), `ruff check tests/test_node_seams.py` clean.

## 2. S1 — `review.py` (462) → `review_payload.py`

Move: `_parse_json_artifact`, `_missing_build_inputs`,
`_resolve_achg_context`, `_extract_task_breakdown`, `_spec_summary`.
Stay: `review_node` + its HIL `interrupt()`.

- [ ] 1.1 Add seam tests for the 5 moved helpers (import
      `graph.nodes.review_payload` directly; no LLM monkeypatch) —
      `tests/test_node_seams.py`.
- [ ] 1.2 Create `graph/nodes/review_payload.py`, move the 5 helpers;
      `graph/nodes/review.py` re-exports them (`from
      graph.nodes.review_payload import _parse_json_artifact, …`).
- [ ] 1.3 Verify: `pytest tests/test_review_missing_inputs.py
      tests/test_arch_review_interlocks.py -q` unchanged-pass;
      `ruff check graph/nodes/review.py graph/nodes/review_payload.py`
      clean. Commit.

## 3. S2 — `ship.py` (282): no split; test seams only

`ship_node` is below the split threshold. If S0's seam tests want to
cover ship's pure bits, extract `_`-prefixed helpers here only if the
seam rule applies (expected: none); otherwise S2 is a no-op task closed
by a note.

- [ ] 2.1 Confirm `ship_node` holds no seam-rule-eligible helper; close
      with a note in the commit message. Verify: `pytest
      tests/test_w3_behavioral.py -q` (in a normal env; the hang-file
      gate excludes it in this sandbox).

## 4. S3 — `seed_data.py` (115): no split

Below threshold; document the decision in the commit.

- [ ] 3.1 Note + commit: `seed_data.py` stays a single module;
      `graph/nodes/seed_data.py` re-export surface unchanged.

## 5. S4 — `reflect.py` (436) → `reflect_skill_review.py` + `reflect_diffs.py`

Move: the skill-review step (per-skill usage counts + LLM verdict
parsing + `storage/skill_recommendations.json` persistence) →
`reflect_skill_review.py`; config-diff generation → `reflect_diffs.py`.
LLM calls stay at the `reflect_node` call site (Decision-3
None-coercion); only the prompt-building and result-parsing helpers move.
Stay: `reflect_node`, the HIL gate, the ChromaDB cycle record, audit
events.

- [ ] 4.1 Seam tests: diff-generation helper + skill-review result
      parser, imported from the new siblings.
- [ ] 4.2 Create both sibling modules; `reflect.py` re-exports moved
      names; verify `tests/test_reflect_skill_review.py` passes with no
      body edits (import re-exports keep `import graph.nodes.reflect as
      reflect_mod` monkeypatch targets valid — if a test monkeypatches a
      moved helper by `reflect_mod._helper`, re-export keeps the patch
      effective only when the call site resolves the name from the
      sibling at call time; move the monkeypatch target to the sibling in
      the test only if the call site moved, and update the test import
      line — body logic unchanged).
- [ ] 4.3 Verify: `pytest tests/test_reflect_skill_review.py -q`,
      `ruff check` clean. Commit.

## 6. S5 — `define.py` (653) → `define_prompts.py` + `define_confidence.py`

Move: `_build_spec_context`, `_arckit_advisory_context`,
`_load_feedback_context` → `define_prompts.py`;
`_estimate_spec_confidence` → `define_confidence.py`.
Stay: `define_node`, the two parallel LLM calls (`invoke_skill_async` +
`asyncio.gather`), None-coercion, counter increment via
`increment_loop`, audit/writer.

- [ ] 5.1 Seam tests for prompt/context builders + confidence estimator
      (pure: state dict + config read passed in, no LLM).
- [ ] 5.2 Create siblings; `define.py` re-exports; check
      `tests/test_define_arckit_context.py` and `tests/test_define_counter.py`
      — both use `import graph.nodes.define as define_mod` and
      monkeypatch; confirm the monkeypatched targets still resolve
      (re-exports keep attribute access; if a test patches
      `define_mod._arckit_advisory_context` and the call site now
      resolves from `define_prompts`, patch the sibling module — import
      line only).
- [ ] 5.3 Verify: `pytest tests/test_define_arckit_context.py
      tests/test_define_counter.py -q`, `ruff check` clean. Commit.

## 7. S6 — `verify.py` (729) → `verify_review.py` + `verify_tooling.py` + `verify_acceptance.py`

Move: `_collect_source_files`, `_build_review_context`,
`_parse_review_result`, `_write_review_report` → `verify_review.py`;
`_run_test_infrastructure`, `_find_venv_python` → `verify_tooling.py`;
`_run_acceptance_tests` → `verify_acceptance.py`.
Stay: `verify_node` (gate logic per Decision 2, `verify_status` write,
`increment_loop`), the LLM review call site.

- [ ] 6.1 Seam tests: `_parse_review_result` (JSON shape parsing),
      `_find_venv_python` (tmp venv dirs), `_run_acceptance_tests`
      (tmp project with a passing/failing check, timeout bound) — all
      without LLM/checkpointer monkeypatch.
- [ ] 6.2 Create the 3 siblings; `verify.py` re-exports; verify
      `tests/test_verify_acceptance.py` and `tests/test_w2_wayforward.py`
      pass; `tests/test_w3_behavioral.py` (hang file — run in a normal
      env if available, else document).
- [ ] 6.3 Verify: `pytest tests/test_verify_acceptance.py
      tests/test_w2_wayforward.py -q`, `ruff check` clean. Commit.

## 8. S7 — `openhands_build.py` (725) → `openhands_client.py` + `openhands_report.py` + `openhands_prompt.py` + `openhands_merge.py`

Move: `_create_conversation`, `_poll_conversation` (+ gateway cfg
plumbing) → `openhands_client.py`; `_parse_build_report` +
`BuildReportMissingError` + rel_path sanitization →
`openhands_report.py`; `_build_prompt` (+ advisory ARCKIT / review-
supplements / failing-acceptance-id block assembly) →
`openhands_prompt.py`; `_merge_results`, `_write_generated_files`,
`_run_local_subgraph` dispatch → `openhands_merge.py`.
Stay: `openhands_build_wrapper`, `openhands_build_proxy_factory`, the
retry-counter increment (E1), `BuildReportMissingError` raise site.
`BuildReportMissingError` is re-exported from both
`openhands_report.py` and `openhands_build.py` (the exception is
catchable from either).

- [ ] 7.1 Seam tests: `_parse_build_report` (valid/missing/invalid
      manifest → dict / None / raise), `_build_prompt` byte-snapshot
      (pins the advisory blocks), rel_path traversal rejection — all
      importing only `graph.nodes.openhands_report` /
      `graph.nodes.openhands_prompt`.
- [ ] 7.2 Create the 4 siblings; `openhands_build.py` re-exports;
      verify `tests/test_w2_wayforward.py`,
      `tests/test_openhands_poll_terminal.py`,
      `tests/test_build_arckit_context.py`,
      `tests/test_build_subgraph_d1.py` pass.
- [ ] 7.3 Verify: the 4 suites + `ruff check` clean. Commit.

## 9. S8 — `plan.py` (932) → `plan_diagrams.py` + `plan_confidence.py`

Move: `_generate_diagram`, `_generate_all_diagrams`,
`_convert_diagrams_to_png`, `_get_diagram_skill`,
`_load_local_diagram_skill`, `_extract_use_cases`, `_slugify` →
`plan_diagrams.py` (the diagram LLM calls stay at the
`plan_node` gather site; the *generation* of the diagram prompt + the
PNG subprocess is the seam; if `_generate_diagram` itself calls
`invoke_skill`, it stays in `plan.py` — finalize at implementation and
record the ruling in the commit); `_estimate_arch_uncertainty`,
`_load_feedback_context`, `_build_diagram_context`,
`_generate_solution_md` → `plan_confidence.py`.
Stay: `plan_node`, the parallel diagram `asyncio.gather`, None-coercion,
counter increment.

- [ ] 8.1 Seam tests: `_extract_use_cases` (W4), `_slugify`,
      `_estimate_arch_uncertainty`, `_convert_diagrams_to_png` with a
      stubbed mermaid binary (tmp dir) — import from the new siblings;
      keep existing `tests/test_plan_sequence_view.py` imports working
      via re-export, then re-point its `from graph.nodes.plan import …`
      to the sibling in this task (import lines only, no body edits).
- [ ] 8.2 Create siblings; `plan.py` re-exports; run
      `tests/test_plan_sequence_view.py` + `tests/test_w2_wayforward.py`.
- [ ] 8.3 Verify: both suites pass, `ruff check` clean. Commit.

## 10. S9 — `discover.py` (1137) → `discover_scan.py` + `discover_prefill.py` + `discover_interview.py`

Move: `_scan_codebase`, `_inventory_tree`, `_detect_project_type`,
`_detect_framework`, `_discover_routes`, `_discover_models`,
`_discover_templates`, `_discover_dependencies`, `_get_git_status`,
`_get_docker_status`, `_discover_specs`, `_collect_plain_docs` →
`discover_scan.py`; `_extract_doc_prefill` + `_DOC_PREFILL_MAX_CHARS` →
`discover_prefill.py`; `_generate_interview_questions`, `_refine_idea`,
`_build_context`, `_generate_requirement_template`,
`_load_improve_telemetry` → `discover_interview.py`.
Stay: `discover_node` (the two `interrupt()` calls, ArcKit pre-scan,
auto-approve branch, HIL counter E12, LLM calls, audit/writer).

- [ ] 9.1 Seam tests: each scanner on tmp trees (routes/models/templates
      per project_type), `_get_git_status`/`_get_docker_status` with
      stubbed `subprocess`, `_extract_doc_prefill` on fixture doc dirs —
      no LLM/checkpointer monkeypatch.
- [ ] 9.2 Create the 3 siblings; `discover.py` re-exports all moved
      names (existing `tests/test_discover.py` imports
      `_detect_project_type`, `_inventory_tree`, `_discover_routes`,
      `_discover_dependencies`, … from `graph.nodes.discover` — the
      re-exports keep them passing with zero test edits).
- [ ] 9.3 Verify: `pytest tests/test_discover.py
      tests/test_discover_docs_prefill.py
      tests/test_discover_arckit.py` (the last is a hang file in this
      sandbox — run in a normal env or document) +
      `tests/test_arckit_p1.py`/`tests/test_arckit_tier2.py`; `ruff
      check` clean. Commit.

## 11. S10 — `build_subgraph_legacy.py` (1496) → `build_legacy_nodes.py` + `build_legacy_superapp.py`

Move: the 11 legacy subgraph node functions (`impl_plan_node`,
`create_backlog_node`, `implement_node`, `unit_test_node`,
`int_test_node`, `seed_node`, `deploy_gate_node`, `uat_node`,
`security_review_node`, `code_review_node`, `security_gate_node`) +
`BuildSubState` → `build_legacy_nodes.py`; the 3 SuperApp runners
(`_run_superApp_agent`, `_run_superApp_scripted`,
`_run_llm_uat_fallback`) → `build_legacy_superapp.py`.
Stay in `build_subgraph_legacy.py`: `build_input_mapping`,
`build_output_mapping`, `route_build`, `build_subgraph`,
`get_compiled_subgraph`, `build_subgraph_node` (the wiring that
imports the moved functions).

- [ ] 10.1 Seam tests: `route_build` (4 paths, mirroring the W2 VERIFY
      path tests), `build_output_mapping` — import the module directly;
      `uat_node` SuperApp-runner seams: `_run_superApp_scripted` with a
      tmp `data/test_results.json` fixture (no network).
- [ ] 10.2 Create the 2 siblings; `build_subgraph_legacy.py` re-exports
      `BuildSubState` and the node functions; verify
      `tests/test_build_subgraph_d1.py`, `test_build_subgraph_d2.py`,
      `test_build_subgraph_d3.py`, `test_build_subgraph_d5.py` pass
      (`import graph.nodes.build_subgraph_legacy as bg` — the
      re-exports keep `bg.impl_plan_node` etc. valid).
- [ ] 10.3 Verify: the 4 suites + `ruff check` clean. Commit.

## 12. S11 — docs + gate close-out

- [ ] 11.1 Update `AGENTS.md` "Code Structure" table: add the sibling
      modules to the `graph/nodes/` row.
- [ ] 11.2 Update `openspec/specs/repo-structure/spec.md` layout table
      (the `graph/nodes/` row) to list the new sibling modules; note the
      "sibling imported only by its owning node or by tests" rule.
- [ ] 11.3 Run the full gate: `pytest tests/ -q` with the 7 hang files
      `--ignore`d and the 9 `test_health` socket tests `--deselect`ed →
      0 failures; `ruff check .` clean. Record the numbers.
- [ ] 11.4 Final commit: docs + gate results.

**Gate note (sandbox):** in the sandboxed agent env the 7 hang files are
run individually with a `timeout` (per AGENTS.md "Environment-Flake &
Sandbox Caveats"); the 9 socket tests are deselected. In a normal env /
CI, the full `pytest tests/ -q` is the gate.
