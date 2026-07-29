"""
Shared executor — singleton workflow core for both CLI (main.py) and Web (app.py).

Uses LangGraph OOTB APIs:
- Command(resume=...) for resuming after interrupt()
- graph.stream() for streaming chunks
- graph.aget_state() for checkpoint inspection
- graph.aupdate_state() for state updates (replaced by Command)

Both modes import this module. Graph construction and state initialization
are identical. Only the UX layer (CLI prompts vs WebSocket) differs.
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict

from langgraph.config import get_stream_writer as _raw_get_stream_writer

def get_stream_writer():
    """Safe wrapper: returns a no-op lambda when called outside a runnable context."""
    try:
        return _raw_get_stream_writer()
    except RuntimeError:
        return lambda *a, **kw: None

# Ensure project root is on path so config.loader resolves
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from config.loader import config  # noqa: E402
from graph.main import build_graph  # noqa: E402
from graph.state import CycleMetrics, WorkflowState  # noqa: E402
from graph.sqlite_saver import SqliteSaver  # noqa: E402
from tools.loader import build_skill_registry  # noqa: E402

# ── Observability ──
from service.otel_instrumentor import tracer  # noqa: E402
from service.evaluator import evaluator as px_evaluator  # noqa: E402
from service import health as health_module  # noqa: E402
from log.logging import setup_logger, log_event  # noqa: E402

logger = setup_logger("executor")


def _run_phase_eval(phase: str, chunk: Dict) -> None:
    """Run Phoenix eval on phase output if evaluator is available.

    Graceful: no-op when evaluator is None or LLM unreachable.
    """
    if px_evaluator is None:
        return

    artifacts = chunk.get("artifacts") or {}

    if phase == "DISCOVER":
        spec_text = artifacts.get("spec_refined", "") or artifacts.get("requirement_md", "")
        if spec_text:
            px_evaluator.eval_spec(spec_text)

    elif phase == "PLAN":
        plan_text = artifacts.get("plan", "") or artifacts.get("plan_md", "")
        spec_ref = artifacts.get("spec_refined", "")
        if plan_text:
            px_evaluator.eval_plan(plan_text, spec_ref=spec_ref)

    elif phase == "ARCH_REVIEW":
        review_text = artifacts.get("review", "") or artifacts.get("review_notes", "")
        spec_context = artifacts.get("spec_refined", "")
        if review_text:
            px_evaluator.eval_review(review_text, spec_context=spec_context)

    elif phase == "BUILD":
        # Aggregate BUILD artifacts for evaluation
        build_parts = []
        test_results = artifacts.get("test_results", "")
        if test_results:
            build_parts.append(f"TEST RESULTS:\n{test_results[:3000]}")
        uat_report = artifacts.get("uat_report", "")
        if uat_report:
            build_parts.append(f"UAT REPORT:\n{uat_report[:3000]}")
        build_log = artifacts.get("build_log", "")
        if build_log:
            build_parts.append(f"BUILD LOG:\n{build_log[:3000]}")
        deploy_gate = artifacts.get("deploy_gate_result", "")
        if deploy_gate:
            build_parts.append(f"DEPLOY GATE:\n{deploy_gate}")
        build_status = artifacts.get("build_status", "")
        build_parts.insert(0, f"BUILD STATUS: {build_status}")

        if build_parts:
            build_artifacts = "\n\n---\n\n".join(build_parts)
            spec_ref = artifacts.get("spec_refined", "")
            px_evaluator.eval_build(build_artifacts, spec_ref=spec_ref)

    elif phase == "SHIP":
        # Aggregate SHIP artifacts for evaluation
        ship_parts = []
        obs = artifacts.get("observability", "")
        if obs:
            ship_parts.append(f"OBSERVABILITY CONFIG:\n{obs[:2000]}")
        launch = artifacts.get("launch_checklist", "")
        if launch:
            ship_parts.append(f"LAUNCH CHECKLIST:\n{launch[:2000]}")
        prod_deploy = artifacts.get("prod_deploy_config", "")
        if prod_deploy:
            ship_parts.append(f"PRODUCTION DEPLOYMENT CONFIG:\n{prod_deploy[:3000]}")
        deploy_logs = artifacts.get("deploy_logs", "")
        if deploy_logs:
            ship_parts.append(f"DEPLOYMENT LOGS:\n{deploy_logs[:1000]}")

        if ship_parts:
            ship_artifacts = "\n\n---\n\n".join(ship_parts)
            spec_ref = artifacts.get("spec_refined", "")
            px_evaluator.eval_ship(ship_artifacts, spec_ref=spec_ref)


def get_skills_dir() -> str:
    """Resolve skills directory — config > Docker mount > local default."""
    sd = config.paths.skills_dir
    if Path(sd).exists():
        return sd
    return config.paths.project_path


def get_project_path() -> str:
    """Resolve project output directory from config."""
    return config.paths.project_path


def build_executor_state(
    cycle_id: str = "1",
    project_name: str = "",
    spec_text: str = "",
    context_folder: str = "",
    improve_mode: bool = False,
) -> WorkflowState:
    """Build initial WorkflowState. Skill registry is lazy-loaded per-node via build_skill_registry()."""
    skip_discover = not bool(context_folder) and not improve_mode

    return WorkflowState(
        cycle_id=cycle_id,
        phase="DISCOVER",
        next_phase="DEFINE",
        project_name=project_name,
        metrics=CycleMetrics(
            spec_confidence=0.0, arch_uncertainty=0.0, task_count=0,
            review_revisions=0, security_findings=0, uat_pass_rate=0.0,
            latency_ms=0.0, test_flakiness_rate=0.0, launch_success=False,
        ),
        config_version="1",
        artifacts={
            "loop_counts": {},
            "project_name": project_name,
        },
        feedback=[],
        error=None,
        spec_text=spec_text,
        project_path=get_project_path(),
        skip_discover=skip_discover,
        context_folder=context_folder,
        human_approval_required=False,
        improve_mode=improve_mode,
        diagrams={},
        diagram_status="pending",
        diagram_feedback="",
        project_folder="",
        project_description="",
        feedback_context="",
        interview_notes="",
        discover_interview_done=False,
        auto_approve_override=None,
        force_hil=False,
        trace_id="",
        superweb_mode="",
        superweb_agent_report=None,
        # Parent graph runtime keys (S-001)
        project_context="",
        spec_refined="",
        plan="",
        tasks="",
        backlog=[],
        diagram_pngs={},
        user_review_comments="",
        status="",
        retry_count=0,
        loop_counts={},
        spec_confidence=0.0,
        tasks_text="",
        solution_md="",
    )


def get_graph(checkpointer=None, auto_approve=False):
    """Build and compile the LangGraph workflow."""
    return build_graph(checkpointer=checkpointer, auto_approve=auto_approve)


def _get_checkpointer():
    """Create a SQLiteSaver checkpointer with configurable DB path."""
    from config.loader import config as _cfg
    build_dir = _cfg.paths.build_dir
    db_path = os.environ.get("CHECKPOINT_DB", os.path.join(build_dir, "checkpoints.db"))
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    return SqliteSaver.from_conn_string(db_path)


class WorkflowRunner:
    """Shared workflow runner for CLI and Web modes.

    Uses LangGraph OOTB pattern:
    1. graph.stream() for normal execution
    2. GraphInterrupt → on_hil() → Command(resume=...) → graph.stream()
    """

    def __init__(self, auto_approve=False):
        import uuid as _uuid
        self.checkpointer = _get_checkpointer()
        self.graph = get_graph(checkpointer=self.checkpointer, auto_approve=auto_approve)
        self.thread_id = str(_uuid.uuid4())
        self.auto_approve = auto_approve

    def _get_fresh_checkpointer(self):
        """Return a new SqliteSaver for a fresh workflow run."""
        return _get_checkpointer()

    def run_interactive(
        self,
        project_name: str,
        spec_text: str = "",
        context_folder: str = "",
        auto_approve: bool = False,
        improve_mode: bool = False,
    ):
        """Run the workflow synchronously with observability instrumentation."""
        config.reset_paths(project_name)
        self.checkpointer = self._get_fresh_checkpointer()
        self.graph = build_graph(checkpointer=self.checkpointer, auto_approve=self.auto_approve)
        self.thread_id = str(__import__("uuid").uuid4())

        cycle_id = "1"
        state = build_executor_state(
            cycle_id=cycle_id,
            project_name=project_name,
            spec_text=spec_text,
            context_folder=context_folder,
            improve_mode=improve_mode,
        )
        state["auto_approve_override"] = auto_approve
        if auto_approve:
            state["diagram_status"] = "approved"

        log_event(logger, "workflow.run", project=project_name, skip_discover=state.get("skip_discover"))

        writer = get_stream_writer()
        if state.get("skip_discover"):
            writer({"type": "progress", "phase": "DISCOVER", "step": "status", "detail": "Skipped — no context folder (greenfield mode)", "ts": time.time()})
        else:
            writer({"type": "progress", "phase": "DISCOVER", "step": "status", "detail": f"Scanning {context_folder}...", "ts": time.time()})

        async def _run():
            last = None
            async for chunk in self._astream_with_hil(state, auto_approve, on_hil=self._hil_cli):
                last = chunk
            return last

        return asyncio.run(_run())

    async def _astream_with_hil(self, state: WorkflowState, auto_approve: bool, on_hil, config=None):
        """OTB streaming with Command(resume=...) pattern.

        OOTB flow:
        1. graph.stream(input_state, config) — streams chunks until interrupt() or completion
        2. On GraphInterrupt: get state, call on_hil(), resume with Command(resume=...)
        3. Repeat until graph completes

        This replaces the old _astream_with_hil + aupdate_state pattern with
        LangGraph's native interrupt/resume lifecycle.
        """
        import time as _time
        import uuid as _uuid
        from langgraph.errors import GraphInterrupt
        from langgraph.types import Command

        if config is None:
            config = {"configurable": {"thread_id": str(_uuid.uuid4())}}

        current_phase = None
        phase_start: Dict[str, float] = {}
        input_state = state

        while True:
            try:
                # Stream execution until interrupt or completion
                async for chunk in self.graph.astream(
                    input_state, stream_mode="values", config=config
                ):
                    phase = chunk.get("phase", "UNKNOWN")

                    if phase != current_phase:
                        # Phase transition — record previous phase timing
                        if current_phase and current_phase in phase_start:
                            duration = round(_time.time() - phase_start[current_phase], 3)
                            success = chunk.get("error") is None
                            tracer.record_phase(current_phase, duration, success, project=state.get("project_name"))
                            health_module.track_phase(current_phase, duration, success)
                            _run_phase_eval(current_phase, chunk)
                            w = get_stream_writer() or (lambda **kw: None)
                            w({"type": "progress", "phase": current_phase, "step": "status", "detail": f"Completed ({duration}s)", "ts": _time.time()})

                        current_phase = phase
                        phase_start[phase] = _time.time()
                        w = get_stream_writer() or (lambda **kw: None)
                        w({"type": "progress", "phase": phase, "step": "status", "detail": "Started...", "ts": _time.time()})
                        health_module.set_current_phase(state.get("project_name"), phase)

                    yield chunk

                # Normal completion (stream ended without exception)
                if current_phase:
                    duration = round(_time.time() - phase_start.get(current_phase, _time.time()), 3)
                    w = get_stream_writer() or (lambda **kw: None)
                    w({"type": "progress", "phase": current_phase, "step": "status", "detail": f"Completed ({duration}s)", "ts": _time.time()})
                break

            except GraphInterrupt as e:
                log_event(logger, "graph.interrupted", phase=current_phase, detail=str(e))
                w = get_stream_writer() or (lambda **kw: None)
                w({"type": "progress", "phase": current_phase or "UNKNOWN", "step": "interrupt", "detail": "GraphInterrupt caught", "ts": _time.time()})

                # Get the suspended state
                graph_state = await self.graph.aget_state(config)

                # Check if this is a true suspension or normal end
                if not graph_state.next:
                    if current_phase:
                        w = get_stream_writer() or (lambda **kw: None)
                        w({"type": "progress", "phase": current_phase, "step": "status", "detail": "Completed", "ts": _time.time()})
                    break

                # Determine the interrupted phase
                current_chunk = graph_state.values or {}
                interrupted_phase = (
                    current_chunk.get("phase")
                    or current_chunk.get("next_phase")
                    or current_phase
                    or "UNKNOWN"
                )

                # Collect HIL input
                input_data = await on_hil(interrupted_phase, current_chunk)

                # Build resume payload based on phase
                if interrupted_phase == "DISCOVER":
                    # Determine which pause fired: project_setup (Pause 1) or interview (Pause 2)
                    # Check the _pause marker from the CLI handler, or fall back to
                    # checking if interview_keys are present in the data.
                    if isinstance(input_data, dict):
                        pause_type = input_data.get("_pause", "")
                    else:
                        pause_type = ""

                    is_interview_pause = pause_type == "interview"
                    is_setup_pause = pause_type == "project_setup" or not is_interview_pause

                    if is_setup_pause:
                        # Pause 1 resolved: project_name, project_description, context_folder
                        existing = (current_chunk.get("artifacts") or {}).copy()
                        existing["discover_hil_count"] = existing.get("discover_hil_count", 0) + 1

                        resume_data = {
                            "human_approval_required": False,
                            "artifacts": existing,
                        }
                        if isinstance(input_data, dict):
                            if input_data.get("project_name"):
                                resume_data["project_name"] = input_data["project_name"]
                            if input_data.get("project_description"):
                                resume_data["project_description"] = input_data["project_description"]
                            if "context_folder" in input_data:
                                resume_data["context_folder"] = input_data["context_folder"]
                        # Do NOT set discover_interview_done — Pause 2 still needs to fire

                    elif is_interview_pause:
                        # Pause 2 resolved: actual interview answers
                        notes = input_data.get("interview_notes", "") if isinstance(input_data, dict) else ""

                        existing = (current_chunk.get("artifacts") or {}).copy()
                        existing["interview_notes"] = notes
                        existing["discover_interview_done"] = True
                        existing["discover_hil_count"] = existing.get("discover_hil_count", 0) + 1

                        resume_data = {
                            "human_approval_required": False,
                            "interview_notes": notes,
                            "discover_interview_done": True,
                            "artifacts": existing,
                        }

                elif interrupted_phase == "ARCH_REVIEW":
                    # ARCH_REVIEW: approve → BUILD, reject with comments → back to PLAN
                    if isinstance(input_data, str):
                        answer = input_data.strip().lower()
                    elif isinstance(input_data, dict):
                        answer = input_data.get("approved", True)
                        if isinstance(answer, bool):
                            resume_data = {
                                "approved": answer,
                                "feedback": input_data.get("feedback", input_data.get("user_review_comments", "")),
                            }
                            w = get_stream_writer() or (lambda **kw: None)
                            w({"type": "progress", "phase": "ARCH_REVIEW", "step": "resume", "detail": f"approved={answer}", "ts": _time.time()})
                            input_state = Command(resume=[resume_data])
                            continue
                        answer = str(answer).lower()
                    else:
                        answer = str(input_data).lower()

                    approved = answer in ("y", "yes", True)
                    resume_data = {
                        "approved": approved,
                        "feedback": input_data.get("feedback", "") if isinstance(input_data, dict) else "",
                    }
                    w = get_stream_writer() or (lambda **kw: None)
                    w({"type": "progress", "phase": "ARCH_REVIEW", "step": "resume", "detail": f"approved={approved}", "ts": _time.time()})
                    input_state = Command(resume=[resume_data])
                    continue

                else:
                    # Generic HIL phase
                    if auto_approve:
                        resume_data = {"human_approval_required": False, "approved": True}
                    else:
                        resume_data = {"human_approval_required": False}

                # OOTB resume: use Command(resume=...) to continue from interrupt()
                w = get_stream_writer() or (lambda **kw: None)
                w({"type": "progress", "phase": interrupted_phase, "step": "resume", "detail": "Resuming with Command(resume=...)", "ts": _time.time()})
                input_state = Command(resume=resume_data)
                continue

            except Exception as e:
                log_event(logger, "stream.error", error=str(e))
                w = get_stream_writer() or (lambda **kw: None)
                w({"type": "progress", "phase": "STREAM", "step": "error", "detail": str(e), "ts": _time.time()})
                break

    # ── CLI HIL handlers ──

    async def _hil_cli(self, phase: str, state: WorkflowState):  # type: ignore[override]
        """CLI handler for HIL — collects user input via stdin/stdout."""
        # Auto-approve: skip input() entirely — return generated defaults
        if self.auto_approve:
            return self._hil_auto_approve(phase, state)

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, self._hil_cli_sync, phase, state)
        return result

    def _hil_auto_approve(self, phase: str, state: WorkflowState) -> dict:
        """Generate automatic responses when auto_approve=True."""
        w = get_stream_writer() or (lambda **kw: None)
        w({"type": "progress", "phase": phase, "step": "auto_approve", "detail": "Auto-approving HIL gate", "ts": time.time()})

        if phase == "DISCOVER":
            hil_count = (state or {}).get("artifacts", {}).get("discover_hil_count", 0) or 0
            if hil_count == 0:
                # Setup pause — extract from state
                return {
                    "project_name": (state or {}).get("project_name", "crm_test"),
                    "project_description": (state or {}).get("project_description", ""),
                    "context_folder": (state or {}).get("context_folder", ""),
                    "_pause": "project_setup",
                }
            else:
                # Interview pause — generate answers from spec
                spec = (state or {}).get("spec_text", "")
                interview = {
                    "core_behavior": "",
                    "data_model": "",
                    "api_surface": "",
                    "validation": "",
                    "ui_template": "",
                    "integration": "",
                    "deployment": "",
                    "edge_cases": "",
                    "non_functional": "",
                }
                if spec:
                    interview["core_behavior"] = spec
                interview["discover_hil_count"] = hil_count + 1
                return {"interview_notes": json.dumps(interview), "discover_interview_done": True}

        if phase == "ARCH_REVIEW":
            return {"approved": True, "feedback": "Auto-approved"}

        # Generic HIL
        return {"human_approval_required": False, "approved": True}

    def _hil_cli_sync(self, phase: str, state: WorkflowState):  # type: ignore[override]
        """Synchronous part that actually blocks on input()."""
        w = get_stream_writer() or (lambda **kw: None)
        w({"type": "progress", "phase": phase, "step": "hil", "detail": "Human Input Required", "ts": time.time()})

        if phase == "DISCOVER":
            # Determine which interrupt fired by checking the suspended state
            # for discover_hil_count — Pause 1 = 0, Pause 2 = 1+
            hil_count = (state or {}).get("artifacts", {}).get("discover_hil_count", 0) or 0
            if hil_count == 0:
                return self._cli_project_setup(state)
            return self._cli_interview(state)

        if phase == "ARCH_REVIEW":
            return self._cli_review(state)

        answer = input(f"  Approve {phase}? (y/n): ").strip().lower()
        if answer == "y":
            return {"approved": True}
        elif answer == "n":
            feedback = input("  Feedback: ").strip()
            return {"approved": False, "feedback": feedback}
        return {"approved": True}

    def _cli_project_setup(self, state=None) -> Dict[str, str]:
        """Pause 1: collect project name, description, context folder."""
        answers = {}

        project_name = (state or {}).get("project_name", "") or ""
        while not project_name:
            project_name = input("  Project name: ").strip()
        answers["project_name"] = project_name

        project_description = (state or {}).get("project_description", "") or ""
        while not project_description:
            project_description = input("  Project description: ").strip()
        answers["project_description"] = project_description

        default_context = (state or {}).get("context_folder", "") or ""
        hint = default_context or "(leave empty for greenfield)"
        context_folder = input(f"  Existing codebase path [{hint}]: ").strip()
        if not context_folder and default_context:
            context_folder = default_context
        answers["context_folder"] = context_folder

        # Mark this as project_setup response (not interview)
        answers["_pause"] = "project_setup"
        return answers

    def _cli_interview(self, state=None) -> Dict[str, str]:
        """Pause 2: collect detailed interview answers."""
        answers = {}

        questions = [
            ("core_behavior", "What does this feature do?"),
            ("data_model", "What entities and fields are involved?"),
            ("api_surface", "What HTTP methods, paths, and auth requirements?"),
            ("validation", "What input validation rules?"),
            ("ui_template", "Any Jinja2 templates or UI requirements?"),
            ("integration", "External services, databases, or APIs?"),
            ("deployment", "Docker or infrastructure implications?"),
            ("edge_cases", "Known edge cases?"),
            ("non_functional", "Performance, security, or monitoring needs?"),
        ]

        for key, q in questions:
            val = input(f"  {q} (or Enter to skip): ").strip()
            if val:
                answers[key] = val

        lines = ["Interview answers:"]
        for key, val in answers.items():
            lines.append(f"  {key}: {val}")
        answers["interview_notes"] = "\n".join(lines)

        # Mark this as interview response
        answers["_pause"] = "interview"
        return answers

    def _cli_review(self, state) -> dict:
        """CLI handler for ARCH_REVIEW phase — render artifacts for human review."""
        artifacts = (state or {}).get("artifacts", {})
        diagrams = artifacts.get("diagrams", {})
        diagram_pngs = artifacts.get("diagram_pngs", {})

        # Render plan summary
        plan = artifacts.get("plan", "")[:500]
        tasks = artifacts.get("tasks", "")[:500]
        analysis = artifacts.get("analysis", "")[:300]

        w = get_stream_writer() or (lambda **kw: None)
        w({"type": "progress", "phase": "ARCH_REVIEW", "step": "display", "detail": "ARCHITECTURE & PLAN REVIEW", "ts": time.time()})
        w({"type": "progress", "phase": "ARCH_REVIEW", "step": "display", "detail": f"Spec: {len(artifacts.get('spec_refined', ''))} chars", "ts": time.time()})
        w({"type": "progress", "phase": "ARCH_REVIEW", "step": "display", "detail": f"Plan: {len(plan)} chars preview → {plan[:120]}...", "ts": time.time()})
        w({"type": "progress", "phase": "ARCH_REVIEW", "step": "display", "detail": f"Tasks: {len(tasks)} chars", "ts": time.time()})
        if analysis:
            w({"type": "progress", "phase": "ARCH_REVIEW", "step": "display", "detail": f"Analysis: {analysis[:120]}...", "ts": time.time()})
        if diagrams:
            w({"type": "progress", "phase": "ARCH_REVIEW", "step": "display", "detail": f"Diagrams: {', '.join(diagrams.keys())}", "ts": time.time()})
            for dtype, png_path in diagram_pngs.items():
                status = "✓ rendered" if png_path else "✗ no PNG"
                w({"type": "progress", "phase": "ARCH_REVIEW", "step": "display", "detail": f"- {dtype}: {status}", "ts": time.time()})
        w({"type": "progress", "phase": "ARCH_REVIEW", "step": "display", "detail": "End of review", "ts": time.time()})

        answer = input("  Approve architecture & plan? (y/n): ").strip().lower()
        if answer == "y":
            return {"approved": True, "feedback": ""}
        elif answer == "n":
            feedback = input("  Feedback for PLAN (will be sent back for regeneration): ").strip()
            return {"approved": False, "feedback": feedback}
        return {"approved": True, "feedback": ""}


