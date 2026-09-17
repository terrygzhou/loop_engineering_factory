"""EYW-184 — ARCH_REVIEW safety interlocks (EYW-178 P2-4).

Covers the three deliverables of EYW-184:

1. **ACHG context + auto-approve interlock** (EYW-171 §8.1 / §7.4):
   - `graph/achg_scanner.py` parses ArcKit ACHG documents into the
     `achg_context` payload (data contract:
     Obsidian/Eywalink/Architecture/EYW-171-ACHG-ARCH_REVIEW-interaction-spec.md).
   - ARCH_REVIEW auto-approval is BLOCKED while any ACHG has PENDING board
     status; the reviewer payload carries the ACHG panel.
2. **px_evaluator gate** (config-flagged via `arch_review_gate` in
   config/guardrails.yaml): a failing gate converts a plain "approve" to a
   reject with findings fed back to PLAN; approval requires `override: true`;
   fail-closed when the evaluator is unavailable.
3. **Reject-loop + data-contract tests**: reject → PLAN re-plan carries the
   reviewer feedback; after 2 rejections the route_phase livelock guard
   forces forward to BUILD.
"""

import copy
import uuid
from unittest.mock import patch

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from graph.state import CycleMetrics
from graph.achg_scanner import (
    scan_achg_context,
    has_pending_achg,
    pending_achg_ids,
)
from service.px_gate import PxGate
from service.evaluator import EvalResult
from graph.nodes import review as review_module


# ── ACHG fixture ─────────────────────────────────────────────────────────────

ACHG_TEMPLATE = """---
title: "Architecture Change Request"
docType: ACHG
templateVersion: "1.0"
---

# Architecture Change Request

## Document Control

| Field | Value |
|-------|-------|
| **Document ID** | `ARC-{pid}-{cid}-v{ver}` |
| **Change ID** | `{cid}` |
| **Status** | DRAFT |
| **Change Type** | {change_type} |
| **Priority** | {priority} |

## 1. Change Request

| Field | Value |
|-------|-------|
| Change ID | `{cid}` |
| Change Type | {change_type} |
| Priority | {priority} |

## 2. Rationale

### 2.1 Problem Statement
{summary}

### 2.4 Change Description
{summary}

## 4. Affected Artefacts

| Artefact | Impact Level | Action Required |
|----------|--------------|-----------------|
| `ARC-{pid}-BPCM-v2.1.md` | HIGH | Update |
| `ARC-{pid}-ADMP-v1.2.md` | MEDIUM | Update |

## 5. ADM Re-Entry Point

| ADM Phase | Re-Entry | Scope |
|-----------|----------|-------|
| Phase C (Information Systems Architectures) | YES | Update BPCM for {summary} |
| Phase H (Architecture Change Management) | YES | Record ACHG outcome |

## 8. Approval Workflow

| Stage | Owner | Decision | Date |
|-------|-------|----------|------|
| Board Review | TOGAF Board | {decision} | 2026-08-20 |
"""


def _write_achg(
    root,
    pid: str,
    slug: str,
    seq: str,
    version: str,
    *,
    decision: str = "Pending",
    priority: str = "HIGH",
    change_type: str = "EVOLUTIONARY",
    summary: str = "Add model explainability requirement to the underwriting pipeline (REQ-023).",
):
    d = root / "projects" / f"{pid}-{slug}" / "changes"
    d.mkdir(parents=True, exist_ok=True)
    cid = f"ACHG-{seq}"
    path = d / f"ARC-{pid}-{cid}-v{version}.md"
    path.write_text(
        ACHG_TEMPLATE.format(
            pid=pid, cid=cid, ver=version,
            change_type=change_type, priority=priority,
            summary=summary, decision=decision,
        )
    )
    return path


def _archg_tree_with_pending(tmp_path):
    """ArcKit tree with one PENDING-board ACHG (the interlock trigger)."""
    _write_achg(tmp_path, "007", "secure-payments", "001", "1.0", decision="Pending")
    return tmp_path


# ── 1. ACHG scanner (data contract, EYW-171 §8.1) ────────────────────────────


