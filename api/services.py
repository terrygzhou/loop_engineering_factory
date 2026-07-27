"""
Loop Engineering — Workflow Service Layer

Executes the LangGraph workflow via WorkflowRunner and bridges HIL
interrupts to the frontend over WebSocket.
"""
import asyncio
import json
import time
import uuid
from typing import Optional, Dict, List

from api.middleware.logging import log_request
from api.input_manager import InputManager


class WorkflowService:
    """Service layer for workflow interactions — shared by CLI, Frontend, and API."""

    def __init__(self):
        self._workflows: dict[str, dict] = {}
        self._history: list[dict] = []
        self._websockets: list[dict] = []
        self._input_manager = InputManager(default_timeout_s=300, auto_approve_on_timeout=True)
        self._tasks: dict[str, asyncio.Task] = {}  # workflow_id → background task
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._skill_progress: dict[str, list[dict]] = {}  # workflow_id → skill events

    async def start(self, project_name: str, spec_text: str = "", context_folder: Optional[str] = None) -> dict:
        """Start a new workflow and execute it in the background."""
        if not project_name:
            raise ValueError("Project name is required")

        workflow_id = project_name
        from graph.executor import build_executor_state, WorkflowRunner
        from config.loader import config

        state = build_executor_state(
            cycle_id="1",
            project_name=project_name,
            spec_text=spec_text,
            context_folder=context_folder or "",
        )
        # Ensure web mode uses HIL (not auto_approve from Docker env)
        state["artifacts"]["discover_hil_count"] = 0

        self._workflows[workflow_id] = {
            "state": state,
            "started_at": time.time(),
            "status": "initializing",
            "ws_callbacks": {},  # request_id → asyncio.Future
        }
        log_request("workflow.start", workflow_id=workflow_id, project_name=project_name)

        # Launch graph execution in background
        runner = WorkflowRunner(auto_approve=False)
        task = asyncio.create_task(
            self._run_workflow(runner, workflow_id, project_name, spec_text, context_folder)
        )
        self._tasks[workflow_id] = task
        return state

    async def _run_workflow(self, runner, workflow_id, project_name, spec_text, context_folder):
        """Run the graph and bridge HIL pauses to WebSocket."""
        wf = self._workflows.get(workflow_id)
        if not wf:
            return

        wf["status"] = "running"
        self._broadcast_status(workflow_id, "running")

        # Skill progress callback — nodes call this to report skill invocations
        def skill_callback(skill_name: str, event: str, details: dict | None = None):
            self._broadcast_skill_event(workflow_id, skill_name, event, details)

        try:
            # Run via astream_events(version="v3") — typed HIL projections
            from graph.executor import build_executor_state
            from graph.main import build_graph
            from graph.sqlite_saver import SqliteSaver
            import uuid as _uuid
            from langgraph.types import Command

            checkpointer = SqliteSaver.from_conn_string(":memory:")
            graph = build_graph(checkpointer=checkpointer, auto_approve=False)
            thread_id = str(_uuid.uuid4())
            config = {"configurable": {"thread_id": thread_id}}

            state = build_executor_state(
                cycle_id="1",
                project_name=project_name,
                spec_text=spec_text,
                context_folder=context_folder or "",
            )
            state["artifacts"]["discover_hil_count"] = 0
            state["discover_interview_done"] = False
            state["auto_approve_override"] = False  # Web UI always uses HIL
            state["skill_callback"] = skill_callback
            wf["state"] = state

            current_phase = None
            input_state = state

            while True:
                try:
                    async for chunk in graph.stream(
                        input_state, config=config, stream_mode="values"
                    ):
                        phase = chunk.get("phase", "UNKNOWN")
                        if phase != current_phase:
                            if current_phase:
                                wf["state"].setdefault("artifacts", {})["phase_log"] = \
                                    wf["state"].get("artifacts", {}).get("phase_log", []) + \
                                    [{"phase": current_phase, "status": "completed"}]
                            current_phase = phase
                            wf["state"]["phase"] = phase
                            wf["status"] = phase
                            self._broadcast_status(workflow_id, phase)

                        wf["state"] = chunk
                        wf["state"]["phase"] = phase
                        wf["state"]["status"] = phase

                    # Normal completion — no interrupt
                    wf["status"] = "completed"
                    self._broadcast_status(workflow_id, "completed")
                    break

                except Exception as e:
                    from langgraph.errors import GraphInterrupt
                    if not isinstance(e, GraphInterrupt):
                        raise

                    log_request("graph.interrupted", workflow_id=workflow_id, phase=current_phase)
                    graph_state = await graph.aget_state(config)
                    if not graph_state.next:
                        wf["status"] = "completed"
                        self._broadcast_status(workflow_id, "completed")
                        break

                    current_chunk = graph_state.values or {}
                    interrupted_phase = current_chunk.get("phase") or current_chunk.get("next_phase") or current_phase or "UNKNOWN"
                    interrupts = list(graph_state.tasks)
                    interrupt_value = interrupts[0].state.values if interrupts else {}
                    pause_type = self._determine_pause_type(interrupted_phase, interrupt_value)
                    wf["status"] = f"paused:{interrupted_phase}:{pause_type}"
                    self._broadcast_status(workflow_id, f"paused:{interrupted_phase}:{pause_type}")

                    # Broadcast HIL prompt to frontend
                    await self.broadcast({
                        "type": "action",
                        "phase": interrupted_phase,
                        "action": self._get_hil_action(interrupted_phase, pause_type),
                        "data": self._build_hil_data(interrupted_phase, pause_type, interrupt_value),
                        "timestamp": time.time(),
                    })

                    # Wait for user input via WebSocket
                    resume_data = await self._collect_hil_input(
                        workflow_id, interrupted_phase, pause_type, interrupt_value
                    )

                    # Build resume payload
                    resume_map = {}
                    for intr in interrupts:
                        if interrupted_phase in ("DISCOVER", "DISCOVER_SETUP"):
                            if pause_type == "project_setup":
                                mapped = self._build_project_setup_resume(wf["state"], resume_data)
                            else:
                                mapped = self._build_interview_resume(wf["state"], resume_data)
                        elif interrupted_phase == "ARCH_REVIEW":
                            mapped = self._build_review_resume(wf["state"], resume_data)
                        else:
                            mapped = resume_data
                        resume_map[intr.id] = mapped

                    log_request("graph.resumed", workflow_id=workflow_id, phase=interrupted_phase, pause_type=pause_type)
                    input_state = Command(resume=resume_map)
                    continue

        finally:
            if workflow_id in self._tasks:
                del self._tasks[workflow_id]

    def _determine_pause_type(self, phase, chunk):
        """Determine which pause fired for DISCOVER."""
        if phase != "DISCOVER":
            return "review"
        hil_count = (chunk.get("artifacts") or {}).get("discover_hil_count", 0) or 0
        if hil_count == 0:
            return "project_setup"
        return "interview"

    def _build_project_setup_resume(self, chunk, resume_data):
        """Build resume data for project setup pause."""
        existing = (chunk.get("artifacts") or {}).copy()
        existing["discover_hil_count"] = existing.get("discover_hil_count", 0) + 1

        result = {
            "human_approval_required": False,
            "artifacts": existing,
        }
        if resume_data:
            if resume_data.get("project_name"):
                result["project_name"] = resume_data["project_name"]
            if resume_data.get("project_description"):
                result["project_description"] = resume_data["project_description"]
            if "context_folder" in resume_data:
                result["context_folder"] = resume_data["context_folder"]
        return result

    def _build_interview_resume(self, chunk, resume_data):
        """Build resume data for interview pause."""
        notes = resume_data.get("interview_notes", "") if resume_data else ""
        existing = (chunk.get("artifacts") or {}).copy()
        existing["interview_notes"] = notes
        existing["discover_interview_done"] = True
        existing["discover_hil_count"] = existing.get("discover_hil_count", 0) + 1

        return {
            "human_approval_required": False,
            "interview_notes": notes,
            "discover_interview_done": True,
            "artifacts": existing,
        }

    def _build_review_resume(self, chunk, resume_data):
        """Build resume data for ARCH_REVIEW pause."""
        approved = resume_data.get("approved", True) if resume_data else True
        feedback = resume_data.get("feedback", "") if resume_data else ""
        return {
            "approved": approved,
            "feedback": feedback,
        }

    def _get_hil_action(self, phase: str, pause_type: str) -> str:
        """Map interrupt phase/pause_type to frontend action type."""
        if phase == "DISCOVER" and pause_type == "interview":
            return "interview"
        if phase == "DISCOVER" and pause_type == "project_setup":
            return "setup"
        if phase == "ARCH_REVIEW":
            return "review"
        return "input"

    def _build_hil_data(self, phase: str, pause_type: str, interrupt_value: dict) -> dict:
        """Build frontend data for HIL prompts."""
        if phase == "DISCOVER" and pause_type == "interview":
            return interrupt_value.get("questions", []) or {}
        if phase == "DISCOVER" and pause_type == "project_setup":
            return interrupt_value or {}
        if phase == "ARCH_REVIEW":
            return interrupt_value or {}
        return {}

    async def _collect_hil_input(self, workflow_id, phase, pause_type, chunk):
        """Collect HIL input from WebSocket with timeout."""
        wf = self._workflows.get(workflow_id, {})
        future = asyncio.get_event_loop().create_future()
        wf.setdefault("ws_callbacks", {})
        wf["ws_callbacks"][pause_type] = future
        wf["pending_pause"] = {"phase": phase, "type": pause_type}

        try:
            return await asyncio.wait_for(future, timeout=300)
        except asyncio.TimeoutError:
            # Auto-approve on timeout
            if pause_type == "project_setup":
                return {
                    "project_name": chunk.get("project_name", "Untitled"),
                    "project_description": chunk.get("project_description", ""),
                    "context_folder": "",
                }
            elif pause_type == "interview":
                return {
                    "interview_notes": "Auto-approved (timeout). Standard implementation.",
                }
            else:
                return {"approved": True, "feedback": "Auto-approved on timeout"}

    def get_status(self, workflow_id: str = "") -> Optional[dict]:
        """Get current workflow status."""
        if workflow_id and workflow_id in self._workflows:
            return self._workflows[workflow_id]
        for wf in self._workflows.values():
            return wf
        return None

    async def submit_approval(self, workflow_id: str, approved: bool, feedback: str = "", section_feedback: dict = None) -> dict:
        """Submit approval/rejection for a workflow."""
        log_request("approval.submitted", workflow_id=workflow_id, approved=approved)
        wf = self._workflows.get(workflow_id, {})
        # Resolve any pending pause
        pending = wf.get("pending_pause")
        if pending:
            pause_type = pending.get("type", "")
            callbacks = wf.get("ws_callbacks", {})
            future = callbacks.get(pause_type)
            if future and not future.done():
                future.set_result({
                    "approved": approved,
                    "feedback": feedback,
                    "section_feedback": section_feedback or {},
                    "interview_notes": feedback,
                    "project_name": wf["state"].get("project_name", ""),
                    "project_description": wf["state"].get("project_description", ""),
                })

        return {
            "workflow_id": workflow_id,
            "approved": approved,
            "feedback": feedback,
            "section_feedback": section_feedback or {},
        }

    def submit_input(self, workflow_id: str, input_data: dict) -> dict:
        """Submit user input during interview or review."""
        log_request("input.submitted", workflow_id=workflow_id, keys=list(input_data.keys()))
        wf = self._workflows.get(workflow_id, {})
        pending = wf.get("pending_pause")
        if pending:
            pause_type = pending.get("type", "")
            callbacks = wf.get("ws_callbacks", {})
            future = callbacks.get(pause_type)
            if future and not future.done():
                future.set_result(input_data)
        return {
            "workflow_id": workflow_id,
            "input_data": input_data,
        }

    def cancel(self, workflow_id: str = "") -> bool:
        """Cancel an active workflow."""
        if workflow_id in self._tasks:
            self._tasks[workflow_id].cancel()
            del self._tasks[workflow_id]
        if workflow_id in self._workflows:
            log_request("workflow.cancelled", workflow_id=workflow_id)
            del self._workflows[workflow_id]
            return True
        return False

    def get_history(self, limit: int = 10) -> list[dict]:
        """Get workflow history."""
        return self._history[-limit:]

    def get_llm_logs(self, workflow_id: str = "", phase: str = "") -> list[dict]:
        """Get LLM prompt/response logs."""
        return []

    async def register_websocket(self, workflow_id: str, websocket):
        """Register a WebSocket connection for real-time updates."""
        self._websockets.append({"id": workflow_id, "ws": websocket})

    async def unregister_websocket(self, workflow_id: str):
        """Unregister a WebSocket connection."""
        self._websockets = [w for w in self._websockets if w["id"] != workflow_id]

    async def broadcast(self, message: dict):
        """Broadcast a message to all connected WebSockets."""
        for entry in self._websockets[:]:
            try:
                await entry["ws"].send_json(message)
            except Exception:
                pass

    def _broadcast_status(self, workflow_id: str, status: str, chunk: dict = None):
        """Broadcast status update to WebSocket."""
        wf = self._workflows.get(workflow_id, {})
        wf["status"] = status
        artifacts = (wf.get("state") or {}).get("artifacts", {}) or {}
        asyncio.get_event_loop().create_task(
            self.broadcast({
                "type": "status",
                "workflow_id": workflow_id,
                "status": status,
                "phase": wf["state"].get("phase", status) if chunk is None else chunk.get("phase", ""),
                "artifact_keys": list(artifacts.keys()),
                "timestamp": time.time(),
            })
        )

    def _broadcast_skill_event(self, workflow_id: str, skill_name: str, event: str, details: dict = None):
        """Broadcast a skill progress event to WebSocket."""
        wf = self._workflows.get(workflow_id)
        if not wf:
            return
        payload = {
            "type": "skill_progress",
            "workflow_id": workflow_id,
            "skill": skill_name,
            "event": event,  # "running" | "completed" | "failed"
            "phase": wf["state"].get("phase", "UNKNOWN"),
            "timestamp": time.time(),
        }
        if details:
            payload["details"] = details

        # Track in memory
        self._skill_progress.setdefault(workflow_id, []).append(payload)

        asyncio.get_event_loop().create_task(self.broadcast(payload))

    async def handle_websocket_message(self, workflow_id: str, data: str):
        """Handle incoming WebSocket messages."""
        try:
            payload = json.loads(data)
            msg_type = payload.get("type")

            if msg_type == "input":
                self.submit_input(workflow_id, payload.get("data", {}))
            elif msg_type == "approval":
                await self.submit_approval(
                    workflow_id,
                    payload.get("approved", True),
                    payload.get("feedback", ""),
                    payload.get("section_feedback", {}),
                )
            elif msg_type == "diagram_review":
                self.submit_diagram_review(
                    workflow_id,
                    payload.get("approved", True),
                    payload.get("feedback", ""),
                )
            elif msg_type == "pause_response":
                # Direct pause response from frontend
                wf = self._workflows.get(workflow_id, {})
                pending = wf.get("pending_pause")
                if pending:
                    pause_type = pending.get("type", "")
                    callbacks = wf.get("ws_callbacks", {})
                    future = callbacks.get(pause_type)
                    if future and not future.done():
                        future.set_result(payload.get("data", {}))

        except json.JSONDecodeError:
            pass

    def get_pending_inputs(self, workflow_id: str = "") -> list[dict]:
        """Get list of pending input requests."""
        wf = self._workflows.get(workflow_id)
        if not wf:
            return []
        pending = wf.get("pending_pause")
        if not pending:
            return []
        return [{
            "request_id": pending.get("type", ""),
            "phase": pending.get("phase", ""),
            "type": pending.get("type", ""),
            "created_at": wf.get("started_at", 0),
            "timeout_s": 300,
        }]

    def get_diagrams(self, workflow_id: str = "") -> Optional[dict]:
        """Get architecture diagrams for a workflow."""
        wf = self._workflows.get(workflow_id)
        if wf and "state" in wf:
            state = wf["state"]
            if isinstance(state, dict):
                return state.get("diagrams", {})
        return None

    def get_artifacts(self, workflow_id: str = "") -> Optional[dict]:
        """Get skill output artifacts for a workflow."""
        wf = self._workflows.get(workflow_id)
        if wf and "state" in wf:
            state = wf["state"]
            if isinstance(state, dict):
                return state.get("artifacts", {})
        return None

    def get_skill_progress(self, workflow_id: str = "") -> list[dict]:
        """Get skill invocation progress history."""
        return self._skill_progress.get(workflow_id, [])

    def submit_diagram_review(self, workflow_id: str, approved: bool, feedback: str = "") -> dict:
        """Submit architecture diagram review approval/rejection."""
        log_request("diagram.review", workflow_id=workflow_id, approved=approved)
        wf = self._workflows.get(workflow_id)
        if wf and "state" in wf:
            state = wf["state"]
            if isinstance(state, dict):
                state["diagram_status"] = "approved" if approved else "rejected"
                if not approved:
                    state["diagram_feedback"] = feedback
        return {
            "workflow_id": workflow_id,
            "approved": approved,
            "feedback": feedback,
        }