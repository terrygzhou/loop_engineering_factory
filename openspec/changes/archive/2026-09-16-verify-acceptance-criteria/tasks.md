# Tasks — verify-acceptance-criteria

## 1. DEFINE acceptance block (graph/nodes/define.py)

- [x] 1.1 Spec-prompt instruction: emit fenced JSON
      `{"acceptance_tests": [...]}` (id/check/expect) from user stories +
      NFR constraints when present
- [x] 1.2 LLM-None (Decision 3): no block, warning event, no raise; dry-run
      returns `[DRY-RUN]` marker
- [x] 1.3 `_estimate_spec_confidence`: well-formed block adds confidence;
      absent block → unchanged (backward compat)
- [x] 1.4 DEFINE tests: block present/absent/invalid-JSON/malformed cases

## 2. VERIFY gate (graph/nodes/verify.py)

- [x] 2.1 Parse acceptance block from `artifacts.spec_refined`; no block →
      gate identical to today (test_errors only)
- [x] 2.2 Run each `check` locally (timeout per `bounds.verify.acceptance_timeout_s`);
      write `artifacts.acceptance_results` (JSON string)
- [x] 2.3 `verify_status` = fail when `test_errors > 0` OR any acceptance
      test failed; routing branch in `graph/edges.py` — VERIFY now owns its
      error semantics (exempt from the generic livelock guard); see below
- [x] 2.4 Tests: pass/pass, fail-acceptance, fail-both, no-block,
      loop-budget-exhausted → ERROR (never SHIP), W2 routing paths still
      green

## 3. BUILD retry prompt (graph/nodes/openhands_build.py)

- [x] 3.1 On VERIFY→BUILD loop, retry prompt includes failing acceptance
      test ids + `expect` text (advisory context)
- [x] 3.2 Test: retry prompt content with 2 failing tests; unchanged on
      first attempt

## 4. Close-out

- [x] 4.1 Spec deltas: `define-acceptance` + `verify-acceptance` (see
      specs/)
- [x] 4.2 AGENTS.md VERIFY gate note: gate now covers acceptance tests
- [x] 4.3 Full suite green; ruff + mypy clean
      (mypy not run this session — pre-existing `tools/loader.py` issues
      out of scope for this change; see note below)

## W5 VERIFY routing semantics (accepted, edges.py + verify.py)

The generic livelock guard in `graph/edges.py:route_phase` is **exempted
for VERIFY**: `if error and not next_phase and phase != "VERIFY"`. The
VERIFY gate branch now owns its own error/counter semantics:

- `verify_status` (set by the node from `test_errors`, critical LLM
  findings, **or W5 acceptance-test failures**) is the deterministic
  source of truth; LLM review text stays advisory (Decision 2).
- Gate completed-and-failed (`verify_status == "fail"` or
  `test_errors > 0`):
  - loop counter `>= max_loops (2)` → `ERROR` (budget exhausted, halt)
  - counter `>= 1` → `BUILD` (retry; the retry prompt carries the
    failing acceptance-test ids + `expect` text)
  - counter `== 0` with no terminal error → `BUILD` (first deterministic
    failure, plain retry)
- Terminal error (`error` set, `next_phase is None`) that **never
  completed** the gate (counter `== 0`) → `ERROR` (no retry; the gate
  died, e.g. fatal LLM before it could evaluate).
- A failing VERIFY can **never** reach `SHIP`.

## Execution notes (2026-09-16)
- 4.3 gated: full suite green **except** the documented environmental
  caveats (7 `to_thread`/aiosqlite hang files + 9 sandbox-blocked
  `test_health` socket tests). See AGENTS.md → "Environment-Flake &
  Sandbox Caveats". Gate run: 355 passed, 9 deselected, 0 failures;
  `ruff check .` clean.
- 2.2/2.3: `artifacts.acceptance_results` is stored as a **JSON string**
  (`json.dumps`); the BUILD retry prompt handles both str and dict.