class TestAchGScanner:
    def test_scan_classifies_board_status(self, tmp_path):
        _write_achg(tmp_path, "007", "secure-payments", "001", "1.0", decision="Pending")
        _write_achg(tmp_path, "007", "secure-payments", "002", "1.0", decision="Approved", priority="MEDIUM")
        _write_achg(tmp_path, "007", "secure-payments", "003", "1.0", decision="Rejected")
        # Decoys: a non-ACHG artefact in the same folder, plus another project
        changes_dir = tmp_path / "projects" / "007-secure-payments" / "changes"
        (changes_dir / "ARC-007-REQ-v1.0.md").write_text("# Requirement\ndecoy\n")
        _write_achg(tmp_path, "001", "other-project", "001", "1.0", decision="Pending")

        ctx = scan_achg_context(str(tmp_path))
        assert has_pending_achg(ctx) is True
        pending = ctx["pending_achgs"]
        rejected = ctx["rejected_achgs"]
        # APPROVED + PENDING both go to pending_achgs (active governance context);
        # REJECTED is context-only
        assert len(pending) == 3
        assert {a["doc_id"] for a in rejected} == {"ARC-007-ACHG-003-v1.0"}
        assert [a["change_id"] for a in rejected] == ["ACHG-003"]

        # Field parsing for the 007/ACHG-001 entry
        entry = next(a for a in pending if a["doc_id"] == "ARC-007-ACHG-001-v1.0")
        assert entry["change_type"] == "EVOLUTIONARY"
        assert entry["priority"] == "HIGH"
        assert entry["board_status"] == "PENDING"
        assert entry["board_date"] == "2026-08-20"
        assert entry["summary"].startswith("Add model explainability")
        assert "ARC-007-BPCM-v2.1.md" in entry["affected_artifacts"]
        assert "ARC-007-ADMP-v1.2.md" in entry["affected_artifacts"]
        assert "Phase C (Information Systems Architectures)" in entry["adm_reentry"]
        assert "note" in ctx and "Pending ACHG" in ctx["note"]

    def test_project_id_filter(self, tmp_path):
        _write_achg(tmp_path, "007", "secure-payments", "001", "1.0", decision="Pending")
        _write_achg(tmp_path, "007", "secure-payments", "002", "1.0", decision="Approved")
        _write_achg(tmp_path, "001", "other-project", "001", "1.0", decision="Pending")

        ctx = scan_achg_context(str(tmp_path), project_id="007")
        assert len(ctx["pending_achgs"]) == 2
        assert all("ARC-007" in a["doc_id"] for a in ctx["pending_achgs"])
        assert pending_achg_ids(ctx) == ["ACHG-001"]

    def test_latest_version_wins_per_change(self, tmp_path):
        _write_achg(tmp_path, "007", "secure-payments", "004", "1.0", decision="Pending")
        _write_achg(tmp_path, "007", "secure-payments", "004", "1.1", decision="Approved")
        ctx = scan_achg_context(str(tmp_path))
        assert len(ctx["pending_achgs"]) == 1
        entry = ctx["pending_achgs"][0]
        assert entry["board_status"] == "APPROVED"
        assert entry["doc_id"].endswith("-v1.1")
        assert has_pending_achg(ctx) is False

    def test_placeholder_decision_counts_as_pending(self, tmp_path):
        # EYW-171 §7.4: undetermined board decision = PENDING board decision
        _write_achg(
            tmp_path, "007", "secure-payments", "001", "1.0",
            decision="[Pending/Approved/Rejected/Conditional]",
        )
        ctx = scan_achg_context(str(tmp_path))
        assert ctx["pending_achgs"][0]["board_status"] == "PENDING"
        assert has_pending_achg(ctx) is True

    def test_conditional_decision_is_not_pending(self, tmp_path):
        _write_achg(tmp_path, "007", "secure-payments", "001", "1.0", decision="Conditional")
        ctx = scan_achg_context(str(tmp_path))
        assert ctx["pending_achgs"][0]["board_status"] == "CONDITIONAL"
        assert has_pending_achg(ctx) is False

    def test_missing_or_empty_root_is_empty_context(self, tmp_path):
        for root in ("", str(tmp_path / "does-not-exist")):
            ctx = scan_achg_context(root)
            assert ctx["pending_achgs"] == []
            assert ctx["rejected_achgs"] == []
            assert has_pending_achg(ctx) is False
            assert has_pending_achg(None) is False
            assert pending_achg_ids(None) == []


# ── 2. px_evaluator gate (EYW-178 P2-4) ──────────────────────────────────────


