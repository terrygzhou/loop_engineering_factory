# EYW-184 — ARCH_REVIEW Safety Interlocks (Loop Factory)

**Status:** Implemented & tested
**Parent report:** EYW-178 P2-4
**Spec:** EYW-171 §7.3 / §7.4 / §8 (ACHG–ARCH_REVIEW interaction)
**Data contract:** `Eywalink/Architecture/EYW-171-data-contract-arckit-loopfactory-discover.md`
**Date:** 2026-08-22

## Summary

ARCH_REVIEW is the human-in-the-loop gate where an agent's generated
architecture/plan/spec is approved before BUILD consumes it. Two safety gaps
were closed, both config-aware and fail-safe:

1. **ACHG pending-state interlock** — while any ArcKit Architecture Change
   Request (ACHG) has a PENDING board decision, ARCH_REVIEW **must not
   auto-approve** (headless CLI or web bridge). It halts for an explicit
   human decision and surfaces the in-flight change to the reviewer.
2. **px_evaluator quality gate** — for regulated workloads (config-flagged),
   a plain "approve" is **blocked** when the spec/plan quality scores fall
   below threshold. Re-approval requires an explicit `override: true` from a
   human. When the evaluator is unavailable the gate is **fail-closed**.

Both interlocks also make the reject-loop observable: a reject bumps
`loop_counts["ARCH_REVIEW"]` and feeds the reviewer's findings back into the
re-plan, and after 2 rejections the existing livelock guard in `route_phase`
forces forward to BUILD.

## Deliverables

| # | File | Change |
|---|------|--------|
| 1 | `graph/achg_scanner.py` | **New.** Parses ArcKit ACHG docs into the `achg_context` payload (EYW-171 §8.1). Classifies board status (PENDING/APPROVED/REJECTED/CONDITIONAL); latest version wins per `(project, change)`. |
| 2 | `service/px_gate.py` | **New.** `PxGate` wraps the px_evaluator: `evaluate_review_gate()` → `GateResult` with `passed`, per-threshold `failures`, `evaluator_available`. Fail-closed when the evaluator is absent or errors. |
| 3 | `config/guardrails.yaml` | **New section** `arch_review_gate` (`enabled: false`, `min_spec_quality: 0.8`, `min_plan_score: 0.8`, `fail_closed: true`). Regulated-workload flag. |
| 4 | `config/guardrails.py` | `get_arch_review_gate()` accessor (defaults merged with the YAML section). |
| 5 | `graph/nodes/review.py` | Auto-approve branch now **checks for PENDING ACHGs** and falls through to the HIL interrupt instead of auto-approving. The interrupt payload carries `achg_context` + `px_gate` + human-readable warnings. The px gate converts a plain approve to a reject (findings → PLAN) unless `override: true`. Rejects persist `loop_counts["ARCH_REVIEW"]` + `user_review_comments`. |
| 6 | `graph/nodes/plan.py` | Consumes `user_review_comments`: prepends an "ARCH_REVIEW Rejection Feedback" block to the re-plan context so the reviewer's findings are actually addressed. |
| 7 | `graph/executor.py` | Headless CLI `_hil_cli`: auto-approve is suppressed for ARCH_REVIEW when a PENDING ACHG is in flight (emits a BLOCKED warning, defers to manual input). |
| 8 | `frontend/backend/workflow_bridge.py` | Web bridge `_handle_hil`: auto-approve suppressed for ARCH_REVIEW with a PENDING ACHG; the 30-minute timeout no longer auto-approves in that case (keeps waiting). |
| 9 | `tests/test_arch_review_interlocks.py` | **New.** 25 tests: ACHG scanner data-contract, px_gate thresholds/fail-closed, review-node interlocks (unit), and end-to-end reject-loop through the compiled graph (reject → PLAN with feedback → force-forward to BUILD after 2 rejects; gate-blocks-approve → override-unblocks). |

## Design decisions

- **Fail-safe direction.** Every ACHG-pending check *blocks* rather than
  *approves*. If the scanner raises or the context is missing, the safe
  default is to **not** auto-approve for ARCH_REVIEW when we *know* a PENDING
  ACHG exists; an empty/unknown context does not fabricate a pending state.
- **Config flag, off by default.** `arch_review_gate.enabled: false` keeps
  existing (non-regulated) flows unchanged. Regulated workloads opt in by
  flipping the flag in `config/guardrails.yaml`.
- **Fail-closed gate.** `fail_closed: true` (default): if px_evaluator is
  unavailable or errors, the gate reports failure and a plain approve is
  converted to a reject — a human must explicitly `override`.
- **Override is explicit and auditable.** `{"approved": true, "override":
  true}` is the only way past a failed gate; the approval path records
  `px_gate_result` and `achg_context` in `artifacts` for the audit log.
- **Reuses ArcKit parsing.** `graph/achg_scanner.py` builds on
  `tools/arckit_loader.py` (`parse_md_table`, `find_section`,
  `split_sections`) so ACHG field extraction stays consistent with the
  rest of the factory's doc parsing.

## Verification

```
python3 -m pytest tests/test_arch_review_interlocks.py -q
# 25 passed

python3 -m pytest tests/ -q -m "not integration"   # full suite
# 182 passed, 26 deselected
python3 -m pytest tests/ -q -m integration
# 26 passed
```

Frontend bridge import check: `frontend/backend/workflow_bridge.py` imports
`graph.achg_scanner` cleanly.

## Test coverage map (EYW-178 P2-4)

- **ACHG data-contract tests** — scanner classification, project filter,
  latest-version-wins, placeholder/conditional board status, empty root.
- **Reject-loop tests** — end-to-end: reject #1 → PLAN re-runs *with*
  `user_review_comments`; reject #2 → `route_phase` forces BUILD; approve →
  BUILD with no re-plan.
- **px_evaluator gate** — disabled passes; passing/low/boundary scores;
  fail-closed & fail-open on unavailability; eval-error treated as
  unavailable; gate blocks plain approve, `override` unblocks (unit + e2e).

## Open items / follow-ups

- **Regulated-workload detection is manual** (flip
  `arch_review_gate.enabled`). A future ticket can auto-enable the gate when
  the project's ArcKit profile marks the workload as regulated/enterprise.
- **ACHG live re-scan on every timeout** in the web bridge re-reads disk;
  cheap now, but could be cached with a TTL if ACHG trees grow large.
- `tests/` is gitignored in this repo (`.gitignore:49`), so the new test file
  lives in the working tree alongside the existing suite — consistent with
  the project's current convention.
