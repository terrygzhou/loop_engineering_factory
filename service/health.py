"""
Health check and metrics endpoint for the orchestrator.

Provides HTTP endpoints for Docker health checks and Prometheus scraping.
Runs on port 8081 (configurable via OBSERVABILITY_PORT).
"""
import atexit
import json
import os
import time
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Lock, Thread
from prometheus_client import Counter, Histogram, Gauge, generate_latest  # type: ignore

# ── Prometheus metrics ──
WORKFLOW_DURATION = Histogram("workflow_duration_seconds", "Workflow cycle duration", ["project"])
PHASE_DURATION = Histogram("phase_duration_seconds", "Phase execution time", ["phase"])
PHASE_ERRORS = Counter("phase_errors_total", "Phase failures", ["phase"])
LLM_CALLS = Counter("llm_calls_total", "LLM invocations", ["skill", "status"])
LLM_DURATION = Histogram("llm_duration_seconds", "LLM call duration", ["skill"])
ACTIVE_WORKFLOWS = Gauge("active_workflows", "Currently running workflows")
WORKFLOW_PHASE = Gauge("workflow_current_phase", "Current workflow phase", ["project"])

# ── Runtime state ──
_start_time = time.time()
_active_workflows: dict[str, dict] = {}
_stats_lock = Lock()


class HealthHandler(BaseHTTPRequestHandler):
    """Minimal health check + metrics handler — no external deps."""

    def log_message(self, format, *args):  # noqa: A002
        pass  # Suppress default stderr logging

    def do_GET(self):
        if self.path == "/health":
            self._health()
        elif self.path == "/metrics":
            self._metrics()
        elif self.path == "/ready":
            self._ready()
        else:
            self.send_response(404)
            self.end_headers()

    def _health(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        data = {
            "status": "healthy",
            "uptime_s": round(time.time() - _start_time, 1),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.wfile.write(json.dumps(data).encode())

    def _ready(self):
        """Check dependencies — chromadb + OTel collector."""
        import httpx
        from config.loader import config as _cfg
        ok = True
        deps = {}
        try:
            r = httpx.get(_cfg.services.chroma.url + "/api/v1/heartbeat", timeout=3)
            deps["chromadb"] = r.status_code == 200
        except Exception:
            deps["chromadb"] = False
            ok = False

        if not ok:
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "not_ready", "deps": deps}).encode())
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "ready", "deps": deps}).encode())

    def _metrics(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(generate_latest())


def start_health_server(port: int = 0):
    """Start health server in a background thread."""
    global health_server
    if port == 0:
        from config.loader import config
        port = int(config.services.observability.port)
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    health_server = server
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"[Health] Server listening on :{port}")
    return server


def _shutdown_health_server():
    try:
        if 'health_server' in globals() and health_server:
            health_server.shutdown()
    except Exception:
        pass


atexit.register(_shutdown_health_server)


def track_workflow_start(project_name: str):
    with _stats_lock:
        _active_workflows[project_name] = {"started": time.time()}
        ACTIVE_WORKFLOWS.set(len(_active_workflows))


def track_workflow_end(project_name: str, duration: float):
    WORKFLOW_DURATION.labels(project=project_name).observe(duration)
    with _stats_lock:
        _active_workflows.pop(project_name, None)
        ACTIVE_WORKFLOWS.set(len(_active_workflows))


def track_phase(phase: str, duration: float, success: bool = True):
    PHASE_DURATION.labels(phase=phase).observe(duration)
    if not success:
        PHASE_ERRORS.labels(phase=phase).inc()


def track_llm(skill: str, duration: float, success: bool = True):
    LLM_DURATION.labels(skill=skill).observe(duration)
    LLM_CALLS.labels(skill=skill, status="success" if success else "error").inc()


def set_current_phase(project_name: str, phase: str):
    WORKFLOW_PHASE.labels(project=project_name).set(1)


if __name__ == "__main__":
    import signal
    start_health_server()
    signal.pause()