class _FakeEvaluator:
    """Stand-in for the service.evaluator.evaluator singleton."""

    def __init__(self, spec_score=0.95, plan_score=0.95,
                 spec_rationale="ok", plan_rationale="ok", available=True):
        self._available = available
        self.spec_score = spec_score
        self.plan_score = plan_score
        self.spec_rationale = spec_rationale
        self.plan_rationale = plan_rationale
        self.spec_calls = 0
        self.plan_calls = 0

    def eval_spec(self, text):
        self.spec_calls += 1
        return EvalResult(name="spec_quality", score=self.spec_score,
                           rationale=self.spec_rationale)

    def eval_plan(self, text, spec_ref=""):
        self.plan_calls += 1
        return EvalResult(name="plan_quality", score=self.plan_score,
                          rationale=self.plan_rationale)


def _gate(**over):
    base = dict(enabled=True, min_spec_quality=0.8, min_plan_score=0.8, fail_closed=True)
    base.update(over)
    return PxGate(**base)


class TestPxGate:
    def test_disabled_gate_passes_without_evaluator(self):
        r = _gate(enabled=False).evaluate_review_gate("spec", "plan")
        assert r.passed is True and r.failures == []

    def test_passing_scores(self):
        with patch("service.evaluator.evaluator", _FakeEvaluator(0.95, 0.95)):
            r = _gate().evaluate_review_gate("spec text", "plan text")
        assert r.passed is True
        assert r.scores["spec_quality"] == 0.95 and r.scores["plan_score"] == 0.95

    def test_low_plan_score_fails(self):
        with patch("service.evaluator.evaluator", _FakeEvaluator(0.95, 0.4)):
            r = _gate().evaluate_review_gate("spec text", "plan text")
        assert r.passed is False
        assert any("plan_score" in f for f in r.failures)

    def test_low_spec_score_fails(self):
        with patch("service.evaluator.evaluator", _FakeEvaluator(0.5, 0.95)):
            r = _gate().evaluate_review_gate("spec text", "plan text")
        assert r.passed is False
        assert any("spec_quality" in f for f in r.failures)

    def test_threshold_boundary_passes(self):
        # score == min is NOT a failure (fail is strictly-below)
        with patch("service.evaluator.evaluator", _FakeEvaluator(0.8, 0.8)):
            r = _gate().evaluate_review_gate("spec text", "plan text")
        assert r.passed is True

    def test_unavailable_fail_closed(self):
        r = _gate(fail_closed=True).evaluate_review_gate("spec", "plan")
        assert r.passed is False
        assert r.evaluator_available is False
        assert any("fail_closed" in f for f in r.failures)

    def test_unavailable_fail_open(self):
        r = _gate(fail_closed=False).evaluate_review_gate("spec", "plan")
        assert r.passed is True
        assert r.evaluator_available is False

    def test_eval_error_counts_as_unavailable(self):
        with patch(
            "service.evaluator.evaluator",
            _FakeEvaluator(spec_rationale="Eval error: LLM down", plan_rationale="ok"),
        ):
            r = _gate(fail_closed=True).evaluate_review_gate("spec", "plan")
        assert r.passed is False
        assert any("eval_spec" in f for f in r.failures)

    def test_to_artifact_roundtrip(self):
        r = _gate(fail_closed=False).evaluate_review_gate("spec", "plan")
        art = r.to_artifact()
        assert set(art) == {"passed", "evaluator_available", "scores", "failures"}


# ── 3. review_node interlocks (unit) ─────────────────────────────────────────


def _review_state(**over):
    base = {
        "cycle_id": "test-eyw184",
        "trace_id": "t184",
        "phase": "ARCH_REVIEW",
        "metrics": CycleMetrics(
            spec_confidence=0.95, arch_uncertainty=0.1,
            security_findings=0, review_revisions=0, uat_pass_rate=0.99,
        ),
        "context_folder": "",
        "project_path": "",
        "auto_approve_override": False,
        "artifacts": {"plan": "plan text", "spec_refined": "spec text"},
    }
    base.update(over)
    return base


def _pending_achg_context():
    return {
        "pending_achgs": [
            {
                "change_id": "ACHG-001",
                "doc_id": "ARC-007-ACHG-001-v1.0",
                "change_type": "EVOLUTIONARY",
                "priority": "HIGH",
                "board_status": "PENDING",
                "board_date": "",
                "summary": "Add explainability to underwriting",
                "affected_artifacts": ["ARC-007-BPCM-v2.1.md"],
                "adm_reentry": ["Phase C (Information Systems Architectures)"],
            }
        ],
        "rejected_achgs": [],
        "note": "Pending ACHGs are context for your review.",
    }


