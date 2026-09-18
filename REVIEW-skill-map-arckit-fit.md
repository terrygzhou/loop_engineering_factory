# Final review — `2026-09-18-skill-map-arckit-fit` (SDD, 2026-09-18)

Scope: OpenSpec change `openspec/changes/2026-09-18-skill-map-arckit-fit`
(4 tasks: PHASE_SKILL_MAP.md drift fix, ArcKit advisory consolidation into
`tools/arckit_context.py` + PLAN backlog consumption, dead `spec_text`
parameter removal, close-out gate). Executed via SDD workflow on main
(no worktree) per user direction.

Commits (all on main, post-amendment `adb7c9b`):
- `424c180` — Task 1: PHASE_SKILL_MAP.md drift fix
- `996b5d8` — Task 2: advisory helper + PLAN backlog + 5 new tests
- `6a9c762` — Task 3: dead `spec_text` removal + 1 new test
- Task 4 (gate): verification-only, no commit (zero tracked changes)

Workflow: 10 agents (4 implementers, 4 task reviewers, 1 final
whole-branch reviewer, 1 gate runner). No fix rounds required — all task
reviews returned `pass` on first pass.

## Findings

0 Critical. 0 Important. 3 Minor (non-blocking, out of scope, noted for
future cleanup passes).

### Minor
- **M-1: `interview-me` live lookup at `graph/nodes/discover.py:224`.**
  Task 1 correctly removed `interview-me` from the DISCOVER map per spec,
  but a live `skills.get("interview-me", {})` lookup remains in the
  non-ArcKit interactive interview fallback path. Pre-existing code-side
  inconsistency — the lookup exists, but the skill is not in the active
  map. Follow-up candidate, not a regression.
- **M-2: `workflow_bridge._run_from_state` / `_spec_text` (L1393/L1427)
  keep their own `spec_text` parameter.** This is a separate, pre-existing
  path that feeds `state["project_description"]` — the bridge's own
  seed-into-state logic, not the dead executor passthrough. Outside
  Task 3's scope (which targets `build_executor_state` /
  `run_interactive`). Candidate for a future cleanup pass.
- **M-3: `tests/test_arckit_context.py::test_plan_prompt_unchanged_when_absent`
  hardcodes the exact rendered context string.** Accurate today but brittle
  to future `context_manager` / `plan.py` ordering changes. Acceptable for
  now; would break loudly if the rendering changes.

### Behavioral nuance (accepted, not a regression)
- DEFINE's post-refactor capping now includes the section header line inside
  the `max_chars` cap (pre-refactor capped the raw value only, then wrapped
  it in the header). The new behavior is *more conservative* (smaller
  output) and aligned with the helper's "total capped at max_chars"
  contract.

## Gate

`.venv/bin/python3 -m pytest tests/ -q` (7 hang files `--ignore`, 5
baseline out-of-scope failures `--deselect`):
**448 passed / 5 deselected / 0 new failures.**

Baseline was 442 passed; the +6 is exactly the 6 new passing tests from
Tasks 2–3 (`tests/test_arckit_context.py` ×5, `tests/test_executor.py` ×1).
No regressions. The 5 out-of-scope baseline failures remain deselected and
unfixed, as required.

`ruff check .` → `All checks passed!` (clean).

## Spec conformance

- **`specs/skill-registry/spec.md`: PASS.** DISCOVER/REFLECT/SHIP rows now
  match the code exactly (`fabric-prompts`/`coding-principles`/`idea-refine`
  / `git-workflow` / `git-workflow`). `interview-me`, `context-engineering`,
  `using-agent-skills`, `deprecation-and-migration` removed from active
  phase rows. `writing-plans` and `git-workflow-and-versioning` marked
  superseded, not deleted. No new `skills/*/SKILL.md` introduced.
- **`specs/workflow-orchestration/spec.md`: PASS.**
  `tools/arckit_context.py::arckit_advisory_block(artifacts, max_chars=4000)`
  with the six-key fixed order (`arckit_product_backlog`,
  `arckit_strategy_waves`, `arckit_integration_standards`,
  `arckit_nfr_constraints`, `arckit_security_controls`,
  `arckit_data_model`). PLAN appends via the shared helper,
  byte-identical-when-absent (tested: `test_block_empty_when_no_keys`,
  `test_plan_prompt_unchanged_when_absent`, plus marker-leak assertions).
  `define.py` delegates per-key (scoped `{key: value}`) while keeping its
  pinned two-key `## ArcKit …` headers byte-identical to pre-refactor
  (covered by the pre-existing `tests/test_define_arckit_context.py`).
  `spec_text` removed from `build_executor_state` + `run_interactive` and
  both call sites (`main.py:105`, `workflow_bridge.py:1404`); new
  `tests/test_executor.py` asserts via `inspect.signature` + direct call.
  No new top-level `artifacts` key read from a node that doesn't own it;
  no routing / Decision-2 / loop-budget change.

## Verdict

**Pass.** All 4 spec-delta requirements met. 0 Critical, 0 Important,
3 Minor (pre-existing or accepted). Safe to archive.
