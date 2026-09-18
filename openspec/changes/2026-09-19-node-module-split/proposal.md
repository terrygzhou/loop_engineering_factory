# Change: Split the LangGraph node modules into small, individually testable modules

## Why

The phase nodes in `graph/nodes/` have grown into monoliths that mix four
concerns in one file: HIL/LLM orchestration, filesystem scanning, prompt
construction, and result parsing. Line counts:

| File | Lines | Mixed concerns |
|------|-------|----------------|
| `build_subgraph_legacy.py` | 1496 | subgraph wiring + 11 nodes + 3 SuperApp runners |
| `discover.py` | 1137 | 2 HIL interrupts + ArcKit pre-scan + doc prefill + 12 filesystem scanners + 3 LLM calls |
| `plan.py` | 932 | plan generation + 4 parallel diagram LLM calls + Mermaid→PNG conversion + use-case extraction |
| `verify.py` | 729 | gate logic + LLM review + pytest/ruff/mypy runs + acceptance-test runner |
| `openhands_build.py` | 725 | gateway API client + prompt builder + report parser + local fallback + result merge |
| `define.py` | 653 | 2 parallel LLM calls + spec confidence + feedback context + ArcKit advisory |
| `review.py` | 462 | HIL gate + JSON artifact parsing + ACHG context + missing-build-inputs |
| `reflect.py` | 436 | cycle recording + config-diff generation + skill review + HIL gate |

Consequences today:

1. **No individual testability.** A test of "does `_parse_build_report`
   validate the schema?" must import the whole 725-line module and mock the
   gateway client. A test of "does the prefill extractor trim questions?"
   must import `discover.py` with its `interrupt()`/httpx/LLM surface.
2. **Unbounded coupling.** New helper in a node file = one more import
   pulled into every test that touches that module; pure helpers and I/O
   helpers share a module namespace and cannot be linted apart.
3. **Review friction.** A 1137-line node file makes diff review unreliable;
   behavioral changes hide among scanner tweaks.

The graph *core* (`main.py` 113, `edges.py` 195, `state.py` 131,
`runner.py` 494, `checkpointer.py` 131) is already small and well-tested
(`test_edges.py`, `test_workflow_lifecycle.py`, `test_checkpointer.py`,
`test_runner_hil_loop.py`). This change targets only `graph/nodes/*`.

## What Changes

Introduce a **seam rule** and apply it to every node file:

**Seam rule.** A function is *pure-ish* and moves to a sibling module when
ALL of the following hold:

1. No `interrupt()` / `asyncio.gather` of LLM calls / `httpx` / subprocess
   network in its body (filesystem reads/writes allowed — they are
   deterministic and monkeypatchable).