class TestReviewNodeInterlocks:
    def test_auto_approve_passes_without_pending_achg(self):
        out = review_module.review_node(
            _review_state(auto_approve_override=True)
        )
        assert out["artifacts"]["review_approved"] is True
        assert out["next_phase"] == "BUILD"

    def test_auto_approve_blocked_by_pending_achg(self, monkeypatch):
        captured = {}

        def fake_interrupt(payload):
            captured["payload"] = payload
            return {"approved": True}  # explicit human decision after the block

        monkeypatch.setattr(review_module, "interrupt", fake_interrupt)
        out = review_module.review_node(
            _review_state(
                auto_approve_override=True,
                artifacts={"plan": "p", "spec_refined": "s",
                           "achg_context": _pending_achg_context()},
            )
        )
        # Auto-approve was suppressed — the node took the HIL interrupt path
        assert "payload" in captured
        payload = captured["payload"]
        assert payload["type"] == "review"
        assert payload["achg_context"]["pending_achgs"][0]["board_status"] == "PENDING"
        assert "PENDING ACHG" in payload["description"]
        # The explicit approve still routes to BUILD
        assert out["artifacts"]["review_approved"] is True
        assert out["next_phase"] == "BUILD"

    def test_interrupt_payload_carries_achg_scan_from_disk(self, monkeypatch, tmp_path):
        _archg_tree_with_pending(tmp_path)
        captured = {}
        monkeypatch.setattr(
            review_module, "interrupt",
            lambda payload: (captured.__setitem__("payload", payload), {"approved": True})[1],
        )
        out = review_module.review_node(
            _review_state(context_folder=str(tmp_path))
        )
        assert has_pending_achg(captured["payload"]["achg_context"]) is True
        assert out["next_phase"] == "BUILD"

    def test_reject_persists_loop_count(self, monkeypatch):
        monkeypatch.setattr(
            review_module, "interrupt",
            lambda payload: {"approved": False, "feedback": "fix the data model"},
        )
        out = review_module.review_node(
            _review_state(artifacts={"plan": "p", "spec_refined": "s",
                                     "loop_counts": {"ARCH_REVIEW": 1}})
        )
        # Second reject → counter at 2 → route_phase forces BUILD (livelock guard)
        assert out["artifacts"]["loop_counts"]["ARCH_REVIEW"] == 2
        assert out["user_review_comments"] == "fix the data model"
        assert out["next_phase"] == "PLAN"
        assert out["artifacts"]["review_approved"] is False

    def test_gate_blocks_plain_approve(self, monkeypatch):
        fake = _FakeEvaluator(spec_score=0.95, plan_score=0.4)
        monkeypatch.setattr(review_module, "get_arch_review_gate", lambda: {
            "enabled": True, "min_spec_quality": 0.8, "min_plan_score": 0.8,
            "fail_closed": True,
        })
        monkeypatch.setattr(
            review_module, "interrupt", lambda payload: {"approved": True}
        )
        with patch("service.evaluator.evaluator", fake):
            out = review_module.review_node(_review_state())
        assert out["next_phase"] == "PLAN"
        assert out["artifacts"]["review_approved"] is False
        assert "[px-gate]" in out["user_review_comments"]
        assert "plan_score" in out["user_review_comments"]

    def test_gate_fail_closed_blocks_approve(self, monkeypatch):
        monkeypatch.setattr(review_module, "get_arch_review_gate", lambda: {
            "enabled": True, "min_spec_quality": 0.8, "min_plan_score": 0.8,
            "fail_closed": True,
        })
        monkeypatch.setattr(
            review_module, "interrupt", lambda payload: {"approved": True}
        )
        # Evaluator unavailable → fail-closed gate blocks the plain approve
        with patch("service.evaluator.evaluator", None):
            out = review_module.review_node(_review_state())
        assert out["next_phase"] == "PLAN"
        assert "fail_closed" in out["user_review_comments"]

    def test_gate_override_approves(self, monkeypatch):
        fake = _FakeEvaluator(spec_score=0.95, plan_score=0.4)
        monkeypatch.setattr(review_module, "get_arch_review_gate", lambda: {
            "enabled": True, "min_spec_quality": 0.8, "min_plan_score": 0.8,
            "fail_closed": True,
        })
        monkeypatch.setattr(
            review_module, "interrupt",
            lambda payload: {"approved": True, "override": True},
        )
        with patch("service.evaluator.evaluator", fake):
            out = review_module.review_node(_review_state())
        assert out["artifacts"]["review_approved"] is True
        assert out["next_phase"] == "BUILD"


