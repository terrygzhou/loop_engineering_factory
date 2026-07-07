# Loop Engineering — Workflow Service Layer

import json
import time
from pathlib import Path
from typing import Optional

from api.middleware.logging import log_request
from api.input_manager import InputManager


class WorkflowService:
    """Service layer for workflow interactions — shared by CLI, Frontend, and API."""

    def __init__(self):
        self._workflows: dict[str, dict] = {}
        self._history: list[dict] = []
        self._websockets: list = []
        self._input_manager = InputManager(default_timeout_s=300, auto_approve_on_timeout=True)

    async def start(self, project_name: str, spec_text: str = "", context_folder: Optional[str] = None) -> dict:
        """Start a new workflow with the given parameters."""
        if not project_name:
            raise ValueError("Project name is required")

        workflow_id = project_name
        from graph.executor import build_executor_state
        state = build_executor_state(
            cycle_id="1",
            project_name=project_name,
            spec_text=spec_text,
            context_folder=context_folder or "",
        )
        self._workflows[workflow_id] = {
            "state": state,
            "started_at": time.time(),
            "status": "initializing",
        }
        log_request("workflow.start", workflow_id=workflow_id, project_name=project_name)
        return state

    def get_status(self, workflow_id: str = "") -> Optional[dict]:
        """Get current workflow status."""
        if workflow_id and workflow_id in self._workflows:
            return self._workflows[workflow_id]["state"]
        for wf in self._workflows.values():
            return wf["state"]
        return None

    def submit_approval(self, workflow_id: str, approved: bool, feedback: str = "", section_feedback: dict = None) -> dict:
        """Submit approval/rejection for a workflow."""
        log_request("approval.submitted", workflow_id=workflow_id, approved=approved)
        return {
            "workflow_id": workflow_id,
            "approved": approved,
            "feedback": feedback,
            "section_feedback": section_feedback or {},
        }

    def submit_input(self, workflow_id: str, input_data: dict) -> dict:
        """Submit user input during interview or review."""
        log_request("input.submitted", workflow_id=workflow_id, keys=list(input_data.keys()))
        return {
            "workflow_id": workflow_id,
            "input_data": input_data,
        }

    def cancel(self, workflow_id: str = "") -> bool:
        """Cancel a workflow."""
        if workflow_id and workflow_id in self._workflows:
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

    async def handle_websocket_message(self, workflow_id: str, data: str):
        """Handle incoming WebSocket messages."""
        try:
            payload = json.loads(data)
            if payload.get("type") == "input":
                self.submit_input(workflow_id, payload.get("data", {}))
            elif payload.get("type") == "approval":
                self.submit_approval(
                    workflow_id,
                    payload.get("approved", True),
                    payload.get("feedback", ""),
                    payload.get("section_feedback", {}),
                )
            elif payload.get("type") == "diagram_review":
                self.submit_diagram_review(
                    workflow_id,
                    payload.get("approved", True),
                    payload.get("feedback", ""),
                )
        except json.JSONDecodeError:
            pass

    def get_pending_inputs(self, workflow_id: str = "") -> list[dict]:
        """Get list of pending input requests."""
        pending = self._input_manager.get_pending()
        return [
            {
                "request_id": r.request_id,
                "phase": r.phase,
                "question": r.question,
                "timeout_s": r.timeout,
                "created_at": r.created_at,
            }
            for r in pending
        ]

    def get_diagrams(self, workflow_id: str = "") -> Optional[dict]:
        """Get architecture diagrams for a workflow."""
        state = self.get_status(workflow_id)
        if state:
            return state.get("diagrams", {})
        return None

    def submit_diagram_review(self, workflow_id: str, approved: bool, feedback: str = "") -> dict:
        """Submit architecture diagram review approval/rejection."""
        log_request("diagram.review", workflow_id=workflow_id, approved=approved)
        if workflow_id in self._workflows:
            state = self._workflows[workflow_id]["state"]
            state["diagram_status"] = "approved" if approved else "rejected"
            if not approved:
                state["diagram_feedback"] = feedback
        return {
            "workflow_id": workflow_id,
            "approved": approved,
            "feedback": feedback,
        }
