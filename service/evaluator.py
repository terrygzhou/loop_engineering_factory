"""
Phoenix LLM-evaluator for Loop Factory workflow phases.

Architecture:
    Phase output → LLM-as-judge (Qwen3.6-27B) → OTel span → Phoenix UI

Context-aware evaluation: the LLM first extracts project domain/context
from the spec, then scores against criteria tailored to that domain.
A CRM project gets different weightings than a CLI tool.

Evaluators run at phase-completion (hooked in executor.py).
Graceful degradation — never blocks workflow if eval fails.

Metrics:
  - spec_quality   (DISCOVER)   — domain-aware requirement quality
  - plan_score     (PLAN)       — project-specific plan alignment
  - review_score   (REVIEW)     — context-aware risk identification
  - build_quality  (BUILD)      — code quality, test coverage, architecture, security
  - ship_quality   (SHIP)       — prod config completeness, secret safety, resilience
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Graceful import — phoenix SDK is optional for evals
_import_error: Optional[str] = None
try:
    import phoenix.trace_eval as _px_eval  # type: ignore  # noqa: F401
except ImportError as e:
    _import_error = str(e)

try:
    from opentelemetry import trace  # type: ignore
except ImportError:
    trace = None

__all__ = ["Evaluator", "evaluator"]


# ── Evaluator definitions ──────────────────────────────────────────────

@dataclass
class EvalResult:
    """Single evaluation result with score, rationale, and dimensions."""
    name: str
    score: float                        # 0.0–1.0
    rationale: str = ""
    dimensions: Dict[str, float] = field(default_factory=dict)
    duration_s: float = 0.0
    model: str = ""

    def to_attributes(self) -> Dict[str, Any]:
        """Shape for OTel span attributes."""
        attrs: Dict[str, Any] = {
            "eval.name": self.name,
            "eval.score": round(self.score, 3),
            "eval.rationale": self.rationale[:2000],
            "eval.model": self.model,
            "eval.duration_s": round(self.duration_s, 3),
        }
        for dim, val in self.dimensions.items():
            attrs[f"eval.dim.{dim}"] = round(val, 3)
        return attrs


# ── Prompts (context-aware, LLM-as-judge templates) ────────────────────
# Each prompt: (1) analyze project context, (2) extract domain-specific
# criteria, (3) score against those criteria.

SPEC_QUALITY_PROMPT = """Analyze the project below, then score its specification quality.

STEP 1: Identify project type and domain.
STEP 2: For THIS type of project, what matters most in a spec? (e.g., API surface for a web service, data models for a database project, CLI ergonomics for a tool)
STEP 3: Score the spec on project-specific criteria.

SPECIFICATION:
{spec_text}

Score dimensions:
- domain_fit: How well does the spec capture what matters for THIS project type?
- clarity: Are requirements unambiguous and testable?
- completeness: Does it cover the full scope including constraints?
- consistency: No contradictions or gaps?
- actionability: Can a developer implement from this alone?

Respond JSON only: {{"score": float, "dimensions": {{"domain_fit": float, "clarity": float, "completeness": float, "consistency": float, "actionability": float}}, "rationale": "string"}}"""

PLAN_SCORE_PROMPT = """Analyze the project spec, then score the implementation plan against it.

STEP 1: From the spec, identify: project type, domain, critical constraints, and what success looks like.
STEP 2: Evaluate whether the plan is tailored to THIS project — not a generic template.
STEP 3: Score on project-specific criteria.

SPEC REFERENCE (project context):
{spec_ref}

PLAN TO EVALUATE:
{plan_text}

Score dimensions:
- coverage: Does it address every requirement from the spec?
- actionability: Tasks specific, ordered, estimable for THIS project?
- architecture: Design sound for this domain (patterns, separation, error handling)?
- risk: Are project-specific edge cases and failure modes addressed?
- domain_fit: Is the technical approach appropriate for this project type?

Respond JSON only: {{"score": float, "dimensions": {{"coverage": float, "actionability": float, "architecture": float, "risk": float, "domain_fit": float}}, "rationale": "string"}}"""

REVIEW_SCORE_PROMPT = """Analyze the project context, then score this review document.

