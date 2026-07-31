"""
Workflow Bridge — connects Loop Engineering LangGraph workflow to the UI backend.

Skill-driven HIL flow:
- When DEFINE runs interview-me, it generates questions from the skill
- Questions stream to the UI as a structured form
- User answers → answers feed back into the workflow as interview_notes
- Workflow continues with enriched context
"""
import asyncio
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import WebSocket

# ── OpenTelemetry tracing ──
try:
    from opentelemetry import trace as _trace
    _OTEL_BRIDGE = True
except ImportError:
    _OTEL_BRIDGE = False

# Import AbortManager — handle both package and direct import paths
try:
    from backend.abort_manager import AbortManager
except ImportError:
    import sys as _sys, pathlib as _pathlib
    _sys.path.insert(0, str(_pathlib.Path(__file__).parent))
    from abort_manager import AbortManager

# ─── Skill-driven interview questions ─────────────────────────────
# Derived from interview-me SKILL.md — the 9 question categories
INTERVIEW_QUESTIONS = [
    {
        "category": "core_behavior",
        "label": "Core Behavior",
        "question": "What does this feature do? What are the inputs and outputs? What are the success and failure paths?",
        "placeholder": "e.g. Users can create an account, log in, and manage their profile...",
        "required": True,
    },
    {
        "category": "data_model",
        "label": "Data Model",
        "question": "What entities are involved? What fields do they have? Are there relationships to existing models?",
        "placeholder": "e.g. User(id, name, email, password_hash), Order(id, user_id, items, status)...",
        "required": True,
    },
    {
        "category": "api_surface",
        "label": "API Surface",
        "question": "What HTTP methods, paths, and parameters? Any authentication/authorization requirements?",
        "placeholder": "e.g. POST /api/users, GET /api/users/{id}, JWT auth required...",
        "required": True,
    },
    {
        "category": "validation",
        "label": "Validation",
        "question": "What input validation rules? What error responses?",
        "placeholder": "e.g. Email must be valid, password min 8 chars, return 422 on bad input...",
        "required": False,
    },
    {
        "category": "ui_template",
        "label": "UI / Templates",
        "question": "Are there Jinja2 templates involved? What data do they display? Any styling or component requirements?",
        "placeholder": "e.g. Login form, dashboard page, use existing CSS framework...",
        "required": False,
    },
    {
        "category": "integration",
        "label": "Integration",
        "question": "Does this feature interact with other services, databases, or external APIs?",
        "placeholder": "e.g. PostgreSQL for users, Redis for sessions, Stripe for payments...",
        "required": False,
    },
    {
        "category": "deployment",
        "label": "Deployment",
        "question": "Any Docker or infrastructure implications? Environment variables, volumes, or network configuration?",
        "placeholder": "e.g. Docker Compose with API + DB, .env for secrets...",
        "required": False,
    },
    {
        "category": "edge_cases",
        "label": "Edge Cases",
        "question": "What are the known edge cases? What should happen with invalid input, missing data, or rate limits?",
        "placeholder": "e.g. Duplicate email registration, concurrent login attempts...",
        "required": False,
    },
    {
        "category": "non_functional",
        "label": "Non-Functional",
        "question": "Performance targets, security requirements, logging/monitoring needs?",
        "placeholder": "e.g. <200ms response time, rate limiting, audit logging...",
        "required": False,
    },
]