2. No `invoke_skill` / `invoke_skill_async` call.
3. No `logging`/audit writes that the function's caller does not itself own.
4. Signatures are stateless (no module-level mutable state, no config
   reads at call time that the caller doesn't already do).

What stays in the node file: the public `*_node` entry point, the HIL
`interrupt()` call sites, LLM orchestration (parallel calls, None-coercion
per Decision 3), audit/writer emissions, and the partial-update delta
construction (the E1 `increment_loop` contract).

**Layout (Option A — thin-node siblings, no `graph/phases/` move):**

New modules live next to the node file in `graph/nodes/` and are imported
by the node file. Public import surface is unchanged: `graph/main.py`,
`graph/runner.py`, and every test keep importing `discover_node`,
`verify_node`, etc. from the same module. Existing tests that reference
private helpers (`_parse_build_report`, `_extract_use_cases`, …) are
re-pointed to the new sibling module with `from graph.nodes.<mod> import _`
updates; the private name is unchanged so no test-body rewrites.

Per-file target shape (helpers grouped by concern; exact grouping
finalized in tasks.md per file):

- `discover.py` → `discover_scan.py` (`_scan_codebase`,
  `_inventory_tree`, `_detect_project_type`, `_detect_framework`,
  `_discover_routes/models/templates/dependencies`, `_get_git_status`,
  `_get_docker_status`, `_discover_specs`, `_collect_plain_docs`),
  `discover_prefill.py` (`_extract_doc_prefill`, `_DOC_PREFILL_MAX_CHARS`),
  `discover_interview.py` (`_generate_interview_questions`,
  `_refine_idea`, `_build_context`, `_generate_requirement_template`,
  `_load_improve_telemetry`)
- `plan.py` → `plan_diagrams.py` (`_generate_diagram`,
  `_generate_all_diagrams`, `_convert_diagrams_to_png`,
  `_get_diagram_skill`, `_load_local_diagram_skill`,
  `_extract_use_cases`, `_slugify`), `plan_confidence.py`
  (`_estimate_arch_uncertainty`, `_load_feedback_context`,
  `_build_diagram_context`, `_generate_solution_md`)
- `verify.py` → `verify_review.py` (`_collect_source_files`,
  `_build_review_context`, `_parse_review_result`, `_write_review_report`),
  `verify_tooling.py` (`_run_test_infrastructure`, `_find_venv_python`),
  `verify_acceptance.py` (`_run_acceptance_tests`)
- `openhands_build.py` → `openhands_client.py` (`_create_conversation`,
  `_poll_conversation`, gateway cfg plumbing),
  `openhands_report.py` (`_parse_build_report`, `BuildReportMissingError`,
  rel_path sanitization), `openhands_prompt.py` (`_build_prompt`),
  `openhands_merge.py` (`_merge_results`, `_write_generated_files`,
  `_run_local_subgraph` dispatch)
- `define.py` → `define_prompts.py` (`_build_spec_context`,
  `_arckit_advisory_context`, `_load_feedback_context`),
  `define_confidence.py` (`_estimate_spec_confidence`)
- `review.py` → `review_payload.py` (`_parse_json_artifact`,
  `_missing_build_inputs`, `_resolve_achg_context`, `_extract_task_breakdown`,
  `_spec_summary`)
- `reflect.py` → `reflect_skill_review.py` (the skill-review step +
  persistence), `reflect_diffs.py` (config-diff generation)
- `build_subgraph_legacy.py` → `build_subgraph_legacy.py` keeps the
  subgraph wiring (`build_subgraph`, `build_input/output_mapping`,
  `route_build`); node functions move to `build_legacy_nodes.py`
  (`impl_plan_node` … `security_gate_node`), SuperApp runners to
  `build_legacy_superapp.py` (`_run_superApp_agent`,
  `_run_superApp_scripted`, `_run_llm_uat_fallback`)
- `seed_data.py` (115 lines) and `ship.py` (282 lines): no split — below
  the threshold; `ship.py` gains only test seams if needed.

**Non-goals (explicit):**

- No `graph/phases/` package, no re-pointing of `graph/main.py` imports,
  no rename of any `*_node` entry point.
- No behavior changes: node outputs, state keys, interrupt payloads,
  LLM prompt text, and error types are byte-identical before/after.
  The byte-identity guarantee is pinned by the existing
  `test_discover_docs_prefill.py` and prompt-snapshot tests; any change
  that alters prompt bytes fails the gate.
- No new runtime dependencies; no import-linter enforcement in this
  change (that is the follow-up if a `graph/phases/` split ever happens).
- `build_subgraph_legacy.py` keeps its "legacy" status; we only split,
  not modernize.

## Capabilities

### New Capabilities
- `node-module-seams` (new spec: the seam rule, the per-file sibling
  layout, the test-seam convention, and the no-behavior-change guarantee)

### Modified Capabilities
- `repo-structure`: the `graph/nodes/` directory table gains the new
  sibling modules; the layout requirement's "graph/nodes/" row is amended.

## Impact

- **Code:** `graph/nodes/*.py` — 8 files split into ~16 sibling modules;
  node files shrink to orchestration only.
- **Tests:** existing helper-import re-pointing in ~15 test files
  (import lines only, no body changes); new seam tests in
  `tests/test_node_seams.py` covering the moved pure helpers with no
  LLM/network/config monkeypatching at all.
- **Docs:** AGENTS.md "Code Structure" table + repo-structure spec
  updated with the sibling layout.
- **Gate:** AGENTS.md close-out command — `pytest tests/ -q` with the 7
  hang files `--ignore`d and the 9 `test_health` socket tests
  `--deselect`ed → 0 failures; `ruff check .` clean.
