"""
px_evaluator gate for the ARCH_REVIEW phase — EYW-184 (EYW-178 P2-4).

Gates ARCH_REVIEW on `px_evaluator` quality thresholds for regulated
workloads. Enabled per-configuration via the `arch_review_gate` section of
`config/guardrails.yaml` (config-flagged, default off):

    arch_review_gate:
      enabled: true
      min_spec_quality: 0.8
      min_plan_score: 0.8
      fail_closed: true

Behaviour:
- The gate evaluates the current spec-refined and plan artifacts with
  `px_evaluator.eval_spec` / `eval_plan` (the same evaluator the phases
  already use for observation scoring — this makes the score load-bearing).
- Gate fails below thresholds, or — when `fail_closed` — when the px
  evaluator is unavailable/errored. Regulated workloads must not get a
  free pass because the scoring service is down.
- A failing gate does not hard-stop the graph: approval requires an
  explicit human `override: true` in the resume payload (see
  `graph/nodes/review.py`). Plain "approve" is converted to reject with
  the gate findings fed back to PLAN.

The gate is a pure function of (config, artifacts, evaluator) — unit
testable with a mocked evaluator singleton.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

__all__ = ["GateResult", "PxGate"]


@dataclass
class GateResult:
    """Outcome of the ARCH_REVIEW px gate."""

    passed: bool
    evaluator_available: bool = True
    scores: Dict[str, float] = field(default_factory=dict)
    failures: List[str] = field(default_factory=list)

    def to_artifact(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "evaluator_available": self.evaluator_available,
            "scores": self.scores,
            "failures": self.failures,
        }


class PxGate:
    """Config-flagged quality gate over px_evaluator scores."""

    def __init__(
        self,
        enabled: bool = False,
        min_spec_quality: float = 0.8,
        min_plan_score: float = 0.8,
        fail_closed: bool = True,
    ):
        self.enabled = enabled
        self.min_spec_quality = float(min_spec_quality)
        self.min_plan_score = float(min_plan_score)
        self.fail_closed = fail_closed

    # ── helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _evaluator_available() -> bool:
        try:
            from service.evaluator import evaluator as px_evaluator
        except Exception:
            return False
        return px_evaluator is not None and bool(getattr(px_evaluator, "_available", False))

    @staticmethod
    def _score_ok(result: Any) -> bool:
        """True when the evaluator actually scored the artifact (no error)."""
        if result is None:
            return False
        rationale = str(getattr(result, "rationale", "") or "")
        return not (
            rationale.startswith("Eval error") or rationale.startswith("LLM HTTP")
        )

    # ── gate ──────────────────────────────────────────────────────────────

    def evaluate_review_gate(
        self,
        spec_text: str,
        plan_text: str,
    ) -> GateResult:
        """Evaluate the ARCH_REVIEW gate against the current artifacts.

        Gates on spec quality (foundation) and plan score (the artifact
        being approved). Disabled → always passes.
        """
        if not self.enabled:
            return GateResult(passed=True, evaluator_available=True)

        if not self._evaluator_available():
            passed = not self.fail_closed
            return GateResult(
                passed=passed,
                evaluator_available=False,
                failures=[
                    "px evaluator unavailable — "
                    + (
                        "fail_closed=true: approval requires explicit human override"
                        if self.fail_closed
                        else "fail_closed=false: treating as pass"
                    )
                ],
            )

        from service.evaluator import evaluator as px_evaluator

        failures: List[str] = []
        scores: Dict[str, float] = {}

        spec_result = px_evaluator.eval_spec(spec_text) if spec_text else None
        if spec_text:
            if not self._score_ok(spec_result):
                failures.append(
                    "px eval_spec errored — treated as gate failure "
                    f"(fail_closed={self.fail_closed})"
                )
                if not self.fail_closed:
                    return GateResult(passed=True, scores=scores, failures=failures)
            else:
                spec_score = float(spec_result.score)
                scores["spec_quality"] = spec_score
                if spec_score < self.min_spec_quality:
                    failures.append(
                        f"spec_quality {spec_score:.2f} < min_spec_quality "
                        f"{self.min_spec_quality:.2f}"
                    )

        plan_result = px_evaluator.eval_plan(plan_text, spec_ref=spec_text) if plan_text else None
        if plan_text:
            if not self._score_ok(plan_result):
                failures.append(
                    "px eval_plan errored — treated as gate failure "
                    f"(fail_closed={self.fail_closed})"
                )
            else:
                plan_score = float(plan_result.score)
                scores["plan_score"] = plan_score
                if plan_score < self.min_plan_score:
                    failures.append(
                        f"plan_score {plan_score:.2f} < min_plan_score "
                        f"{self.min_plan_score:.2f}"
                    )

        return GateResult(
            passed=not failures,
            evaluator_available=True,
            scores=scores,
            failures=failures,
        )