STEP 1: From the spec context, understand what the project does and its risk profile.
STEP 2: For THIS project type, what would a good review actually catch?
STEP 3: Score the review on project-specific depth.

SPEC CONTEXT (what the project is):
{spec_context}

REVIEW DOCUMENT TO EVALUATE:
{review_text}

Score dimensions:
- thoroughness: Does it identify real risks for THIS project, not boilerplate?
- specificity: Are findings tied to concrete code/requirements in this project?
- actionability: Are recommendations implementable for this codebase?
- severity: Are critical issues weighted appropriately for this domain?
- domain_fit: Does the reviewer understand this project's context?

Respond JSON only: {{"score": float, "dimensions": {{"thoroughness": float, "specificity": float, "actionability": float, "severity": float, "domain_fit": float}}, "rationale": "string"}}"""

BUILD_QUALITY_PROMPT = """Analyze the BUILD phase output for this project, then score the code quality.

STEP 1: Identify the project type and domain from the spec.
STEP 2: For THIS type of project, what code quality matters most? (e.g., API contract adherence for web services, data model integrity for database projects, CLI ergonomics for tools)
STEP 3: Score the BUILD artifacts on project-specific criteria.

SPEC REFERENCE (project context):
{spec_ref}

BUILD ARTIFACTS (test results, UAT report, code summary):
{build_artifacts}

Score dimensions:
- code_quality: Clean architecture, proper separation of concerns, error handling patterns appropriate for this domain
- test_coverage: Unit tests cover critical paths and edge cases; test isolation and determinism
- security: No hardcoded secrets, input validation, rate limiting, proper auth patterns for this project type
- performance: Reasonable query patterns, no N+1 problems, sensible indexing for this data model
- maintainability: Clear naming, consistent structure, documentation, import hygiene, dependency management

Respond JSON only: {{"score": float, "dimensions": {{"code_quality": float, "test_coverage": float, "security": float, "performance": float, "maintainability": float}}, "rationale": "string"}}"""

SHIP_QUALITY_PROMPT = """Analyze the SHIP phase output for this project, then score the production deployment configuration.

STEP 1: Identify the project type and deployment target from the context.
STEP 2: For THIS deployment scenario, what configuration correctness matters most?
STEP 3: Score the SHIP artifacts on production-readiness criteria.

SPEC REFERENCE (project context):
{spec_ref}

SHIP ARTIFACTS (deployment configs, CI/CD pipeline, secrets, health checks):
{ship_artifacts}

Score dimensions:
- config_completeness: All production environments covered (database, cache, secrets, TLS, monitoring) with no missing pieces
- secret_safety: No .env references in cloud configs; proper secret manager integration (AWS Secrets Manager / Azure Key Vault / GCP Secret Manager)
- resilience: Health check endpoints configured, auto-scaling thresholds set, rollback strategy documented
- observability: Structured logging, RED metrics (Request/Duration/Errors), distributed tracing configured for target platform
- deployment_automation: CI/CD pipeline is idempotent, supports blue-green or canary, handles database migrations safely

