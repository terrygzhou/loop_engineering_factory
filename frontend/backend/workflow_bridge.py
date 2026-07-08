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
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import WebSocket

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
    HIL_PHASES = {"DISCOVER", "ARCH_REVIEW", "VERIFY"}

    # Orchestrator state file path (shared via Docker volume) — legacy, kept for backward compat
    ORCHESTRATOR_STATE_DIR = Path("/app/build")

    # SQLite checkpoint DB path (matches executor's _get_checkpointer default)
    CHECKPOINT_DB = Path("/app/build/checkpoints.db")

    def __init__(self):
        self.status = "idle"
        self.current_phase = ""
        self.cycle = 0
        self.events: List[dict] = []
        self.phase_states: Dict[str, dict] = {}
        self.waiting_for: Optional[str] = None
        self.websocket_clients: List[WebSocket] = []
        self._user_inputs_path = Path("/app/build/user_inputs.json")
        self.user_inputs: Dict[str, Any] = self._load_persisted_inputs()
        self._lock = asyncio.Lock()
        self._run_task: Optional[asyncio.Task] = None
        self._aborted = False
        self._auto_approve = False
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
        self._thread_id: Optional[str] = None          # Current LangGraph thread (for abort cleanup)
        self._checkpointer = None                      # Current checkpointer instance

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
        """Save user inputs to disk so they survive restarts."""
        try:
            self._user_inputs_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._user_inputs_path, "w") as f:
                json.dump(self.user_inputs, f)
        except Exception:
            pass

    def _load_checkpoint_status(self) -> Dict[str, Any]:
        """Read workflow state from the SQLite checkpoint DB.

        Returns a dict with keys matching WorkflowResponse shape:
        status, phase, cycle, phases, waiting_for, messages, project_name.
        Returns empty dict if checkpoint DB is unavailable.
        """
        import sqlite3

        db_path = os.environ.get("CHECKPOINT_DB", str(self.CHECKPOINT_DB))

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
        """On startup: detect active checkpoint + persisted input, auto-resume."""
        cp = self._load_checkpoint_status()
        if not cp or cp.get("status") == "idle":
            return

        phase = cp.get("phase")
        if phase and phase in self.HIL_PHASES:
            if phase in self.user_inputs:
                self.status = "running"
                self.current_phase = phase
                self.waiting_for = phase
                self._project_name = cp.get("project_name", "")
                self._context_folder = cp.get("context_folder", "")
                self._spec_text = cp.get("spec_text", "")
                if cp.get("cycle"):
                    self.cycle = cp["cycle"]
                print(f"[Bridge] Recovering workflow from checkpoint: {phase}", flush=True)
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
        self.websocket_clients.append(websocket)
        for ev in self.events[-50:]:
            try:
                await websocket.send_text(json.dumps(ev))
            except Exception:
                pass

    def disconnect_ws(self, websocket: WebSocket):
        """Remove a WebSocket client."""
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

        # Lazy-load review_contract module (shared with _send_review)
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

    async def _send_review(self, phase: str, chunk: dict):
        """Send full DEFINE output to the UI for human review.

        Uses the shared review_contract to build identical section payloads
        as the CLI executor — same keys, labels, content, and word counts.
        """
        # Lazy-load review_contract once (cached per instance)
        if self._review_contract is None:
            import importlib.util
            from pathlib import Path
            _rc_candidates = [
                Path(__file__).resolve().parent.parent.parent / "graph" / "nodes" / "review_contract.py",
                Path("/loop_factory/graph/nodes/review_contract.py"),
            ]
            _rc_path = next((c for c in _rc_candidates if c.exists()), None)
            if not _rc_path:
                raise FileNotFoundError(f"Cannot find review_contract.py in {_rc_candidates}")
            _spec = importlib.util.spec_from_file_location("review_contract", _rc_path)
            _mod = importlib.util.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            sys.modules["review_contract"] = _mod
            self._review_contract = _mod
        _mod = self._review_contract
        build_review_sections = _mod.build_review_sections
        build_review_summary = _mod.build_review_summary
        build_review_metrics = _mod.build_review_metrics

        artifacts = chunk.get("artifacts", {})
        sections = build_review_sections(artifacts)
        metrics = build_review_metrics(chunk)

        ev = self.add_event(
            phase, "review",
            f"{phase}: review DEFINE output before proceeding to PLAN",
            {
                "type": "human_review",
                "summary": build_review_summary(sections),
                "sections": sections,
                "metrics": metrics,
            },
        )
        await self.broadcast(ev)

    async def _wait_for_user_input(self, phase: str):
        """Block until user provides input or times out (30 min)."""
        self.status = "waiting"
        self.waiting_for = phase

        ev = self.add_event(phase, "waiting", f"Waiting for user input — {phase} phase", {"type": "review_approval"})
        await self.broadcast(ev)

        for _ in range(1800):  # 30 minutes max
            await asyncio.sleep(1)
            if phase in self.user_inputs:
                inp = self.user_inputs.pop(phase)
                ev = self.add_event(phase, "progress", f"User input received")
                await self.broadcast(ev)
                return inp

        ev = self.add_event(phase, "progress", f"{phase} auto-approved (timeout)")
        await self.broadcast(ev)
        return None

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

            # HIL at DEFINE: send interview questions (skill-driven)
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

            # Skill-driven interview at DEFINE (not DISCOVER — already handled in on_hil_bridge)
            if phase == "DEFINE":
                await self._send_interview(phase)
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
        """Run the actual LangGraph workflow with OOTB interrupt/resume.

        Uses LangGraph native interrupt() + Command(resume=...) pattern:
        1. graph.stream() for normal execution
        2. GraphInterrupt caught → UI polling for input → Command(resume=...)
        3. Repeat until workflow completes

        Replaces custom _astream_with_hil() with OOTB pattern.
        """
        if not self._use_real_workflow:
            print("[Bridge] Real workflow unavailable — falling back to simulated")
            await self.run_simulated()
            return

        async with self._lock:
            if self.status == "running":
                return

        self.status = "running"
        self.cycle += 1
        self.waiting_for = None
        self._last_phase = None

        # Clear abort signal for fresh run
        AbortManager.get().clear()
        print(f"[Bridge.run_real] abort cleared, is_aborted={AbortManager.get().is_aborted}", flush=True)

        # ── Use shared executor for graph + state (same as CLI) ──
        from graph.executor import WorkflowRunner, _get_checkpointer
        from langgraph.errors import GraphInterrupt
        from langgraph.types import Command
        import uuid as _uuid

        # Fresh checkpointer for this run — store for abort cleanup
        checkpointer = _get_checkpointer()
        thread_id = str(_uuid.uuid4())
        self._checkpointer = checkpointer
        self._thread_id = thread_id
        config = {"configurable": {"thread_id": thread_id}}

        # Build state via shared executor — guarantees identical state for both modes
        state = self._build_executor_state(
            cycle_id=str(self.cycle),
            project_name=self._project_name,
            spec_text=self._spec_text,
            context_folder=self._context_folder,
        )

        ev = self.add_event("SYSTEM", "started", f"Cycle {self.cycle} — real workflow started for: {self._project_name or 'Untitled'}")
        await self.broadcast(ev)

        # DISCOVER always runs — if project_name provided, interrupt(project_setup) is skipped automatically
        self._last_phase = None
        completed = False

        try:
            # ── OOTB interrupt/resume loop ──
            from graph.main import build_graph
            graph = build_graph(checkpointer=checkpointer, auto_approve=self._auto_approve)

            input_state = state
            abort_mgr = AbortManager.get()
            while not self._aborted and not completed:
                if self._aborted:
                    break

                # ── Abort-responsive stream iteration ──
                # graph.astream() is an async generator. We iterate explicitly
                # with AbortManager so the abort signal can break us out mid-stream.
                stream = graph.astream(input_state, stream_mode="values", config=config)
                interrupted_chunk = None
                chunk_count = 0

                while True:
                    if self._aborted:
                        break

                    # Race: get next chunk OR abort signal
                    # Timeout=999s is effectively "wait forever unless aborted"
                    next_task = asyncio.ensure_future(stream.__anext__())
                    abort_task = asyncio.ensure_future(abort_mgr.wait(999))

                    done, pending = await asyncio.wait(
                        {next_task, abort_task}, return_when=asyncio.FIRST_COMPLETED
                    )

                    # Clean up pending tasks
                    for t in pending:
                        t.cancel()
                        try:
                            await t
                        except BaseException:
                            pass

                    if abort_task in done and abort_mgr.is_aborted:
                        # Actual abort — cancel chunk fetch and break
                        next_task.cancel()
                        try:
                            await next_task
                        except BaseException:
                            pass
                        break

                    if next_task in done:
                        # Chunk arrived — cancel abort waiter and process
                        abort_task.cancel()
                        try:
                            await abort_task
                        except BaseException:
                            pass
                        try:
                            chunk = next_task.result()
                            chunk_count += 1
                        except StopAsyncIteration:
                            print("[Bridge] StopAsyncIteration (stream ended)", flush=True)
                            break  # Exit inner loop — stream ended
                    else:
                        # Both completed (rare) — re-loop
                        print("[Bridge] both tasks completed (rare)", flush=True)
                        continue

                    # ── Process chunk (only reached when chunk arrived normally) ──
                    # Check for interrupt signal in chunk (LangGraph yields __interrupt__ on suspend)
                    if "__interrupt__" in chunk:
                        print(f"  → Interrupt detected in chunk: {chunk['__interrupt__']}")
                        interrupted_chunk = chunk
                        break

                    phase = chunk.get("phase", "UNKNOWN")
                    artifacts = chunk.get("artifacts", {})

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
                        self.current_phase = phase
                        ev = self.add_event(phase, "started", f"Entering {phase} phase")
                        await self.broadcast(ev)
                        self._last_phase = phase

                    else:
                        ev = self.add_event(phase, "progress", f"{phase} processing...")
                        await self.broadcast(ev)

                # If we hit an interrupt, handle HIL flow
                if interrupted_chunk is not None:
                    graph_state = await graph.aget_state(config)
                    if not graph_state.next:
                        if self._last_phase:
                            ev = self.add_event(self._last_phase, "completed", f"{self._last_phase} completed")
                            await self.broadcast(ev)
                        break

                    # Determine interrupted phase
                    current_chunk = graph_state.values or {}
                    interrupted_phase = (
                        current_chunk.get("phase")
                        or current_chunk.get("next_phase")
                        or self._last_phase
                        or "UNKNOWN"
                    )
                    # Determine HIL type from the actual interrupt value in the stream
                    interrupted_type = None
                    if interrupted_chunk and "__interrupt__" in interrupted_chunk:
                        raw = interrupted_chunk["__interrupt__"]
                        # Two shapes: (1) synthetic string sentinel from StopAsyncIteration,
                        # (2) tuple/list of Interrupt objects from LangGraph native interrupt()
                        if isinstance(raw, str):
                            interrupted_type = raw
                        else:
                            for iv in raw:
                                interrupted_type = iv.value.get("type")
                                break

                    print(f"  → HIL pause for: {interrupted_phase}, type={interrupted_type}")

                    if interrupted_phase == "DISCOVER" and interrupted_type == "project_setup":
                        hil_type = "project_setup"
                    elif interrupted_phase == "DISCOVER" and interrupted_type == "interview":
                        hil_type = "interview"
                    else:
                        hil_type = "generic"

                    # ── Wait for user input (bridge layer) ──
                    self.status = "waiting"
                    self.waiting_for = interrupted_phase

                    # Send appropriate form based on interrupt type
                    if interrupted_phase == "DISCOVER" and hil_type == "project_setup":
                        ev = self.add_event(interrupted_phase, "interview",
                            "DISCOVER: project setup required",
                            {"type": "project_setup", "fields": [
                                {"key": "project_name", "label": "Project name", "required": True},
                                {"key": "project_description", "label": "Project description", "required": True},
                                {"key": "context_folder", "label": "Existing codebase path (leave empty for greenfield)", "required": False},
                            ]})
                        await self.broadcast(ev)
                    elif interrupted_phase == "DISCOVER" and hil_type == "interview":
                        await self._send_interview(interrupted_phase)
                    elif interrupted_phase == "ARCH_REVIEW" or interrupted_type == "review":
                        # ARCH_REVIEW may still show phase="PLAN" in checkpoint because ARCH_REVIEW's
                        # state["phase"]="ARCH_REVIEW" isn't visible in aget_state() until resume.
                        # interrupted_type carries the real interrupt type ("review") from the payload.
                        print(f"  → ARCH_REVIEW HIL detected (phase={interrupted_phase}, type={interrupted_type})", flush=True)
                        await self._send_review_plan("ARCH_REVIEW", current_chunk)
                    else:
                        ev = self.add_event(interrupted_phase, "waiting", f"Waiting for user input — {interrupted_phase}", {"type": "review_approval"})
                        await self.broadcast(ev)

                    # Poll for user input (up to 30 min)
                    user_input = None
                    for _ in range(1800):
                        if self._aborted:
                            break
                        await asyncio.sleep(1)
                        if interrupted_phase in self.user_inputs:
                            user_input = self.user_inputs.pop(interrupted_phase)
                            self._save_persisted_inputs()
                            ev = self.add_event(interrupted_phase, "progress", "User input received")
                            await self.broadcast(ev)
                            break

                    if self._aborted:
                        break

                    if user_input is None:
                        user_input = {"approved": True, "interview_notes": ""}
                        ev = self.add_event(interrupted_phase, "progress", f"{interrupted_phase} auto-approved (timeout)")
                        await self.broadcast(ev)

                    self.waiting_for = None

                    # Resume: normalize user_input to a dict for the node's interrupt() return value
                    if interrupted_phase == "DISCOVER":
                        # Bridge stores raw value (could be str or dict from UI)
                        # Node's interrupt() expects dict; normalize to {key: value}
                        if isinstance(user_input, dict):
                            resume_data = user_input
                        elif isinstance(user_input, str):
                            resume_data = {"interview_notes": user_input}
                        else:
                            resume_data = {"interview_notes": str(user_input)}
                    elif interrupted_phase == "ARCH_REVIEW" or interrupted_type == "review":
                        # ARCH_REVIEW may still show phase="PLAN" in checkpoint — use interrupted_type.
                        resume_data = {
                            "approved": bool(user_input.get("approved", True)),
                            "feedback": user_input.get("feedback", user_input.get("user_review_comments", "")),
                        }
                    else:
                        resume_data = {"human_approval_required": False}

                    print(f"  → Resuming {interrupted_phase} with Command(resume=...)")
                    # Resume workflow and update status
                    self.status = "running"
                    self.waiting_for = None
                    input_state = Command(resume=resume_data)
                    continue
                else:
                    # Normal completion (no interrupt)
                    if self._last_phase:
                        ev = self.add_event(self._last_phase, "completed", f"{self._last_phase} completed")
                        await self.broadcast(ev)
                    completed = True  # Prevent outer loop from re-entering
                    break  # break inner loop, then outer loop exits below

            # Mark workflow complete
            if not self._aborted:
                self.status = "complete"
                self.current_phase = ""
                self.waiting_for = None
                ev = self.add_event("SYSTEM", "completed", f"Cycle {self.cycle} complete — all phases done")
                await self.broadcast(ev)

        except asyncio.CancelledError:
            # Only reset to idle if we didn't already complete successfully
            if self.status != "complete":
                import traceback, sys
                print(f"[Bridge] CancelledError caught (non-fatal, already completed) — stacktrace:", flush=True)
                traceback.print_exc()
                exc_type, exc_value, exc_tb = sys.exc_info()
                print(f"[Bridge] CancelledError origin: {exc_tb}", flush=True)
                self.status = "idle"
                self.current_phase = ""
                self.waiting_for = None
            else:
                # Already marked complete — keep status="complete"
                print(f"[Bridge] CancelledError ignored (status=complete)", flush=True)
        except Exception as e:
            self.status = "error"
            ev = self.add_event("SYSTEM", "error", f"Workflow failed: {str(e)[:200]}")
            await self.broadcast(ev)
            raise

    def _build_executor_state(self, cycle_id, project_name, spec_text, context_folder):
        """Build state via shared executor — identical to what CLI uses."""
        from graph.executor import build_executor_state
        return build_executor_state(
            cycle_id=cycle_id,
            project_name=project_name,
            spec_text=spec_text,
            context_folder=context_folder,
        )

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
