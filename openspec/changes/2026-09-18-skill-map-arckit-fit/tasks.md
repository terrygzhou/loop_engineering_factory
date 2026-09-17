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

## 2. Feed `arckit_product_backlog` into PLAN task-breakdown prompt

**Files:**
- Modify: `graph/nodes/plan.py` (context_parts construction, ~L84–92)
- Test: `tests/test_plan_arckit_backlog.py` (new)

Steps:
1. In `graph/nodes/plan_node()` context construction, after the interview
   append, add an advisory block when
   `state.get("artifacts", {}).get("arckit_product_backlog")` is set and non-empty:
   ```
   ## PRODUCT BACKLOG (advisory — from ArcKit OAPR; use to constrain task ordering)
   <json>
   ```
   Cap the JSON by `bounds.context.arckit_advisory_max_chars` (existing bound,
   default 4000) — same cap used by `_arckit_advisory_context` in
   `graph/nodes/define.py:45-60`.
2. When the key is absent or empty: `context_parts` is byte-identical to
   today's (no new block) — test this explicitly.
3. Test file `tests/test_plan_arckit_backlog.py`:
   - `test_plan_prompt_includes_backlog_when_set`: monkeypatch
     `invoke_skill` to capture context; seed `artifacts["arckit_product_backlog"]`
     with a small JSON; assert the captured context contains the block header
     `## PRODUCT BACKLOG` and the backlog JSON.
   - `test_plan_prompt_unchanged_when_backlog_absent`: same setup without the
     key; assert the block header is NOT in the captured context and the
     context matches the pre-change baseline (spec + interview only).
4. Run: `pytest tests/test_plan_arckit_backlog.py tests/test_plan.py tests/test_w2_wayforward.py -q` (plan.py
   has existing coverage in `test_w2_wayforward.py`? check — use whichever
   plan tests exist) → 0 new failures.

## 3. Feed `arckit_data_model` into SEED_DATA seed prompt

**Files:**
- Modify: `graph/nodes/build_subgraph_legacy.py` `_seed_data_node`
  (the `context = spec_text + data_models + api_specs` construction, ~L648–654)
- Test: `tests/test_seed_data_arckit.py` (new)

Steps:
1. When `state.get("artifacts", {}).get("arckit_data_model")` is set and
   non-empty, append to the seed prompt context:
   ```
   \n\nArcKit DATA model (advisory — prefer these entities/classification scheme):
   <json>
   ```
   No cap needed here (the seed prompt is a single local LLM call, not a
   parallel fan-out; the DATA model JSON is bounded by the ArcKit loader's
   own size limits).
2. When absent: context is byte-identical to today's.
3. Test file `tests/test_seed_data_arckit.py`:
   - `test_seed_prompt_includes_data_model_when_set`: monkeypatch
     `invoke_skill`; seed `artifacts["arckit_data_model"]`; assert header
     present in captured context.
   - `test_seed_prompt_unchanged_when_data_model_absent`: assert header absent.
4. Run: `pytest tests/test_seed_data_arckit.py -q` → green.

## 4. Close-out gate

- Full gate per AGENTS.md (7 hang files `--ignore`, 9 health socket tests
  `--deselect`) → 0 new failures vs baseline.
- `ruff check .` clean.
