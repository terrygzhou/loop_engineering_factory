# Tasks: skill-map-arckit-fit

## 1. Fix `PHASE_SKILL_MAP.md` drift (doc-only)

**Files:**
- Modify: `skills/PHASE_SKILL_MAP.md`
- Test: none (doc change; verified by reading against `graph/nodes/*.py` skill lookups)

Steps:
1. DISCOVER section: replace the 3-row table with the actual DISCOVER skill
   lookups: `fabric-prompts` ✅, `coding-principles` ✅, `idea-refine` ✅
   (verified: `graph/nodes/discover.py` `skills.get("fabric-prompts")` L742,
   `skills.get("coding-principles")` L745, `skills.get("idea-refine")` L1070).
   Remove `interview-me` and `context-engineering` rows (never called).
2. REFLECT section: replace the 2 📦 rows with `git-workflow` ✅
   (verified: `graph/nodes/reflect.py` L310 `skills.get("git-workflow")`).
3. SHIP section: change `git-workflow-and-versioning` 📦 row to `git-workflow` ✅
   (verified: `graph/nodes/ship.py` L158 `skills.get("git-workflow")`).
4. Coverage Summary: update counts to reflect the corrected rows.
5. Wiring Priority: remove `context-engineering` / `debugging-and-error-recovery`
   entries that claim DISCOVER/SEED_DATA/VERIFY wiring that doesn't exist in code.

## 2. Consolidate ArcKit advisory block into a shared helper, feed `arckit_product_backlog` into PLAN

**Files:**
- Modify: `graph/nodes/define.py` — extract `_arckit_advisory_context` logic into `tools/arckit_context.py`
- Create: `tools/arckit_context.py` — `arckit_advisory_block(state) -> str` returning "" when no ArcKit advisory keys are set, else a consolidated header + JSON
- Modify: `graph/nodes/plan.py` — add `arckit_product_backlog` to the advisory block (via the shared helper), append to `context_parts` when non-empty
- Test: `tests/test_arckit_context.py` (new)

Steps:
1. Create `tools/arckit_context.py`:
   ```python
   def arckit_advisory_block(artifacts: dict, max_chars: int = 4000) -> str:
       """Return a consolidated advisory block for any ArcKit keys present in artifacts.
       Returns "" when no advisory keys are set. Caps total JSON by max_chars."""
   ```
   Keys it checks: `arckit_product_backlog`, `arckit_strategy_waves`,
   `arckit_integration_standards`, `arckit_nfr_constraints`,
   `arckit_security_controls`, `arckit_data_model`.
   Each key present and non-empty → one `## <KEY_NAME>` section with the JSON.
   Total output capped at `max_chars`.
2. Refactor `graph/nodes/define.py::_arckit_advisory_context` to call
   `arckit_advisory_block` (delete the inline logic).
3. In `graph/nodes/plan.py` context_parts construction (~L84–92), call
   `arckit_advisory_block(state.get("artifacts", {}))` and append to
   `context_parts` when non-empty. Byte-identical when no ArcKit keys set.
4. Test file `tests/test_arckit_context.py`:
   - `test_block_empty_when_no_keys`: call with `{}` → `""`
   - `test_block_includes_backlog_when_set`: seed `artifacts["arckit_product_backlog"]` → block contains `## arckit_product_backlog`
   - `test_block_caps_at_max_chars`: seed large JSON → output ≤ max_chars
   - `test_plan_prompt_includes_backlog_when_set`: monkeypatch `invoke_skill`;
     seed `arckit_product_backlog`; assert `## PRODUCT BACKLOG` in captured context
   - `test_plan_prompt_unchanged_when_absent`: no keys → byte-identical context
5. Run: `pytest tests/test_arckit_context.py -q` → green.

## 3. Remove dead `spec_text` parameter from `build_executor_state` (review finding I-1)

**Files:**
- Modify: `graph/executor.py` — remove `spec_text: str = ""` from `build_executor_state` signature (L142) and from the `WorkflowState(...)` call
- Test: `tests/test_executor.py` (new or existing — add test if none exists)

Steps:
1. Remove `spec_text: str = ""` from `build_executor_state` signature.
   Remove the `spec_text=spec_text` kwarg from the `WorkflowState(...)` call
   (P0-A1 already removed it from the schema; this is the residual).
2. Remove `spec_text: str = ""` from `run_interactive` signature (L242) and
   from the `build_executor_state(...)` call inside it.
3. Remove `spec_text=spec_text` from `build_executor_state(...)` call at L259.
4. Update any callers that pass `spec_text` — grep for `build_executor_state(`
   and `run_interactive(` to find all call sites.
5. Test: add `tests/test_executor.py::test_build_executor_state_has_no_spec_text`
   asserting the function signature does not include `spec_text` (via
   `inspect.signature`), and that calling `build_executor_state(cycle_id="1",
   project_name="x")` works without error.
6. Run: `pytest tests/test_executor.py -q` → green.

## 4. Close-out gate

- Full gate per AGENTS.md (7 hang files `--ignore`, 9 health socket tests
  `--deselect`) → 0 new failures vs baseline.
- `ruff check .` clean.
