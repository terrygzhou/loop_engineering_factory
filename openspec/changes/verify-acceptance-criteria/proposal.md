# Change: acceptance tests as VERIFY's deterministic target

## Why

Decision 2 makes VERIFY a deterministic gate on `test_errors` — but today
"done" is whatever the build agent happened to test. The factory has no
machine-checkable definition of *what the software must do*, so the gate
verifies effort, not correctness. Two fixes, one change:

1. **DEFINE** (Lane B, `graph/nodes/define.py`): the spec generation gains a
   machine-checkable **acceptance-test block** — a structured
   ```json
   {"acceptance_tests": [{"id": "AT-01", "check": "<test command or predicate>", "expect": "..."}]}
   ```
   fenced block, derived from the spec's user stories + NFR constraints
   (`arckit_nfr_constraints` when set, per `arckit-build-context`). This is
   Lane B: the tests are *generated*, not human-provided; human input enters
   via ARCH_REVIEW `answers` when NFRs are missing.
2. **VERIFY** (`graph/nodes/verify.py`): the gate runs the acceptance tests
   in addition to `test_errors`; `verify_status` reflects both, and a
   failing retry loop carries the failing test ids into the BUILD retry
   prompt. Routing semantics unchanged: fail → BUILD (max 2 loops) →
   ERROR, never SHIP (Decision 2 preserved exactly).

## What changes

- DEFINE: LLM spec prompt gains the acceptance-test block instruction;
  `_estimate_spec_confidence` counts a well-formed block (absent block →
  no penalty, backward compatible). LLM-None path (Decision 3) coerces to
  no block + warning, never raises.
- VERIFY: parses the block from `artifacts.spec_refined`; runs each
  `check` (bounded, timeout per `bounds`); writes
  `artifacts.acceptance_results` = per-test pass/fail; `verify_status`
  fails if `test_errors > 0` OR any acceptance test failed. Retry prompt
  (BUILD loop) lists failing test ids + `expect` text.
- No new HIL gate, no new phase, no routing change (`route_phase` VERIFY
  branch untouched — `verify_status` already drives it).

## Non-goals

- No change to Decision 2's loop budget (max 2) or ERROR halt.
- No new LLM provider/model.
- Acceptance `check` commands are sandbox-executed inside the built
  project; arbitrary network checks are out of scope (local test/predicate
  commands only).
- No VERIFY change when the spec has no acceptance block: gate behaves
  exactly as today (`test_errors` only).

## Impact

- New capability specs: `define-acceptance` (DEFINE requirement),
  `verify-acceptance` (VERIFY gate requirement).
- `llm-invocation` delta: acceptance-test generation goes through
  `invoke_skill_async` (parallel with the existing DEFINE calls) or the
  same call chain — no new LLM path.
- Code: `graph/nodes/define.py`, `graph/nodes/verify.py`,
  `graph/nodes/openhands_build.py` (retry-prompt inclusion of failing
  ids), tests: `tests/test_w2_wayforward.py` (VERIFY routing paths stay
  green) + new `tests/test_acceptance_gate.py`.
- Wave order: independent of `arckit-build-context`/`plan-sequence-view`
  (works on plain spec text); NFR sharpening comes free when
  `arckit_nfr_constraints` lands.