# ── 4. End-to-end reject loop through the compiled graph ────────────────────

SPEC_TEXT = "Refined spec for the secure-payments underwriting module. 500+ chars " * 8
PLAN_TEXT = (
    "## Implementation Plan\n"
    "- [ ] Task 1: Foundation — schema + migrations\n"
    "1. Task 2: Core — underwriting service\n"
    "2. Task 3: Integration — risk feed adapter\n"
)


def _base_state(**over):
    base = {
        "cycle_id": "test-eyw184-e2e",
        "phase": "DISCOVER",
        "metrics": CycleMetrics(
            spec_confidence=0.95, arch_uncertainty=0.1,
            security_findings=0, review_revisions=0, uat_pass_rate=0.99,
        ),
        "feedback": [],
        "feedback_context": "",
        "config_version": "1.0",
        "human_approval_required": False,
        "next_phase": None,
        "project_name": "SecurePayments",
        "project_path": "/tmp/e2e-eyw184",
        "project_folder": "/tmp/e2e-eyw184",
        "project_description": "Regulated payments project",
        "skip_discover": False,
        "context_folder": "",
        "error": None,
        "diagrams": {},
        "diagram_status": "",
        "diagram_feedback": "",
        "improve_mode": False,
        "auto_approve_override": False,
        "force_hil": False,
        "interview_notes": "",
        "discover_setup_done": False,
        "discover_interview_done": False,
        "trace_id": "t184-e2e",
        "superweb_mode": "",
        "superweb_agent_report": None,
        "artifacts": {},
        "project_context": "",
        "spec_text": "",
        "spec_refined": "",
        "plan": "",
        "tasks": "",
        "backlog": [],
        "diagram_pngs": {},
        "user_review_comments": "",
        "status": "running",
        "retry_count": 0,
        "spec_confidence": 0.95,
        "tasks_text": "",
        "solution_md": "",
    }
    base.update(over)
    return base


def _stubbed_nodes(rec):
    """Stubs for every node except the real ARCH_REVIEW node."""

    def discover_node(state):
        return {
            "phase": "DISCOVER", "next_phase": "DEFINE",
            "artifacts": {"spec_refined": SPEC_TEXT, "interview_notes": "n/a"},
        }

    def define_node(state):
        return {
            "phase": "DEFINE", "next_phase": "PLAN",
            "artifacts": {"api_contract": "GET /api/underwrite"},
        }

    def plan_node(state):
        rec["plan_states"].append(copy.deepcopy(state))
        return {
            "phase": "PLAN", "next_phase": "ARCH_REVIEW",
            "artifacts": {"plan": PLAN_TEXT, "tasks": PLAN_TEXT},
        }

    def build_node(state):
        rec["build_calls"] += 1
        return {"phase": "BUILD", "next_phase": "SEED_DATA"}

    def _passthrough(phase, nxt):
        def node(state):
            return {"phase": phase, "next_phase": nxt}
        return node

    return {
        "graph.main.discover_node": discover_node,
        "graph.main.define_node": define_node,
        "graph.main.plan_node": plan_node,
        "graph.main.openhands_build_proxy_factory": lambda: build_node,
        "graph.main.seed_data_node": _passthrough("SEED_DATA", "VERIFY"),
        "graph.main.verify_node": _passthrough("VERIFY", "SHIP"),
        "graph.main.ship_node": _passthrough("SHIP", "REFLECT"),
        "graph.main.reflect_node": lambda state: {"phase": "REFLECT"},
    }


def _enter_stub_patches(rec):
    """Context manager stacking all node stubs."""
    stubs = _stubbed_nodes(rec)
    patchers = [patch(target, value) for target, value in stubs.items()]
    for p in patchers:
        p.start()

    class _Exit:
        def __call__(self):
            for p in reversed(patchers):
                p.stop()

    return _Exit()


def _stream_to_review_interrupt(graph, input_value, cfg, expect_review=True):
    """Stream until a review-type interrupt; return its payload (or None)."""
    payload = None
    for chunk in graph.stream(input_value, cfg, stream_mode="values"):
        if isinstance(chunk, dict) and chunk.get("__interrupt__"):
            value = chunk["__interrupt__"][0].value
            if isinstance(value, dict) and value.get("type") == "review":
                payload = value
    if expect_review and payload is None:
        raise AssertionError("expected a review interrupt, stream ended without one")
    return payload