Respond JSON only: {{"score": float, "dimensions": {{"config_completeness": float, "secret_safety": float, "resilience": float, "observability": float, "deployment_automation": float}}, "rationale": "string"}}"""


# ── Evaluator class ──────────────────────────────────────────────────

class Evaluator:
    """LLM-as-judge evaluator using the existing model endpoint.

    Results stream to Phoenix via OTel span attributes. Graceful
    degradation: if LLM is unreachable or phoenix SDK missing,
    workflow continues silently.
    """

    def __init__(
        self,
        llm_base_url: str = "",
        llm_model: str = "",
        tracer: Any = None,
        api_key: str = "",
    ):
        self.llm_base_url = llm_base_url
        self.llm_model = llm_model
        self.tracer = tracer
        self.api_key = api_key or "not-needed"
        self._available = bool(llm_base_url and llm_model)

    # ── Public API (context-aware) ──

    def eval_spec(self, spec_text: str) -> EvalResult:
        """Evaluate DISCOVER phase output. Score the spec against its own domain."""
        return self._judge("spec_quality", SPEC_QUALITY_PROMPT, spec_text=spec_text)

    def eval_plan(self, plan_text: str, spec_ref: str = "") -> EvalResult:
        """Evaluate PLAN phase output. Score plan against project-specific spec."""
        return self._judge("plan_score", PLAN_SCORE_PROMPT, plan_text=plan_text, spec_ref=spec_ref)

    def eval_review(self, review_text: str, spec_context: str = "") -> EvalResult:
        """Evaluate REVIEW phase output. Score review depth against project context."""
        return self._judge("review_score", REVIEW_SCORE_PROMPT, review_text=review_text, spec_context=spec_context)

    def eval_build(self, build_artifacts: str, spec_ref: str = "") -> EvalResult:
        """Evaluate BUILD phase output. Score code quality, test coverage, security, performance, maintainability."""
        return self._judge("build_quality", BUILD_QUALITY_PROMPT, build_artifacts=build_artifacts, spec_ref=spec_ref)

    def eval_ship(self, ship_artifacts: str, spec_ref: str = "") -> EvalResult:
        """Evaluate SHIP phase output. Score prod config completeness, secret safety, resilience, observability, deployment automation."""
        return self._judge("ship_quality", SHIP_QUALITY_PROMPT, ship_artifacts=ship_artifacts, spec_ref=spec_ref)

    # ── Core judge ──

    def _judge(self, name: str, template: str, **ctx: str) -> EvalResult:
        """Call LLM-as-judge and attach result to OTel."""
        result = EvalResult(name=name, score=0.0, model=self.llm_model)

        if not self._available:
            return result

        try:
            import httpx  # already in requirements.txt
            prompt = template.format(**ctx)
            start = time.time()

            resp = httpx.post(
                f"{self.llm_base_url}/chat/completions",
                json={
                    "model": self.llm_model,
                    "messages": [
                        {"role": "system", "content": "You are an impartial evaluator. Score 0.0–1.0 and explain briefly. Adapt your criteria to the project domain."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 512,
                },
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=30.0,
            )

            result.duration_s = round(time.time() - start, 3)

            if resp.status_code != 200:
                result.rationale = f"LLM HTTP {resp.status_code}: {resp.text[:200]}"
                return result

            body = resp.json()
            raw = body["choices"][0]["message"]["content"]
            parsed = self._parse_json(raw)
            result.score = parsed.get("score", 0.0)
            result.rationale = parsed.get("rationale", "")
            result.dimensions = parsed.get("dimensions", {})
        except Exception as e:
            result.rationale = f"Eval error: {e}"
            if "start" in locals():
                result.duration_s = round(time.time() - start, 3)

        # Record to OTel — piggybacks on tracer's current span
        self._record_to_otel(result)
        return result

    def _parse_json(self, raw: str) -> Dict[str, Any]:
        """Extract JSON from LLM response (handle markdown fences, whitespace)."""
        import re
        text = raw.strip()
        # Strip markdown code fences if present
        m = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
        if m:
            text = m.group(1).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Fallback: find first { ... }
            m = re.search(r"(\{.*\})", text, re.DOTALL)
            if m:
                return json.loads(m.group(1))
            return {"score": 0.0, "rationale": raw[:500], "dimensions": {}}

    def _record_to_otel(self, result: EvalResult):
        """Attach eval result as OTel span attributes."""
        if not self.tracer or not self.tracer.is_configured():
            return

        attrs = result.to_attributes()
        # Emit a dedicated eval span under the current workflow context
        if trace:
            span = trace.get_tracer("eval").start_span(
                f"eval.{result.name}",
                attributes=attrs,
            )
            span.end()


# ── Module singleton ─────────────────────────────────────────────────

# Created lazily when executor imports it (passes tracer + config).
evaluator: Optional["Evaluator"] = None


def init_evaluator(llm_base_url: str, llm_model: str, tracer_instance: Any, api_key: str = ""):
    """Initialize the singleton evaluator. Call once at startup."""
    global evaluator
    evaluator = Evaluator(
        llm_base_url=llm_base_url,
        llm_model=llm_model,
        tracer=tracer_instance,
        api_key=api_key,
    )