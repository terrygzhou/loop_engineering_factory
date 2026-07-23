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
import os
import sys
import time
from pathlib import Path
from typing import Dict

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
    """Build initial WorkflowState with pre-loaded skill registry."""
    skills_dir = get_skills_dir()
    skill_registry = build_skill_registry(skills_dir)

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
            "skill_registry": skill_registry,
            "loop_counts": {},
            "project_name": project_name,
        },
        feedback=[],
        error=None,
        spec_path=spec_text,
        project_path=get_project_path(),
        skip_discover=skip_discover,
        context_folder=context_folder,
        human_approval_required=False,
        improve_mode=improve_mode,
        pending_inputs=[],
        input_responses={},
        input_timeout_s=300,
        auto_approve_timeout=True,
        diagrams={},
        diagram_status="pending",
        diagram_feedback="",
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
        if auto_approve:
            state["diagram_status"] = "approved"

        log_event(logger, "workflow.run", project=project_name, skip_discover=state.get("skip_discover"))

        if state.get("skip_discover"):
            print("\n[DISCOVER] Skipped — no context folder (greenfield mode)\n")
        else:
            print(f"\n[DISCOVER] Scanning {context_folder}...")

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
                async for chunk in self.graph.stream(
                    input_state, stream_mode="values", config=config
                ):
                    phase = chunk.get("phase", "UNKNOWN")

                    if phase != current_phase:
                        # Phase transition — record previous phase timing
                        if current_phase and current_phase in phase_start:
                            duration = round(time.time() - phase_start[current_phase], 3)
                            success = chunk.get("error") is None
                            tracer.record_phase(current_phase, duration, success, project=state.get("project_name"))
                            health_module.track_phase(current_phase, duration, success)
                            _run_phase_eval(current_phase, chunk)
                            print(f"\n[{current_phase}] Completed ({duration}s)")

                        current_phase = phase
                        phase_start[phase] = time.time()
                        print(f"[{phase}] Started...")
                        health_module.set_current_phase(state.get("project_name"), phase)

                    yield chunk

                # Normal completion (stream ended without exception)
                if current_phase:
                    duration = round(time.time() - phase_start.get(current_phase, time.time()), 3)
                    print(f"\n[{current_phase}] Completed ({duration}s)\n")
                break

            except GraphInterrupt as e:
                log_event(logger, "graph.interrupted", phase=current_phase, detail=str(e))
                print(f"  → GraphInterrupt caught")

                # Get the suspended state
                graph_state = await self.graph.aget_state(config)

                # Check if this is a true suspension or normal end
                if not graph_state.next:
                    if current_phase:
                        print(f"\n[{current_phase}] Completed\n")
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
                    # Extract interview notes
                    if isinstance(input_data, str):
                        notes = input_data
                    elif isinstance(input_data, dict):
                        notes = input_data.get("interview_notes") or input_data.get("raw_input") or ""
                    else:
                        notes = str(input_data)

                    # Build update for OOTB resume
                    existing = (current_chunk.get("artifacts") or {}).copy()
                    existing["user_input"] = input_data
                    existing["interview_notes"] = notes
                    existing["discover_interview_done"] = True
                    existing["discover_hil_count"] = existing.get("discover_hil_count", 0) + 1

                    resume_data = {
                        "human_approval_required": False,
                        "interview_notes": notes or "",
                        "discover_interview_done": True,
                        "artifacts": existing,
                    }
                    if isinstance(input_data, dict):
                        if input_data.get("project_name"):
                            resume_data["project_name"] = input_data["project_name"]
                        if input_data.get("project_description"):
                            resume_data["project_description"] = input_data["project_description"]

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
                            print(f"  → ARCH_REVIEW resumed: approved={answer}")
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
                    print(f"  → ARCH_REVIEW resumed: approved={approved}")
                    input_state = Command(resume=[resume_data])
                    continue

                else:
                    # Generic HIL phase
                    if auto_approve:
                        resume_data = {"human_approval_required": False, "approved": True}
                    else:
                        resume_data = {"human_approval_required": False}

                # OOTB resume: use Command(resume=...) to continue from interrupt()
                print(f"  → Resuming {interrupted_phase} with Command(resume=...)")
                input_state = Command(resume=resume_data)
                continue

            except Exception as e:
                log_event(logger, "stream.error", error=str(e))
                print(f"  → Stream error: {e}")
                break

    # ── CLI HIL handlers ──

    async def _hil_cli(self, phase: str, state: WorkflowState):  # type: ignore[override]
        """CLI handler for HIL — collects user input via stdin/stdout."""
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, self._hil_cli_sync, phase, state)
        return result

    def _hil_cli_sync(self, phase: str, state: WorkflowState):  # type: ignore[override]
        """Synchronous part that actually blocks on input()."""
        print(f"\n  === {phase}: Human Input Required ===")

        if phase == "DISCOVER":
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

    def _cli_review(self, state) -> dict:
        """CLI handler for REVIEW phase — render artifacts for human review."""
        artifacts = (state or {}).get("artifacts", {})
        diagrams = artifacts.get("diagrams", {})
        diagram_pngs = artifacts.get("diagram_pngs", {})

        # Render plan summary
        plan = artifacts.get("plan", "")[:500]
        tasks = artifacts.get("tasks", "")[:500]
        analysis = artifacts.get("analysis", "")[:300]

        print("\n  ┌─ ARCHITECTURE & PLAN REVIEW ──────────────────────────────")
        print(f"  │ Spec: {len(artifacts.get('spec_refined', ''))} chars")
        print(f"  │ Plan: {len(plan)} chars preview → {plan[:120]}...")
        print(f"  │ Tasks: {len(tasks)} chars")
        if analysis:
            print(f"  │ Analysis: {analysis[:120]}...")

        # Show diagram availability
        if diagrams:
            print(f"  │ Diagrams: {', '.join(diagrams.keys())}")
            for dtype, png_path in diagram_pngs.items():
                status = "✓ rendered" if png_path else "✗ no PNG"
                print(f"  │   - {dtype}: {status}")

        print(f"  └────────────────────────────────────────────────────────────\n")

        answer = input("  Approve architecture & plan? (y/n): ").strip().lower()
        if answer == "y":
            return {"approved": True, "feedback": ""}
        elif answer == "n":
            feedback = input("  Feedback for PLAN (will be sent back for regeneration): ").strip()
            return {"approved": False, "feedback": feedback}
        return {"approved": True, "feedback": ""}

    def _cli_interview(self, state=None) -> Dict[str, str]:
        """Ask for project name, description, and interview questions."""
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
            if key not in ("project_name", "project_description"):
                lines.append(f"  {key}: {val}")
        answers["interview_notes"] = "\n".join(lines)
        answers["approved"] = True
        return answers


