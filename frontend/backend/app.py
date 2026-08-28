"""
Loop Engineering UI Backend — FastAPI + WebSocket + SSE
Uses WorkflowBridge to run the actual LangGraph workflow or a simulated one.
"""

import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ─── OpenTelemetry (manual — no auto-instrumentation deps) ──
try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    _OTEL_AVAILABLE = True
except ImportError:
    _OTEL_AVAILABLE = False

tracer = None  # type: ignore

# ─── Import the Workflow Bridge ────────────────────────────────
try:
    from backend.workflow_bridge import WorkflowBridge
except ImportError:
    # Fallback: add backend to path
    sys.path.insert(0, str(Path(__file__).parent))
    from workflow_bridge import WorkflowBridge


# ─── Models ────────────────────────────────────────────────────────────────


class UserInput(BaseModel):
    phase: str
    input_type: str
    value: Any


class StartRequest(BaseModel):
    """User provides project name, requirements, and optional context folder."""

    project_name: str = ""
    spec: str = ""
    context_folder: str = (
        ""  # Path to existing codebase/docs folder; empty = skip DISCOVER
    )
    auto_approve: Optional[bool] = None  # None = use config.yaml default


class WorkflowResponse(BaseModel):
    status: str
    phase: str
    cycle: int
    phases: List[Dict[str, Any]]
    waiting_for: Optional[str] = None
    messages: List[Dict[str, Any]] = []


# ─── App Setup ─────────────────────────────────────────────────────────────

app = FastAPI(title="Loop Engineering UI", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Single shared bridge instance
bridge = WorkflowBridge()


@app.on_event("startup")
async def startup():
    # ── Initialise OpenTelemetry ──
    global tracer
    if _OTEL_AVAILABLE:
        endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
        service = os.environ.get("OTEL_SERVICE_NAME", "loop-ui")
        if endpoint:
            provider = TracerProvider()
            exporter = OTLPSpanExporter(endpoint=endpoint)
            processor = BatchSpanProcessor(exporter)
            provider.add_span_processor(processor)
            trace.set_tracer_provider(provider)
            tracer = trace.get_tracer("loop.ui")
            print(f"✓ OTEL tracing enabled → {endpoint} (service={service})")
        else:
            print("⚠ OTEL env vars not set — tracing disabled")
    else:
        print("⚠ opentelemetry packages not installed — tracing disabled")

    print("✓ Loop Engineering UI backend started")
    bridge._try_import_real()
    if bridge._use_real_workflow:
        print("✓ Real workflow available — will use actual LangGraph nodes")
    else:
        print("⚠ Real workflow unavailable — will use simulated mode")
    # Recover workflow if checkpoint exists from a previous session
    asyncio.create_task(bridge._recover_workflow())


@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    """Serve the main HTML page."""
    frontend_path = Path(__file__).parent.parent / "static" / "index.html"
    if frontend_path.exists():
        return HTMLResponse(content=frontend_path.read_text())
    return HTMLResponse(content="<h1>Frontend not found</h1>")


@app.get("/api/status")
async def get_status():
    """Get current workflow status.

    Priority:
    1. Local bridge state (if a workflow is running via the UI)
    2. Orchestrator persisted state (shared volume from orchestrator container)
    3. Idle fallback
    """
    # If local bridge is actively running, use its state
    if bridge.status in ("running", "waiting"):
        return WorkflowResponse(
            status=bridge.status,
            phase=bridge.current_phase,
            cycle=bridge.cycle,
            phases=list(bridge.phase_states.values()),
            waiting_for=bridge.waiting_for,
            messages=bridge.events[-50:],
        )

    # Fall back to checkpoint DB (SQLite)
    orch = bridge._load_checkpoint_status()
    if orch:
        return WorkflowResponse(
            status=orch["status"],
            phase=orch["phase"],
            cycle=int(orch["cycle"])
            if isinstance(orch["cycle"], str)
            else orch["cycle"],
            phases=orch["phases"],
            waiting_for=orch.get("waiting_for"),
            messages=orch.get("messages", []),
        )

    # Idle fallback
    return WorkflowResponse(
        status="idle",
        phase="",
        cycle=0,
        phases=list(bridge.phase_states.values()),
        waiting_for=None,
        messages=[],
    )


@app.get("/api/metrics")
async def get_metrics():
    """Get current cycle metrics and thresholds."""
    from config.guardrails import _DEFAULTS

    # Gather metrics from the current workflow state via the runner
    metrics = {}
    if bridge._use_real_workflow and bridge._last_phase:
        # Try to extract metrics from phase artifacts
        for ps in bridge.phase_states.values():
            if ps.get("status") == "complete":
                artifacts = ps.get("artifacts", {})
                if "metrics" in artifacts:
                    metrics = artifacts["metrics"]
    return {
        "current": metrics if metrics else {},
        "thresholds": _DEFAULTS,
    }


@app.get("/api/phases")
async def get_phases():
    """Get phase details."""
    return list(bridge.phase_states.values())


@app.post("/api/start")
async def start_workflow(req: StartRequest):
    """Start a new workflow cycle with user requirements.

    If a workflow is already running, return an error instead of
    starting a second one in parallel.
    """
    if bridge.status in ("running", "waiting"):
        return {"status": "error", "message": "Workflow already running — abort first"}
    # Always force fresh workflow — don't reuse stale thread_id from recovery
    bridge._thread_id = None
    bridge._checkpointer = None
    bridge._seen_artifacts = {}
    bridge._spec_text = req.spec
    bridge._project_name = req.project_name
    bridge._context_folder = req.context_folder
    bridge._aborted = False
    # auto_approve defaults from config.yaml; Web UI may override via StartRequest
    if req.auto_approve is not None:
        bridge._auto_approve = req.auto_approve
    bridge._run_task = asyncio.create_task(bridge.run_real())

    # Log exceptions from background task (previously silently swallowed)
    async def log_task_errors(task):
        try:
            await task
        except BaseException as e:
            # Don't override status if workflow completed successfully
            if bridge.status != "complete":
                import traceback

                print(
                    f"[APP] Workflow task exception: {type(e).__name__}: {e}",
                    flush=True,
                )
                traceback.print_exc()
                bridge.status = "idle"
                bridge.waiting_for = None
                bridge.current_phase = None

    asyncio.create_task(log_task_errors(bridge._run_task))
    return {"status": "started", "cycle": bridge.cycle}


@app.post("/api/abort")
async def abort_workflow():
    """Abort the running workflow and reset state."""
    if bridge.status not in ("running", "waiting"):
        return {"status": "not_running"}
    result = await bridge.abort()
    return result


@app.post("/api/input")
async def submit_input(user_input: UserInput):
    """Submit user input for a waiting phase."""
    bridge.user_inputs[user_input.phase] = user_input.value
    bridge._save_persisted_inputs()
    # Wake up the polling waiter
    if user_input.phase in bridge._input_events:
        bridge._input_events[user_input.phase].set()
    return {"status": "received", "phase": user_input.phase}


@app.websocket("/ws/progress")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket for real-time progress updates."""
    await bridge.connect_ws(websocket)
    try:
        while True:
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        await bridge.disconnect_ws(websocket)


# Mount static files
static_path = Path(__file__).parent.parent / "static"
if static_path.exists():
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8011)