class WorkflowBridge:
    """
    Bridges the Loop Engineering LangGraph workflow with the UI.

    Features:
    - Skill-driven interview: interview-me generates questions, UI presents them
    - Streams real-time progress via WebSocket
    - Supports HIL (Human-In-The-Loop) on DEFINE, PLAN, VERIFY phases
    - Falls back to simulated workflow if real imports fail
    - Captures node-level events from LangGraph astream()
    """

    # Phases in order
    PHASES = [
        "DISCOVER", "DEFINE", "PLAN", "ARCH_REVIEW", "BUILD",
        "SEED_DATA", "VERIFY", "SHIP", "REFLECT",
    ]

    # Phases where we wait for user input
    HIL_PHASES = {"DISCOVER", "ARCH_REVIEW"}

    # Orchestrator state directory (configurable via config/config.yaml paths.build_dir)
    @property
    def orchestrator_state_dir(self) -> Path:
        from config.loader import config as _cfg
        return Path(_cfg.paths.build_dir)

    # SQLite checkpoint DB path
    @property
    def checkpoint_db(self) -> Path:
        return self.orchestrator_state_dir / "checkpoints.db"

    def __init__(self):
        self.status = "idle"
        self.current_phase = ""
        self.cycle = 0
        self.events: List[dict] = []
        self.phase_states: Dict[str, dict] = {}
        self.waiting_for: Optional[str] = None
        self.websocket_clients: List[WebSocket] = []
        self._user_inputs_path = self.orchestrator_state_dir / "user_inputs.json"
        self.user_inputs: Dict[str, Any] = self._load_persisted_inputs()
        self._lock = asyncio.Lock()
        self._ws_lock = asyncio.Lock()
        self._run_task: Optional[asyncio.Task] = None
        self._aborted = False
        self._auto_approve = self._get_auto_approve()
        self._seen_artifacts: Dict[str, Any] = {}
        self._use_real_workflow = False
        self._build_graph = None
        self._WorkflowState = None
        self._CycleMetrics = None
        self._build_skill_registry = None
        self._last_phase = None
        self._project_name = ""
        self._spec_text = ""
        self._context_folder = ""
        self._interrupt_counts: Dict[str, int] = {}  # Track interrupt index per phase
        self._thread_id: Optional[str] = self._load_persisted_inputs().get("_thread_id")
        self._checkpointer = None
        self._input_events: Dict[str, asyncio.Event] = {}

        # Initialize phase tracking
        for phase in self.PHASES:
            self.phase_states[phase] = {
                "phase": phase,
                "status": "pending",
                "started_at": None,
                "completed_at": None,
                "artifacts": {},
                "messages": [],
            }

    def _get_auto_approve(self) -> bool:
        """Web UI is always HIL — never auto-approve. The CLI executor
        handles auto_approve separately via its own flag. The bridge
        should always wait for real user input."""
        return False

    def _load_persisted_inputs(self) -> Dict[str, Any]:
        """Load persisted user inputs from disk (survives restarts)."""
        if self._user_inputs_path.exists():
            try:
                with open(self._user_inputs_path) as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_persisted_inputs(self):
        """Save user inputs + context to disk so they survive restarts."""
        try:
            self._user_inputs_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                **self.user_inputs,
                "_thread_id": self._thread_id,
                "_project_name": self._project_name,
                "_context_folder": self._context_folder,
                "_spec_text": self._spec_text,
            }
            with open(self._user_inputs_path, "w") as f:
                json.dump(payload, f)
        except Exception:
            pass

    def _load_checkpoint_status(self) -> Dict[str, Any]:
        """Read workflow state from the SQLite checkpoint DB.

        Returns a dict with keys matching WorkflowResponse shape:
        status, phase, cycle, phases, waiting_for, messages, project_name.
        Returns empty dict if checkpoint DB is unavailable.
        """
        import sqlite3

        db_path = os.environ.get("CHECKPOINT_DB", str(self.checkpoint_db))

        if not os.path.exists(db_path):
            return {}

        try:
            conn = sqlite3.connect(db_path, uri=True)
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                "SELECT blob FROM checkpoints ORDER BY rowid DESC LIMIT 1"
            )
            row = cur.fetchone()
            conn.close()
        except (sqlite3.OperationalError, OSError):
            return {}

        if row is None:
            return {}

        try:
            import msgpack
            blob = msgpack.loads(row["blob"], strict_map_key=False)
        except Exception:
            return {}

        # LangGraph checkpoint structure:
        # blob is a dict with keys: v, id, ts, channel, channel_versions, metadata, current, next
        # 'channel' maps channel names → values
        channel = blob.get("channel", {})

        # Channels are stored as dicts keyed by channel name
        # The 'phase' channel holds current phase name
        # The '__input__' channel holds the initial state
        phase = None
        project_name = ""
        error = None
        cycle = "1"

        # Extract state from channels
        for ch_name, ch_val in channel.items():
            if ch_name == "phase":
                phase = ch_val
            elif isinstance(ch_val, dict):
                if "phase" in ch_val:
                    phase = ch_val.get("phase")
                if "project_name" in ch_val:
                    project_name = ch_val.get("project_name", "")
                if "error" in ch_val:
                    error = ch_val.get("error")
                if "cycle_id" in ch_val:
                    cycle = ch_val.get("cycle_id", "1")

        if not phase:
            phase = self.PHASES[0]  # default to DISCOVER

        if error:
            overall_status = "error"
        elif phase in self.PHASES:
            overall_status = "running"
        else:
            overall_status = "idle"

        # Build phase states
        phases = []
        for p in self.PHASES:
            phases.append({
                "phase": p,
                "status": "pending",
                "started_at": None,
                "completed_at": None,
                "artifacts": {},
                "messages": [],
            })

        phase_idx = self.PHASES.index(phase) if phase in self.PHASES else 0
        for i in range(phase_idx):
            phases[i]["status"] = "complete"
        phases[phase_idx]["status"] = "running"

        return {
            "status": overall_status,
            "phase": phase,
            "cycle": int(cycle) if isinstance(cycle, str) and cycle.isdigit() else cycle,
            "phases": phases,
            "waiting_for": None,
            "messages": [],
            "project_name": project_name,
            "error": error,
        }

    async def _recover_workflow(self):
        """On startup: if persisted inputs for HIL phases exist, auto-resume."""
        # Check if we have any persisted inputs that match a HIL phase
        persisted = self._load_persisted_inputs()
        thread_id = persisted.get("_thread_id")
        if not thread_id:
            return

        # Check for HIL phase inputs
        hil_phase = None
        for phase in self.HIL_PHASES:
            if phase in self.user_inputs:
                hil_phase = phase
                break
        if not hil_phase:
            return

        # Restore all context from persisted data
        self._thread_id = thread_id
        self._project_name = persisted.get("_project_name", "")
        self._context_folder = persisted.get("_context_folder", "")
        self._spec_text = persisted.get("_spec_text", "")
        self.status = "running"
        self.current_phase = hil_phase
        self.waiting_for = hil_phase
        print(f"[Bridge] Recovering workflow from checkpoint: {hil_phase} thread={thread_id}", flush=True)
        self._run_task = asyncio.create_task(self.run_real())

    def _try_import_real(self):
        """Attempt to import the real workflow modules."""
        if self._use_real_workflow:
            return

        # Resolve project root — try multiple locations for local vs Docker
        candidates = [
            Path(__file__).resolve().parent.parent.parent,  # local: ../.. from backend/
            Path("/loop_factory"),                        # Docker volume mount
        ]
        project_root = None
        for candidate in candidates:
            if (candidate / "graph" / "main.py").exists():
                project_root = candidate
                break

        if project_root and str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))
            print(f"[Bridge] → Added {project_root} to sys.path")

        try:
            from graph.main import build_graph
            from graph.state import WorkflowState, CycleMetrics
            from tools.loader import build_skill_registry
            self._build_graph = build_graph
            self._WorkflowState = WorkflowState
            self._CycleMetrics = CycleMetrics
            self._build_skill_registry = build_skill_registry
            self._use_real_workflow = True
            print("[Bridge] ✓ Real workflow imported")
        except ImportError as e:
            print(f"[Bridge] ⚠ Real workflow import failed: {e} — using simulated mode")
            self._use_real_workflow = False

    def _make_event(self, phase: str, action: str, message: str, data: Optional[Dict[str, Any]] = None) -> dict:
        """Create a progress event dict."""
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "phase": phase,
            "action": action,
            "message": message,
            "data": data or {},
        }

    def add_event(self, phase: str, action: str, message: str, data: Optional[Dict[str, Any]] = None) -> dict:
        """Create, record, and update phase state for an event."""
        ev = self._make_event(phase, action, message, data)
        self.events.append(ev)

        if phase in self.phase_states:
            ps = self.phase_states[phase]
            if action == "started":
                ps["status"] = "running"
                ps["started_at"] = ev["timestamp"]
            elif action == "waiting":
                ps["status"] = "waiting"
            elif action == "completed":
                ps["status"] = "complete"
                ps["completed_at"] = ev["timestamp"]
            elif action == "error":
                ps["status"] = "error"
            ps["messages"].append(ev)

        return ev

    async def broadcast(self, ev: dict):
        """Send event to all WebSocket clients."""
        payload = json.dumps(ev)
        async with self._ws_lock:
            dead = []
            for ws in self.websocket_clients:
                try:
                    await ws.send_text(payload)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self.websocket_clients.remove(ws)

    async def connect_ws(self, websocket: WebSocket):
        """Accept a WebSocket and send recent event history."""
        await websocket.accept()
        async with self._ws_lock:
            self.websocket_clients.append(websocket)
            for ev in self.events[-50:]:
                try:
                    await websocket.send_text(json.dumps(ev))
                except Exception:
                    pass

    async def disconnect_ws(self, websocket: WebSocket):
        """Remove a WebSocket client."""
        async with self._ws_lock:
            if websocket in self.websocket_clients:
                self.websocket_clients.remove(websocket)

    async def abort(self):
        """Abort the running workflow and fully reset state.

        Strategy:
        1. Signal AbortManager so the workflow loop exits immediately
        2. Cancel the running task (raises CancelledError at next await)
        3. Delete the LangGraph checkpoint thread (prevents stale state)
        4. Reset all bridge state
        """
        # Get the shared abort manager and signal it
        abort_mgr = AbortManager.get()
        abort_mgr.signal()

        if self._aborted:
            return {"status": "already_aborted"}
        self._aborted = True

        # Cancel the running task
        if self._run_task and not self._run_task.done():
            self._run_task.cancel()
            try:
                await asyncio.wait_for(self._run_task, timeout=3.0)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                pass

        # Delete the LangGraph checkpoint thread (prevents stale state)
        if self._thread_id and self._checkpointer:
            try:
                self._checkpointer.delete_thread(self._thread_id)
            except Exception:
                pass

        # Clear abort signal for fresh start
        abort_mgr.clear()

        # ── Full state reset ──
        self.status = "idle"
        self.current_phase = ""
        self.cycle = 0
        self.waiting_for = None
        self._aborted = False
        self._run_task = None
        self._last_phase = None
        self._seen_artifacts = {}
        self.user_inputs = {}
        self.events = []
        self._interrupt_counts = {}
        self._thread_id = None
        self._checkpointer = None

        # Wake any blocked input waiters so they see _aborted
        for ev in self._input_events.values():
            ev.set()
        self._input_events.clear()

        # Reset phase tracking
        for phase in self.PHASES:
            self.phase_states[phase] = {
                "phase": phase,
                "status": "pending",
                "started_at": None,
                "completed_at": None,
                "artifacts": {},
                "messages": [],
            }

        ev = self.add_event("SYSTEM", "aborted", "Workflow aborted — all state reset")
        await self.broadcast(ev)
        return {"status": "aborted", "cycle": self.cycle, "phases": list(self.phase_states.values())}

    async def _send_interview(self, phase: str):
        """Send skill-driven interview questions to the UI."""
        ev = self.add_event(
            phase, "interview",
            f"{phase}: skill-driven interview — answer the questions below",
            {"type": "interview", "questions": INTERVIEW_QUESTIONS},
        )
        await self.broadcast(ev)

    def _extract_interview_questions(self, state: dict) -> list:
        """Extract dynamic interview questions from the interrupt graph state.

        The discover node fires interrupt with a 'questions' list. On resume,
        the graph state carries this in the interrupt value. Extract it here
        so the UI renders the right questions (not static defaults).
        """
        # Try graph state artifacts first
        artifacts = state.get("artifacts", {})
        if isinstance(artifacts, dict):
            q = artifacts.get("interview_questions")
            if q and isinstance(q, list) and len(q) > 0:
                return q

        # Try the interrupt value directly (LangGraph 1.x stores it)
        if hasattr(self, '_interrupt_value') and isinstance(self._interrupt_value, dict):
            q = self._interrupt_value.get("questions")
            if q and isinstance(q, list) and len(q) > 0:
                return q

        # Fall back to static defaults
        return INTERVIEW_QUESTIONS

    async def _send_interview_with_questions(self, phase: str, questions: list):
        """Send interview form with the given questions to the UI."""
        # Normalize question format for the JS frontend
        normalized = []
        for q in questions:
            normalized.append({
                "category": q.get("key", q.get("category", "general")),
                "label": q.get("label", q.get("key", "").replace("_", " ").title()),
                "question": q.get("prompt", q.get("question", "")),
                "placeholder": q.get("placeholder", f"Answer for {q.get('key', 'this topic')}..."),
                "required": q.get("required", False),
            })
        ev = self.add_event(
            phase, "interview",
            f"{phase}: interview — answer the questions below",
            {"type": "interview", "questions": normalized},
        )
        await self.broadcast(ev)

    _review_contract: Optional[Any] = None  # type: ignore[misc]

    async def _send_review_plan(self, phase: str, chunk: dict):
        """Send PLAN artifacts to the UI for architecture review."""
        artifacts = chunk.get("artifacts", {})
        diagrams = artifacts.get("diagrams", {})
        diagram_pngs = artifacts.get("diagram_pngs", {})

        # Build diagram display info
        diagram_display = {}
        for dtype, mmd_path in diagrams.items():
            diagram_display[dtype] = {
                "mermaid": mmd_path,
                "png": diagram_pngs.get(dtype, ""),
                "label": dtype.replace("_", " ").title(),
            }

        metrics = chunk.get("metrics")
        arch_uncertainty = getattr(metrics, "arch_uncertainty", 0.0) if metrics else 0.0
        task_count = getattr(metrics, "task_count", 0) if metrics else 0
        diagram_count = getattr(metrics, "diagram_count", 0) if metrics else 0

        # Lazy-load review_contract once (cached per instance)
        if self._review_contract is None:
            import importlib.util
            _rc_candidates = [
                Path(__file__).resolve().parent.parent.parent / "graph" / "nodes" / "review_contract.py",
                Path("/loop_factory/graph/nodes/review_contract.py"),
            ]
            _rc_path = next((c for c in _rc_candidates if c.exists()), None)
            if _rc_path:
                _spec = importlib.util.spec_from_file_location("graph.nodes.review_contract", _rc_path)
                _mod = importlib.util.module_from_spec(_spec)
                sys.modules["graph.nodes.review_contract"] = _mod
                _spec.loader.exec_module(_mod)
                self._review_contract = _mod
        if self._review_contract:
            sections = self._review_contract.build_review_sections(artifacts)
        else:
            sections = []

        ev = self.add_event(
            phase, "review",
            f"ARCH_REVIEW: architecture & plan review — {task_count} tasks, {diagram_count} diagrams",
            {
                "type": "human_review",
                "label": "Architecture & Plan Review",
                "spec_refined": artifacts.get("spec_refined", ""),
                "plan": artifacts.get("plan", ""),
                "tasks": artifacts.get("tasks", ""),
                "analysis": artifacts.get("analysis", ""),
                "doubt_resolution": artifacts.get("doubt_resolution", ""),
                "checklist": artifacts.get("checklist", ""),
                "api_contract": artifacts.get("api_contract", ""),
                "interview_notes": artifacts.get("interview_notes", ""),
                "sections": sections,
                "diagrams": diagram_display,
                "diagram_pngs": diagram_pngs,
                "metrics": {
                    "arch_uncertainty": round(arch_uncertainty, 2),
                    "task_count": task_count,
                    "diagram_count": diagram_count,
                },
            },
        )
        await self.broadcast(ev)

    async def run_simulated(self):
        """Simulated workflow for testing (no real imports needed)."""
        async with self._lock:
            if self.status == "running":
                return

        self.status = "running"
        self.cycle += 1
        self.waiting_for = None

        ev = self.add_event("SYSTEM", "started", f"Cycle {self.cycle} — simulated workflow started for: {self._project_name or 'Untitled'}")
        await self.broadcast(ev)

        # If no context folder, skip DISCOVER immediately
        skip_discover = not bool(self._context_folder)
        # DISCOVER always runs — if project_name provided, interrupt(project_setup) is skipped automatically
        phases_to_run = self.PHASES
        self._last_phase = None

        for phase in phases_to_run:
            if self._aborted:
                break
            self.current_phase = phase
            ev = self.add_event(phase, "started", f"Entering {phase} phase")
            await self.broadcast(ev)

            # Simulate work with artifacts
            for i in range(3):
                await asyncio.sleep(0.5)
                ev = self.add_event(phase, "progress", f"{phase} step {i + 1}/3 in progress")
                await self.broadcast(ev)

            # Generate simulated artifact
            artifact_name = f"{phase.lower()}_output"
            artifact_value = f"Simulated {phase} output for {self._project_name or 'Untitled'}"
            self.phase_states[phase]["artifacts"][artifact_name] = artifact_value
            ev = self.add_event(phase, "artifact", f"Generated: {artifact_name}", {"artifact_name": artifact_name, "artifact_value": artifact_value})
            await self.broadcast(ev)

            # Skill-driven interview at DEFINE
            if phase == "DEFINE":
                await self._send_interview(phase)
                # Populate simulated artifacts for the review phase
                self.phase_states["DEFINE"]["artifacts"]["spec_refined"] = (
                    f"## Simulated Specification for {self._project_name or 'Untitled'}\n\n"
                    "This feature provides a complete end-to-end workflow for managing "
                    "user requirements through automated specification, planning, and implementation.\n\n"
                    "### Key Features\n"
                    "- Requirement gathering via interview\n"
                    "- Automated specification generation\n"
                    "- Human review and approval gates\n"
                    "- Iterative build-verify-reflect cycles"
                )
                self.phase_states["DEFINE"]["artifacts"]["api_contract"] = (
                    f"### API Contract\n\n"
                    "```\n"
                    "POST /api/workflow/start\n"
                    "  Body: { project_name, spec, context_folder }\n"
                    "  Response: { status, cycle }\n\n"
                    "GET /api/status\n"
                    "  Response: { status, phase, cycle, phases, waiting_for }\n\n"
                    "POST /api/input\n"
                    "  Body: { phase, input_type, value }\n"
                    "  Response: { status, phase }\n\n"
                    "WS /ws/progress\n"
                    "  Events: { timestamp, phase, action, message, data }\n"
                    "```\n"
                )
                self.phase_states["DEFINE"]["artifacts"]["interview_notes"] = (
                    "### Interview Notes\n"
                    "- Core behavior: Full workflow automation from requirement to deployment\n"
                    "- Data model: WorkflowState with cycle tracking\n"
                    "- API surface: REST + WebSocket\n"
                    "- Deployment: Docker Compose"
                )

            if not self._aborted:
                ev = self.add_event(phase, "completed", f"{phase} phase completed successfully")
                await self.broadcast(ev)

        # After the loop — only if NOT aborted
        if not self._aborted:
            self.status = "complete"
            self.current_phase = ""
            self.waiting_for = None
            ev = self.add_event("SYSTEM", "completed", f"Cycle {self.cycle} complete")
            await self.broadcast(ev)

    async def run_real(self):
        """Run the actual LangGraph workflow using astream(stream_mode='values').

        Uses the same pattern as the CLI executor:
        1. graph.astream(input_state, stream_mode='values', config) → full merged state snapshots
        2. On GraphInterrupt: get graph state → build HIL form → poll user → resume
        3. Repeat until stream completes normally (no exception)

        astream('values') yields the full merged state dict each time a node completes,
        so phase, project_name, artifacts etc. are always present.
        """
        if not self._use_real_workflow:
            print("[Bridge] Real workflow unavailable — falling back to simulated")
            await self.run_simulated()
            return

        async with self._lock:
            if self.status == "running":
                return

        # ── OTEL root span ──
        self._root_span = None
        if _OTEL_BRIDGE:
            tracer = _trace.get_tracer("loop.bridge")
            self._root_span = tracer.start_span(
                "workflow.run",
                attributes={
                    "workflow.cycle": self.cycle,
                    "workflow.project": self._project_name or "Untitled",
                },
            )
            self._root_span.set_attribute("workflow.spec_preview", (self._spec_text or "")[:200])

        self.status = "running"
        # On recovery (thread_id was pre-set by _recover_workflow), don't increment cycle
        has_stale_thread_id = bool(self._thread_id)
        is_recovery = has_stale_thread_id
        if has_stale_thread_id:
            try:
                from graph.executor import _get_checkpointer
                checkpointer = _get_checkpointer()
                test_config = {"configurable": {"thread_id": self._thread_id}}
                cp_list = list(checkpointer.list(test_config))
                if not cp_list:
                    print(f"[Bridge] Stale thread_id {self._thread_id} — no checkpoint, treating as fresh", flush=True)
                    self._thread_id = None
                    is_recovery = False
            except Exception:
                is_recovery = False

        if not is_recovery:
            self.cycle += 1
        self.waiting_for = None
        self._last_phase = None

        # Clear abort signal for fresh run
        AbortManager.get().clear()
        print(f"[Bridge.run_real] abort cleared, is_aborted={AbortManager.get().is_aborted}", flush=True)

        # ── Use shared executor for graph + state (same as CLI) ──
        from graph.executor import _get_checkpointer
        from langgraph.errors import GraphInterrupt
        from langgraph.types import Command
        import uuid as _uuid

        checkpointer = _get_checkpointer()
        if not self._thread_id:
            thread_id = str(_uuid.uuid4())
        else:
            thread_id = self._thread_id
        self._checkpointer = checkpointer
        self._thread_id = thread_id
        self._save_persisted_inputs()
        config = {"configurable": {"thread_id": thread_id}}

        # Build state via shared executor
        state = self._build_executor_state(
            cycle_id=str(self.cycle),
            project_name=self._project_name,
            spec_text=self._spec_text,
            context_folder=self._context_folder,
        )

        ev = self.add_event("SYSTEM", "started", f"Cycle {self.cycle} — real workflow started for: {self._project_name or 'Untitled'}")
        await self.broadcast(ev)

        self._last_phase = None
        abort_mgr = AbortManager.get()

        try:
            from graph.main import build_graph
            graph = build_graph(checkpointer=checkpointer, auto_approve=False)

            # ── astream(values) loop — same as CLI executor ──
            current_input = None if is_recovery else state
            chunk = None  # last yielded state snapshot

            while not self._aborted:
                # Race: drain stream vs abort signal
                abort_task = asyncio.ensure_future(abort_mgr.wait(999))

                try:
                    async for chunk in graph.astream(
                        current_input, stream_mode="values", config=config
                    ):
                        if self._aborted:
                            break

                        # Race check: if abort fired, stop processing
                        if abort_task.done() and abort_mgr.is_aborted:
                            break

                        # Full merged state — phase is always present
                        phase = chunk.get("phase", "UNKNOWN")
                        artifacts = chunk.get("artifacts", {})
                        # ── LangGraph 1.x: interrupt() no longer raises; it
                        # yields __interrupt__ in the stream chunk and completes.
                        # Capture interrupt data, then re-raise so the pause handler runs. ──
                        if chunk.get("__interrupt__"):
                            interrupt_data = chunk["__interrupt__"]
                            # Extract type from Interrupt(value={'type': 'project_setup', ...})
                            if interrupt_data and len(interrupt_data) > 0:
                                iv = interrupt_data[0]
                                if hasattr(iv, 'value') and isinstance(iv.value, dict):
                                    self._interrupt_type = iv.value.get("type")
                                    # Store full interrupt value for question extraction
                                    self._interrupt_value = iv.value
                                else:
                                    self._interrupt_type = str(iv)
                                    self._interrupt_value = None
                            else:
                                self._interrupt_type = None
                                self._interrupt_value = None
                            from langgraph.errors import GraphInterrupt
                            raise GraphInterrupt("Interrupted for HIL input")

                        # Capture artifacts
                        if artifacts and phase in self.phase_states:
                            self.phase_states[phase]["artifacts"].update(artifacts)

                        # Deduplicate artifact events
                        for artifact_name, artifact_value in artifacts.items():
                            artifact_key = f"{phase}:{artifact_name}"
                            if artifact_key not in self._seen_artifacts or self._seen_artifacts[artifact_key] != artifact_value:
                                self._seen_artifacts[artifact_key] = artifact_value
                                ev = self.add_event(phase, "artifact", f"{artifact_name}: {str(artifact_value)[:200]}", {
                                    "artifact_name": artifact_name,
                                    "artifact_value": artifact_value,
                                })
                                await self.broadcast(ev)

                        # Detect phase transitions
                        if phase != self._last_phase:
                            if self._last_phase is not None:
                                ev = self.add_event(self._last_phase, "completed", f"{self._last_phase} completed")
                                await self.broadcast(ev)
                                # OTEL: record completed phase
                                if _OTEL_BRIDGE and self._root_span:
                                    self._root_span.add_event("phase.completed", {"phase": self._last_phase})
                            self.current_phase = phase
                            ev = self.add_event(phase, "started", f"Entering {phase} phase")
                            await self.broadcast(ev)
                            # OTEL: record phase start
                            if _OTEL_BRIDGE and self._root_span:
                                self._root_span.add_event("phase.started", {"phase": phase})
                            self._last_phase = phase
                        else:
                            ev = self.add_event(phase, "progress", f"{phase} processing...")
                            await self.broadcast(ev)

                except GraphInterrupt:
                    # Cancel abort waiter
                    if not abort_task.done():
                        abort_task.cancel()
                        try:
                            await abort_task
                        except BaseException:
                            pass
                    if self._aborted:
                        break

                    # Get the suspended graph state for HIL
                    graph_state = await graph.aget_state(config)
                    if not graph_state.next and not graph_state.interrupts:
                        # Normal end disguised as interrupt
                        break
                    # Nodes not in interrupt_after can have empty graph_state.next
                    # while still having pending interrupts. Check both before breaking.

                    current_chunk = graph_state.values or {}
                    # Determine interrupted phase — prefer the interrupting node's name
                    # over the stale phase in current_chunk (which reflects the previous phase).
                    if graph_state.next and len(graph_state.next) > 0:
                        node_name = graph_state.next[0]
                        # Map node names to phase names (node names are typically snake_case of phase)
                        if "discover" in node_name:
                            interrupted_phase = "DISCOVER"
                        elif "define" in node_name:
                            interrupted_phase = "DEFINE"
                        elif "plan" in node_name:
                            interrupted_phase = "PLAN"
                        elif "review" in node_name or "arch" in node_name:
                            interrupted_phase = "ARCH_REVIEW"
                        elif "build" in node_name:
                            interrupted_phase = "BUILD"
                        elif "seed" in node_name:
                            interrupted_phase = "SEED_DATA"
                        elif "verify" in node_name:
                            interrupted_phase = "VERIFY"
                        elif "ship" in node_name:
                            interrupted_phase = "SHIP"
                        elif "reflect" in node_name:
                            interrupted_phase = "REFLECT"
                        else:
                            interrupted_phase = node_name
                    else:
                        interrupted_phase = (
                            current_chunk.get("phase")
                            or current_chunk.get("next_phase")
                            or self._last_phase
                            or "UNKNOWN"
                        )
                    interrupted_type = getattr(self, '_interrupt_type', None)
                    if not interrupted_type:
                        # Fallback: try graph_state.interrupts
                        if graph_state.interrupts and len(graph_state.interrupts) > 0:
                            first = graph_state.interrupts[0]
                            if hasattr(first, 'value'):
                                # Extract type key from interrupt value dict
                                if isinstance(first.value, dict):
                                    interrupted_type = first.value.get("type")
                                else:
                                    interrupted_type = str(first.value)
                            else:
                                interrupted_type = str(first)
                    print(f"  → HIL pause for: {interrupted_phase}, type={interrupted_type}")
                    # OTEL: record HIL pause (guard against None which crashes OTEL)
                    if _OTEL_BRIDGE and self._root_span:
                        otel_type = interrupted_type or "unknown"
                        self._root_span.add_event("hil.pause", {"phase": interrupted_phase, "type": otel_type})

                    user_input = await self._handle_hil(interrupted_phase, interrupted_type, current_chunk)
                    if self._aborted:
                        break

                    resume_result = self._build_resume_data(interrupted_phase, user_input)
                    resume_data, update_data = resume_result if isinstance(resume_result, tuple) else (resume_result, None)
                    print(f"  → Resuming {interrupted_phase} with Command(resume=..., update=...)")
                    self.status = "running"
                    self.waiting_for = None
                    if update_data:
                        current_input = Command(resume=[resume_data], update=update_data)
                    else:
                        current_input = Command(resume=[resume_data])
                    continue

                # Cancel abort waiter (normal completion path)
                if not abort_task.done():
                    abort_task.cancel()
                    try:
                        await abort_task
                    except BaseException:
                        pass

                if self._aborted:
                    break

                # Normal completion — check if graph still has pending nodes.
                # interrupt_after can cause the stream to exit after a node
                # completes even though downstream edges remain (e.g. DISCOVER
                # → DEFINE). If next is non-empty, continue streaming.
                graph_state = await graph.aget_state(config)
                if graph_state.next:
                    print(f"[Bridge] Stream ended but {len(graph_state.next)} node(s) pending: {graph_state.next} — continuing", flush=True)
                    current_input = None
                    continue

                if self._last_phase:
                    ev = self.add_event(self._last_phase, "completed", f"{self._last_phase} completed")
                    await self.broadcast(ev)

                self.status = "complete"
                self.current_phase = ""
                self.waiting_for = None
                last_keys = list(chunk.keys()) if chunk else []
                print(f"[Bridge] Workflow complete, final state keys: {last_keys}", flush=True)
                ev = self.add_event("SYSTEM", "completed", f"Cycle {self.cycle} complete — all phases done")
                await self.broadcast(ev)
                if _OTEL_BRIDGE and self._root_span:
                    self._root_span.set_status(_trace.Status(_trace.StatusCode.OK))
                    self._root_span.end()
                break

        except asyncio.CancelledError:
            if self.status != "complete":
                import traceback, sys
                print(f"[Bridge] CancelledError caught (non-fatal) — stacktrace:", flush=True)
                traceback.print_exc()
                self.status = "idle"
                self.current_phase = ""
                self.waiting_for = None
            else:
                print(f"[Bridge] CancelledError ignored (status=complete)", flush=True)
            if _OTEL_BRIDGE and self._root_span:
                self._root_span.set_status(_trace.Status(_trace.StatusCode.OK, "cancelled"))
                self._root_span.end()
        except Exception as e:
            self.status = "error"
            ev = self.add_event("SYSTEM", "error", f"Workflow failed: {str(e)[:200]}")
            await self.broadcast(ev)
            if _OTEL_BRIDGE and self._root_span:
                self._root_span.set_status(_trace.Status(_trace.StatusCode.ERROR, str(e)[:200]))
                self._root_span.end()
            raise

    def _classify_hil_type(self, interrupted_phase, interrupted_type):
        """Classify HIL interaction type."""
        if interrupted_phase == "DISCOVER" and interrupted_type == "project_setup":
            return "project_setup"
        elif interrupted_phase == "DISCOVER" and interrupted_type == "interview":
            return "interview"
        else:
            return "generic"

    async def _handle_hil(self, phase, interrupted_type, state):
        """Handle HIL interruption: classify, broadcast form, poll for input."""
        hil_type = self._classify_hil_type(phase, interrupted_type)
        print(f"  → HIL pause: {phase}, type={interrupted_type}, hil_type={hil_type}", flush=True)
        # OTEL: record HIL pause
        if _OTEL_BRIDGE and hasattr(self, '_root_span') and self._root_span:
            self._root_span.add_event("hil.pause", {"phase": phase, "type": interrupted_type or "unknown"})

        # Auto-resume project_setup if data already provided via start request
        if hil_type == "project_setup" and self._project_name:
            print(f"  → Auto-resuming project_setup (data from start request)", flush=True)
            return {
                "project_name": self._project_name,
                "project_description": self._spec_text,
                "context_folder": self._context_folder or "",
            }

        # Auto-resume any HIL pause when auto_approve is enabled
        if self._auto_approve:
            print(f"  → Auto-approving HIL pause: {phase} type={interrupted_type}", flush=True)
            if interrupted_type == "review":
                return {"approved": True, "feedback": "Auto-approved"}
            if hil_type == "interview":
                return {"interview_notes": f"Auto-approved interview for {self._project_name}", "discover_interview_done": True}
            return {"approved": True, "human_approval_required": False}

        await self._broadcast_hil_form(phase, hil_type, state)
        user_input = await self._poll_user_input(phase)
        # OTEL: record HIL resume
        if _OTEL_BRIDGE and hasattr(self, '_root_span') and self._root_span:
            self._root_span.add_event("hil.resume", {"phase": phase})
        return user_input

    async def _broadcast_hil_form(self, phase, hil_type, state):
        """Broadcast appropriate form based on HIL type."""
        self.status = "waiting"
        self.waiting_for = phase

        if phase == "DISCOVER" and hil_type == "project_setup":
            ev = self.add_event(phase, "setup",
                "DISCOVER: project setup required",
                {"type": "project_setup", "fields": [
                    {"key": "project_name", "label": "Project name", "required": True},
                    {"key": "project_description", "label": "Project description", "required": True},
                    {"key": "context_folder", "label": "Existing codebase path (leave empty for greenfield)", "required": False},
                ]})
            await self.broadcast(ev)
        elif phase == "DISCOVER" and hil_type == "interview":
            # Extract dynamic questions from the interrupt's graph state
            dynamic_questions = self._extract_interview_questions(state)
            await self._send_interview_with_questions(phase, dynamic_questions)
        elif phase == "ARCH_REVIEW":
            print(f"  → ARCH_REVIEW HIL detected", flush=True)
            await self._send_review_plan("ARCH_REVIEW", state)
        else:
            ev = self.add_event(phase, "waiting", f"Waiting for user input — {phase}", {"type": "review_approval"})
            await self.broadcast(ev)

    async def _poll_user_input(self, phase):
        """Wait for user input with abort check (up to 30 min)."""
        # Ensure an event exists for this phase
        if phase not in self._input_events:
            self._input_events[phase] = asyncio.Event()
        event = self._input_events[phase]
        event.clear()

        try:
            # Wait for either: input received, abort, or timeout
            await asyncio.wait_for(event.wait(), timeout=1800)  # 30 min
        except asyncio.TimeoutError:
            ev = self.add_event(phase, "progress", f"{phase} auto-approved (timeout)")
            await self.broadcast(ev)
            return {"approved": True, "interview_notes": ""}

        if self._aborted:
            return None

        if phase in self.user_inputs:
            user_input = self.user_inputs.pop(phase)
            self._save_persisted_inputs()
            ev = self.add_event(phase, "progress", "User input received")
            await self.broadcast(ev)
            return user_input

        # Event fired but no input (e.g. abort signal)
        return {"approved": True, "interview_notes": ""}

    def _parse_formatted_input(self, text: str) -> Optional[Dict[str, str]]:
        """Parse formatted input strings from the JS frontend.

        The frontend sends formatted text like:
          "[Project Name] ContactHub\n\n[Description] App for contacts and calendar\n\n[Context Folder] /path"

        Maps known label keywords to their canonical keys so the backend
        can reconstruct the resume dict regardless of whether the frontend
        sent a dict or a formatted string.
        """
        label_to_key = {
            "project name": "project_name",
            "description": "project_description",
            "context folder": "context_folder",
            "core behavior": "core_behavior",
            "data model": "data_model",
            "api surface": "api_surface",
            "validation": "validation",
            "deployment": "deployment",
            "user experience": "user_experience",
            "error handling": "error_handling",
            "authentication": "authentication",
            "testing": "testing",
        }

        parsed = {}
        for line in text.split("\n"):
            line = line.strip()
            match = re.match(r'^\[([^\]]+)\]\s*(.*)', line)
            if match:
                label = match.group(1).lower()
                value = match.group(2).strip()
                if not value:
                    continue
                key = label_to_key.get(label, label.replace(" ", "_"))
                parsed[key] = value

        return parsed if parsed else None

    def _build_resume_data(self, phase, user_input):
        """Build resume payload for Command(resume=...).

        Returns (resume_data, update_data) tuple.
        update_data is passed to Command(update=...) to pre-seed the
        checkpoint so guards see fresh state on node re-run.
        """
        if user_input is None:
            user_input = {"approved": True, "interview_notes": ""}
        self.waiting_for = None

        if phase == "DISCOVER":
            if isinstance(user_input, dict):
                resume = user_input
            elif isinstance(user_input, str):
                # Parse formatted strings like "[Project Name] X\n[Description] Y"
                parsed = self._parse_formatted_input(user_input)
                if parsed:
                    resume = parsed
                else:
                    resume = {"interview_notes": user_input}
            else:
                resume = {"interview_notes": str(user_input)}

            itype = getattr(self, '_interrupt_type', None)
            # Build interview_notes from whatever form the user input took
            if itype == "interview":
                # User may have sent individual answer keys or a pre-formed interview_notes
                if resume.get("interview_notes"):
                    interview_notes = resume["interview_notes"]
                elif isinstance(resume, dict) and any(k in resume for k in ("core_behavior", "data_model", "api_surface")):
                    # Convert answer dict to structured notes string
                    parts = []
                    for k, v in resume.items():
                        if k not in ("approved",) and v:
                            parts.append(f"{k}: {v}")
                    interview_notes = "\n".join(parts)
                    resume["interview_notes"] = interview_notes
                elif isinstance(resume, dict) and resume:
                    # Generic key-value answers (from dynamic questions)
                    parts = []
                    for k, v in resume.items():
                        if k not in ("approved", "input_type") and v:
                            label = k.replace("_", " ").title()
                            parts.append(f"[{label}] {v}")
                    interview_notes = "\n\n".join(parts)
                    if not interview_notes:
                        interview_notes = str(resume.get("interview_notes", ""))
                    resume["interview_notes"] = interview_notes
                else:
                    interview_notes = str(resume.get("interview_notes", ""))
                update = {
                    "interview_notes": interview_notes,
                    "discover_interview_done": True,
                }
            elif itype == "project_setup":
                interview_notes = ""
                # Persist project name/description into state so the node
                # can read them on re-run (they were only in resume dict).
                update = {
                    "project_name": resume.get("project_name", ""),
                    "project_description": resume.get("project_description", ""),
                    "discover_setup_done": True,
                }
                if resume.get("context_folder"):
                    update["context_folder"] = resume["context_folder"]
            else:
                interview_notes = resume.get("interview_notes", "")
                update = None
            return resume, update
        elif phase == "ARCH_REVIEW":
            return {
                "approved": bool(user_input.get("approved", True)),
                "feedback": user_input.get("feedback", user_input.get("user_review_comments", "")),
            }, None
        else:
            return {"human_approval_required": False}, None

    def _build_executor_state(self, cycle_id, project_name, spec_text, context_folder):
        """Build state via shared executor — identical to what CLI uses.
        
        Web UI always forces HIL mode (auto_approve_override=False) so that
        interrupt() gates are triggered regardless of config defaults.
        """
        from graph.executor import build_executor_state
        state = build_executor_state(
            cycle_id=cycle_id,
            project_name=project_name,
            spec_text=spec_text,
            context_folder=context_folder,
        )
        # Force HIL: override any config defaults so nodes hit interrupt() gates
        state["auto_approve_override"] = False
        # Force HIL: ensure setup node doesn't skip when project_name is provided
        state["force_hil"] = True
        # Pre-seed project data so DISCOVER skips the project_setup interrupt
        # and goes straight to the interview interrupt. The web UI already
        # collects project_name / description in the start request, so pausing
        # for project_setup is redundant. Critically, this avoids the
        # "orphaned resume" bug: when the bridge auto-resumed project_setup
        # with Command(resume=..., update={discover_setup_done: True}), the
        # node re-ran and skipped the setup interrupt() (because
        # discover_setup_done was True), but LangGraph still consumed the
        # resume value. The subsequent interview interrupt() was then
        # suppressed — it returned the stale resume dict instead of pausing.
        # By pre-setting discover_setup_done here, the setup interrupt never
        # fires, so no resume is consumed and the interview interrupt fires cleanly.
        state["discover_setup_done"] = True
        state["project_description"] = spec_text or ""
        # Inject skill_callback so SkillTimer events reach the UI
        bridge_ref = self
        def _skill_callback(skill_name, event_type, details=None):
            ev = {
                "timestamp": datetime.utcnow().isoformat(),
                "type": "skill_progress",
                "skill": skill_name,
                "event": event_type,
                "details": details or {},
                "phase": bridge_ref.current_phase or "",
                "action": event_type,
                "message": f"Skill '{skill_name}' {event_type}",
                "data": {"skill_name": skill_name, "event_type": event_type},
            }
            bridge_ref.events.append(ev)
            try:
                asyncio.ensure_future(bridge_ref.broadcast(ev))
            except Exception:
                pass
        state["skill_callback"] = _skill_callback
        return state

    async def run(self, spec_text: str = "", project_name: str = "", project_path: str = "", context_folder: str = ""):
        """Main entry point — tries real workflow, falls back to simulated."""
        self._spec_text = spec_text
        self._project_name = project_name
        self._context_folder = context_folder
        self._try_import_real()

        if self._use_real_workflow:
            await self.run_real()
        else:
            await self.run_simulated()
