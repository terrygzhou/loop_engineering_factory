"""
Shared executor — singleton workflow core for both CLI (main.py) and Web (app.py).

Both modes import this module. Graph construction, state initialization, and
node execution are identical. Only the UX layer (CLI prompts vs WebSocket) differs.
"""
import asyncio
import sys
import time
from pathlib import Path
from typing import Dict, Optional

# Ensure project root is on path so config.loader resolves
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from config.loader import config  # noqa: E402
from graph.main import build_graph  # noqa: E402
from graph.state import CycleMetrics, WorkflowState  # noqa: E402
from langgraph.checkpoint.memory import MemorySaver  # noqa: E402
from tools.loader import build_skill_registry  # noqa: E402

# ── Observability ──
from service.otel_instrumentor import tracer  # noqa: E402
from service import health as health_module  # noqa: E402
from log.logging import setup_logger, log_event  # noqa: E402

logger = setup_logger("executor")


def get_skills_dir() -> str:
    """Resolve skills directory — config > Docker mount > local default."""
    sd = config.paths.skills_dir
    if Path("/app/skills").exists():
        return "/app/skills"
    return sd


def get_project_path() -> str:
    """Resolve project output directory from config (env var > config.yaml > default)."""
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
    log_event(logger, "executor.skills_loading", skills_dir=skills_dir)
    skill_registry = build_skill_registry(skills_dir)
    log_event(logger, "executor.skills_loaded", count=len(skill_registry))

    skip_discover = not bool(context_folder) and not improve_mode

    return WorkflowState(
        cycle_id=cycle_id,
        phase="DISCOVER",
        next_phase="DEFINE",
        project_name=project_name,
        metrics=CycleMetrics(
            spec_confidence=0.0,
            arch_uncertainty=0.0,
            task_count=0,
            review_revisions=0,
            security_findings=0,
            uat_pass_rate=0.0,
            latency_ms=0.0,
            test_flakiness_rate=0.0,
            launch_success=False,
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
        # B-009: Non-blocking input
        pending_inputs=[],
        input_responses={},
        input_timeout_s=300,
        auto_approve_timeout=True,
        # B-010: Architecture diagrams
        diagrams={},
        diagram_status="pending",
        diagram_feedback="",
        arch_review_approved=False,
    )


def get_graph(checkpointer=None, auto_approve=False):
    """Build and compile the LangGraph workflow."""
    return build_graph(checkpointer=checkpointer, auto_approve=auto_approve)


class WorkflowRunner:
    """Shared workflow runner for CLI and Web modes."""

    HIL_PHASES = {"DISCOVER", "HUMAN_REVIEW", "ARCH_REVIEW", "PLAN"}

    def __init__(self, auto_approve=False):
        import uuid as _uuid
        self.checkpointer = MemorySaver()
        self.graph = get_graph(checkpointer=self.checkpointer, auto_approve=auto_approve)
        self.thread_id = str(_uuid.uuid4())
        self.auto_approve = auto_approve

    def run_interactive(
        self,
        project_name: str,
        spec_text: str = "",
        context_folder: str = "",
        auto_approve: bool = False,
        improve_mode: bool = False,
    ):
        """Run the workflow synchronously with observability instrumentation."""
        cycle_id = "1"
        state = build_executor_state(
            cycle_id=cycle_id,
            project_name=project_name,
            spec_text=spec_text,
            context_folder=context_folder,
            improve_mode=improve_mode,
        )
        # Pre-set auto-approval flags so ARCH_REVIEW passes through without interrupt
        if auto_approve:
            state["arch_review_approved"] = True
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

        result = asyncio.run(_run())
        return result

    async def _astream_with_hil(self, state: WorkflowState, auto_approve: bool, on_hil, config=None):
        """Stream graph execution with HIL gates via LangGraph interrupt_after."""
        import uuid as _uuid
        from langgraph.errors import GraphInterrupt

        if config is None:
            config = {"configurable": {"thread_id": str(_uuid.uuid4())}}

        current_phase = None
        phase_start: Dict[str, float] = {}
        input_state = state

        while True:
            try:
                async for chunk in self.graph.astream(
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
                            log_event(logger, "phase.completed", phase=current_phase, duration_s=duration, success=success)
                            print(f"\n[{current_phase}] Completed ({duration}s)")

                        current_phase = phase
                        phase_start[phase] = time.time()
                        print(f"[{phase}] Started...")
                        log_event(logger, "phase.started", phase=phase)
                        health_module.set_current_phase(state.get("project_name"), phase)

                    yield chunk

            except GraphInterrupt as e:
                log_event(logger, "graph.interrupted", phase=current_phase, detail=str(e))
                print(f"  → GraphInterrupt caught: {e}")
                graph_state = await self.graph.aget_state(config)
                is_interrupted = graph_state.next is not None and len(graph_state.next) > 0

                if not is_interrupted:
                    if current_phase:
                        print(f"\n[{current_phase}] Completed\n")
                    break

                next_nodes = graph_state.next
                interrupted_phase = current_phase
                current_chunk = graph_state.values or {}

                if not current_chunk:
                    print(f"  → WARNING: graph_state.values is None for phase {interrupted_phase}")

                if interrupted_phase and interrupted_phase in self.HIL_PHASES:
                    # DISCOVER always needs HIL (interview), regardless of human_approval_required flag
                    needs_approval = (
                        interrupted_phase == "DISCOVER"
                        or current_chunk.get("human_approval_required", False)
                    )

                    if needs_approval:
                        try:
                            # ── DISCOVER: interview gate ──
                            if interrupted_phase == "DISCOVER":
                                if auto_approve:
                                    print(f"  → Auto-approved {interrupted_phase}")
                                    interview_answers = self._default_interview(graph_state.values or {})
                                    # Set resume flag + notes so DISCOVER node doesn't loop
                                    existing_artifacts = (current_chunk.get("artifacts") or {}).copy()
                                    existing_artifacts["interview_notes"] = interview_answers
                                    existing_artifacts["discover_interview_done"] = True
                                    update = {
                                        "human_approval_required": False,
                                        "interview_notes": interview_answers,
                                        "artifacts": existing_artifacts,
                                    }
                                else:
                                    input_data = await on_hil(interrupted_phase, current_chunk)
                                    update = {"human_approval_required": False}
                                    if input_data:
                                        # Store at top level for reliable LangGraph shallow merge
                                        notes = input_data.get("interview_notes", "")
                                        if notes:
                                            update["interview_notes"] = notes
                                        existing = (current_chunk.get("artifacts") or {}).copy()
                                        existing["user_input"] = input_data
                                        existing["interview_notes"] = notes
                                        update["artifacts"] = existing
                            # ── ARCH_REVIEW: approval gate ──
                            elif interrupted_phase == "ARCH_REVIEW":
                                if auto_approve:
                                    print(f"  → Auto-approved {interrupted_phase}")
                                    update = {
                                        "human_approval_required": False,
                                        "diagram_status": "approved",
                                        "arch_review_approved": True,
                                    }
                                else:
                                    input_data = await on_hil(interrupted_phase, current_chunk)
                                    update = {"human_approval_required": False}
                                    if input_data:
                                        existing = (current_chunk.get("artifacts") or {}).copy()
                                        existing["user_input"] = input_data
                                        approved = input_data.get("arch_review_approved", False)
                                        update["arch_review_approved"] = approved
                                        update["diagram_status"] = "approved" if approved else "rejected"
                                        if input_data.get("diagram_feedback"):
                                            update["diagram_feedback"] = input_data["diagram_feedback"]
                                            update["user_review_comments"] = input_data["diagram_feedback"]
                                        if input_data.get("section_feedback"):
                                            for key, feedback in input_data["section_feedback"].items():
                                                if feedback.get("edited") and feedback.get("content") is not None:
                                                    existing[key] = feedback["content"]
                                        update["artifacts"] = existing
                            # ── Other HIL phases ──
                            else:
                                if auto_approve:
                                    print(f"  → Auto-approved {interrupted_phase}")
                                    interview_answers = self._default_interview(graph_state.values or {})
                                    update = {
                                        "human_approval_required": False,
                                        "diagram_status": "approved",
                                        "arch_review_approved": True,
                                        "artifacts": {
                                            **(current_chunk.get("artifacts") or {}),
                                            "interview_notes": interview_answers,
                                            "user_input": {"approved": True},
                                        },
                                    }
                                else:
                                    input_data = await on_hil(interrupted_phase, current_chunk)
                                    update = {"human_approval_required": False}
                                    if input_data:
                                        existing = (current_chunk.get("artifacts") or {}).copy()
                                        existing["user_input"] = input_data
                                        if "interview_notes" in input_data:
                                            existing["interview_notes"] = input_data["interview_notes"]
                                        if interrupted_phase == "HUMAN_REVIEW" and input_data.get("section_feedback"):
                                            existing["human_review_feedback"] = input_data["section_feedback"]
                                            for key, feedback in input_data["section_feedback"].items():
                                                if feedback.get("edited") and feedback.get("content") is not None:
                                                    existing[key] = feedback["content"]
                                        update["artifacts"] = existing
                        except Exception as e:
                            log_event(logger, "hil.error", phase=interrupted_phase, error=str(e))
                            print(f"  → HIL error: {type(e).__name__}: {e}")
                            import traceback
                            traceback.print_exc()
                            update = {"human_approval_required": False}
                    else:
                        update = None

                    if update:
                        await self.graph.aupdate_state(config, update)
                        print(f"  → State updated: resuming to {next_nodes}")

                input_state = None
                continue

    def _default_interview(self, state: WorkflowState) -> str:
        """Generate default interview notes when auto-approving."""
        project_name = state.get("artifacts", {}).get("project_name", "Untitled")
        spec = state.get("spec_path", "") or ""
        return (
            f"Auto-generated interview for '{project_name}':\n"
            f"Core behavior: {spec}\n"
            f"Data model: Standard CRUD\n"
            f"API surface: RESTful endpoints\n"
            f"Validation: Standard input validation\n"
            f"Integration: None specified\n"
            f"Deployment: Docker Compose\n"
            f"Edge cases: Standard error handling\n"
            f"Non-functional: Standard performance targets\n"
        )

    async def _hil_cli(self, phase: str, state: WorkflowState) -> Optional[Dict[str, str]]:
        """CLI handler for HIL — collects user input via stdin/stdout."""
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, self._hil_cli_sync, phase, state)
        return result

    def _hil_cli_sync(self, phase: str, state: WorkflowState) -> Optional[Dict[str, str]]:
        """Synchronous part that actually blocks on input()."""
        print(f"\n  === {phase}: Human Input Required ===")

        if phase == "DISCOVER":
            return self._cli_interview()
        elif phase == "HUMAN_REVIEW":
            return self._cli_human_review(state)
        elif phase == "ARCH_REVIEW":
            return self._cli_arch_review(state)
        elif phase == "DEFINE":
            return self._cli_interview()
        else:
            answer = input(f"  Approve {phase}? (y/n): ").strip().lower()
            if answer == "y":
                return {"approved": True}
            elif answer == "n":
                feedback = input("  Feedback: ").strip()
                return {"approved": False, "feedback": feedback}
            return {"approved": True}

    def _cli_human_review(self, state: WorkflowState) -> dict:
        """Display full DEFINE output for human review with per-section approval."""
        from graph.nodes.review_contract import (
            build_review_sections,
            format_review_summary_for_cli,
            format_review_section_for_cli,
            make_review_result,
        )

        artifacts = state.get("artifacts", {})
        sections = build_review_sections(artifacts)

        print("\n  === Human Review: Approve Each Section ===\n")
        print(format_review_summary_for_cli(sections))

        section_feedback = {}
        for sec in sections:
            key = sec["key"]
            title = sec["label"].upper()
            content = sec["content"]

            if content:
                print(format_review_section_for_cli(title, content))
            else:
                print(f"\n  [{title}]: (not provided)")

            answer = input(f"\n  Approve {title}? (y/n/e=edit): ").strip().lower()

            if answer == "e":
                print(f"  Enter revised {title.lower()} (end with empty line):\n")
                edits = []
                while True:
                    line = input()
                    if not line:
                        break
                    edits.append(line)
                if edits:
                    new_content = "\n".join(edits)
                    artifacts[key] = new_content
                    print(f"  ✓ {title} updated with {len(edits)} lines")
                    section_feedback[key] = {"approved": True, "edited": True, "content": new_content}
                else:
                    section_feedback[key] = {"approved": True, "edited": False}
            elif answer == "y":
                section_feedback[key] = {"approved": True}
            elif answer == "n":
                comment = input(f"  Feedback for {title}: ").strip()
                section_feedback[key] = {"approved": False, "comment": comment}
            else:
                section_feedback[key] = {"approved": True}

        result = make_review_result(section_feedback)
        state["artifacts"]["human_review_feedback"] = section_feedback
        return result.to_dict()

    def _cli_arch_review(self, state: WorkflowState) -> dict:
        """Display full Plan outputs for architecture review.\n\n        Shows specification, implementation plan, task breakdown, and\n        architecture diagrams — exactly the same sections that\n        arch_review_node collects.
        """
        from graph.nodes.review_contract import (
            format_review_summary_for_cli,
            format_review_section_for_cli,
            make_review_result,
        )

        artifacts = state.get("artifacts", {})
        diagrams = state.get("diagrams", {})

        # Collect all Plan artifacts for review
        review_sections = []

        # 1. Specification
        spec = artifacts.get("spec_refined", "")
        if spec:
            review_sections.append({
                "key": "spec_refined",
                "label": "Specification",
                "content": spec,
                "word_count": len(spec.split()),
            })

        # 2. Implementation Plan
        plan = artifacts.get("plan", "")
        if plan:
            review_sections.append({
                "key": "plan",
                "label": "Implementation Plan",
                "content": plan,
                "word_count": len(plan.split()),
            })

        # 3. Task Breakdown
        tasks = artifacts.get("tasks", "")
        if tasks:
            review_sections.append({
                "key": "tasks",
                "label": "Task Breakdown",
                "content": tasks,
                "word_count": len(tasks.split()),
            })

        # 4. Architecture Diagrams
        if diagrams:
            diagram_content = ""
            for name, path in diagrams.items():
                diagram_content += f"\n### {name}\n"
                try:
                    from pathlib import Path
                    diagram_content += Path(path).read_text()
                except Exception:
                    diagram_content += f"(diagram file: {path})"
            review_sections.append({
                "key": "diagrams",
                "label": "Architecture Diagrams",
                "content": diagram_content,
                "word_count": len(diagram_content.split()),
            })

        print("\n  === Architecture Review ===")
        print(f"  Sections to review: {len(review_sections)}")
        print(format_review_summary_for_cli(review_sections))

        # Show full content for each section
        section_feedback = {}
        for sec in review_sections:
            key = sec["key"]
            title = sec["label"].upper()
            content = sec["content"]

            print(format_review_section_for_cli(title, content))

            answer = input(f"\n  Approve {title}? (y/n/e=edit): ").strip().lower()

            if answer == "e":
                print(f"  Enter revised {title.lower()} (end with empty line):\n")
                edits = []
                while True:
                    line = input()
                    if not line:
                        break
                    edits.append(line)
                if edits:
                    new_content = "\n".join(edits)
                    artifacts[key] = new_content
                    print(f"  ✓ {title} updated with {len(edits)} lines")
                    section_feedback[key] = {"approved": True, "edited": True, "content": new_content}
                else:
                    section_feedback[key] = {"approved": True, "edited": False}
            elif answer == "y":
                section_feedback[key] = {"approved": True}
            elif answer == "n":
                comment = input(f"  Feedback for {title}: ").strip()
                section_feedback[key] = {"approved": False, "comment": comment}
            else:
                section_feedback[key] = {"approved": True}

        result = make_review_result(section_feedback)
        state["artifacts"]["arch_review_feedback"] = section_feedback

        # Preserve diagram paths in state
        if diagrams:
            state["artifacts"]["diagrams"] = diagrams
            state["diagrams"] = diagrams

        if result.approved:
            return {"approved": True, "arch_review_approved": True, "section_feedback": section_feedback}
        else:
            feedback_text = "; ".join(
                fb.get("comment", "") for fb in section_feedback.values() if not fb.get("approved", True)
            )
            return {
                "approved": False,
                "feedback": feedback_text,
                "arch_review_approved": False,
                "diagram_feedback": feedback_text,
                "section_feedback": section_feedback,
            }

    def _cli_interview(self) -> Dict[str, str]:
        """Ask interview questions from interview-me skill."""
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

        answers = {}
        for key, q in questions:
            val = input(f"  {q} (or Enter to skip): ").strip()
            if val:
                answers[key] = val

        lines = ["Interview answers:"]
        for key, val in answers.items():
            lines.append(f"  {key}: {val}")
        answers["interview_notes"] = "\n".join(lines)
        answers["approved"] = True

        return answers