class TestRejectLoopEndToEnd:
    """Reject → PLAN (with feedback) → reject → force-forward BUILD."""

    def test_reject_loop_feeds_plan_and_forces_build_after_two_rejects(self, tmp_path):
        _archg_tree_with_pending(tmp_path)
        rec = {"plan_states": [], "build_calls": 0}
        exit_stubs = _enter_stub_patches(rec)
        try:
            from graph.main import build_graph

            graph = build_graph(checkpointer=InMemorySaver(), auto_approve=True)
            cfg = {"configurable": {"thread_id": str(uuid.uuid4())}}
            state = _base_state(context_folder=str(tmp_path))

            # ── 1st review: ACHG panel must be in the interrupt payload ──
            payload = _stream_to_review_interrupt(graph, state, cfg)
            assert has_pending_achg(payload["achg_context"]) is True
            assert "PENDING ACHG" in payload["description"]

            # ── Reject #1 → PLAN re-runs WITH the feedback ──
            _stream_to_review_interrupt(
                graph,
                Command(resume={"approved": False, "feedback": "f1: fix data model"}),
                cfg,
            )
            assert len(rec["plan_states"]) == 2
            assert rec["plan_states"][1]["user_review_comments"] == "f1: fix data model"

            # ── Reject #2 → loop_count hits 2 → route_phase forces BUILD ──
            _stream_to_review_interrupt(
                graph,
                Command(resume={"approved": False, "feedback": "f2: still wrong"}),
                cfg,
                expect_review=False,
            )
            assert rec["build_calls"] == 1

            final = graph.get_state(cfg)
            assert not final.next, f"graph did not terminate: next={final.next}"
        finally:
            exit_stubs()

    def test_approve_routes_to_build(self, tmp_path):
        _archg_tree_with_pending(tmp_path)
        rec = {"plan_states": [], "build_calls": 0}
        exit_stubs = _enter_stub_patches(rec)
        try:
            from graph.main import build_graph

            graph = build_graph(checkpointer=InMemorySaver(), auto_approve=True)
            cfg = {"configurable": {"thread_id": str(uuid.uuid4())}}
            state = _base_state(context_folder=str(tmp_path))

            _stream_to_review_interrupt(graph, state, cfg)
            _stream_to_review_interrupt(
                graph, Command(resume={"approved": True, "feedback": ""}), cfg,
                expect_review=False,
            )
            assert rec["build_calls"] == 1
            assert len(rec["plan_states"]) == 1  # no re-plan after approval
        finally:
            exit_stubs()

    def test_px_gate_blocks_approve_and_override_unblocks(self, tmp_path):
        """Gate fails → plain approve becomes reject → override approve wins."""
        _archg_tree_with_pending(tmp_path)
        rec = {"plan_states": [], "build_calls": 0}
        fake = _FakeEvaluator(spec_score=0.95, plan_score=0.4)
        exit_stubs = _enter_stub_patches(rec)
        try:
            import contextlib

            gate_cfg = {
                "enabled": True, "min_spec_quality": 0.8,
                "min_plan_score": 0.8, "fail_closed": True,
            }

            @contextlib.contextmanager
            def _gate_on():
                with patch("service.evaluator.evaluator", fake), patch.object(
                    review_module, "get_arch_review_gate", lambda: gate_cfg
                ):
                    yield

            with _gate_on():
                from graph.main import build_graph

                graph = build_graph(checkpointer=InMemorySaver(), auto_approve=True)
                cfg = {"configurable": {"thread_id": str(uuid.uuid4())}}
                state = _base_state(context_folder=str(tmp_path))

                payload = _stream_to_review_interrupt(graph, state, cfg)
                # Gate result surfaced in the reviewer payload
                assert payload["px_gate"]["passed"] is False
                assert any("plan_score" in f for f in payload["px_gate"]["failures"])

                # Plain approve → converted to reject → PLAN re-runs with findings
                _stream_to_review_interrupt(
                    graph, Command(resume={"approved": True}), cfg,
                )
                assert len(rec["plan_states"]) == 2
                assert "[px-gate]" in rec["plan_states"][1]["user_review_comments"]

                # Re-review with explicit override → BUILD
                _stream_to_review_interrupt(
                    graph,
                    Command(resume={"approved": True, "override": True}),
                    cfg,
                    expect_review=False,
                )
                assert rec["build_calls"] == 1
        finally:
            exit_stubs()
