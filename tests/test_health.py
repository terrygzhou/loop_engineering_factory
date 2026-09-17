"""Tests for service/health.py — HTTP endpoints, metrics tracking."""
import json
import sys
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _make_handler(path: str):
    """Construct a HealthHandler with mocked response methods.

    Uses a socketpair so the handler parses the requestline, then replaces
    response-writing methods with MagicMock for assertions.
    """
    import socket
    from service.health import HealthHandler
    sock_a, sock_b = socket.socketpair()
    try:
        sock_a.settimeout(0.1)
        sock_b.sendall(b"GET " + path.encode() + b" HTTP/1.1\r\nHost: localhost\r\n\r\n")
        # Third arg is typed BaseServer; None is fine at runtime (handler is
        # never served — we parse the request line, then mock the response).
        handler = HealthHandler(sock_a, ("127.0.0.1", 0), None)  # type: ignore[arg-type]
        # Mock response methods so we can assert on them
        handler.send_response = MagicMock()  # type: ignore[method-assign]
        handler.send_header = MagicMock()  # type: ignore[method-assign]
        handler.end_headers = MagicMock()  # type: ignore[method-assign]
        handler.wfile = MagicMock()
        return handler
    finally:
        sock_a.close()
        sock_b.close()


class TestHealthHandler:
    """Test HealthHandler HTTP endpoints."""

    def test_health_endpoint(self):
        handler = _make_handler("/health")
        handler._health()
        handler.send_response.assert_called_with(200)
        written = handler.wfile.write.call_args[0][0]
        data = json.loads(written)
        assert data["status"] == "healthy"
        assert "uptime_s" in data
        assert "timestamp" in data

    def test_ready_endpoint_deps_ok(self):
        handler = _make_handler("/ready")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("httpx.get", return_value=mock_resp):
            with patch("config.loader.config") as mock_cfg:
                mock_cfg.services.chroma.url = "http://chroma:8000"
                handler._ready()
        handler.send_response.assert_called_with(200)
        written = handler.wfile.write.call_args[0][0]
        data = json.loads(written)
        assert data["status"] == "ready"
        assert data["deps"]["chromadb"] is True

    def test_ready_endpoint_chroma_unreachable(self):
        handler = _make_handler("/ready")
        with patch("httpx.get", side_effect=Exception("connection refused")):
            with patch("config.loader.config") as mock_cfg:
                mock_cfg.services.chroma.url = "http://chroma:8000"
                handler._ready()
        handler.send_response.assert_called_with(503)
        written = handler.wfile.write.call_args[0][0]
        data = json.loads(written)
        assert data["status"] == "not_ready"
        assert data["deps"]["chromadb"] is False

    def test_metrics_endpoint(self):
        handler = _make_handler("/metrics")
        handler._metrics()
        handler.send_response.assert_called_with(200)
        handler.send_header.assert_called_with(
            "Content-Type", "text/plain; charset=utf-8"
        )

    def test_404_unhandled_path(self):
        handler = _make_handler("/unknown")
        handler.do_GET()
        handler.send_response.assert_called_with(404)

    def test_do_GET_routes_health(self):
        handler = _make_handler("/health")
        handler._health = MagicMock()
        handler.do_GET()
        handler._health.assert_called_once()

    def test_do_GET_routes_metrics(self):
        handler = _make_handler("/metrics")
        handler._metrics = MagicMock()
        handler.do_GET()
        handler._metrics.assert_called_once()

    def test_do_GET_routes_ready(self):
        handler = _make_handler("/ready")
        handler._ready = MagicMock()
        handler.do_GET()
        handler._ready.assert_called_once()


class TestHealthServer:
    """Test start_health_server and lifecycle."""

    def test_start_server_returns_server(self):
        import service.health as health
        old_server = health._health_server
        try:
            health._health_server = None
            with patch("config.loader.config") as mock_cfg:
                mock_cfg.services.observability.port = 0
                server = health.start_health_server()
            assert server is not None
            assert isinstance(server, HTTPServer)
            health._health_server = server
        finally:
            if health._health_server is not None:
                health._health_server.shutdown()
            health._health_server = old_server

    def test_duplicate_start_skips(self):
        import service.health as health
        old_server = health._health_server
        try:
            existing = MagicMock()
            health._health_server = existing
            with patch("config.loader.config") as mock_cfg:
                mock_cfg.services.observability.port = 0
                result = health.start_health_server(8081)
            assert result == existing
        finally:
            health._health_server = old_server

    def test_shutdown_health_server(self):
        import service.health as health
        server_mock = MagicMock()
        old = health._health_server
        health._health_server = server_mock
        health._shutdown_health_server()
        server_mock.shutdown.assert_called_once()
        health._health_server = old


class TestTrackWorkflow:
    """Test workflow tracking functions."""

    def test_track_workflow_start(self):
        import service.health as health
        health.track_workflow_start("test-proj")
        assert "test-proj" in health._active_workflows
        assert len(health._active_workflows) == 1
        health.track_workflow_end("test-proj", 1.0)

    def test_track_workflow_end(self):
        import service.health as health
        health.track_workflow_start("test-proj")
        health.track_workflow_end("test-proj", 2.5)
        assert "test-proj" not in health._active_workflows
        assert len(health._active_workflows) == 0

    def test_track_workflow_error(self):
        import service.health as health
        health.track_workflow_start("test-proj")
        health.track_workflow_error("test-proj")
        assert "test-proj" not in health._active_workflows

    def test_track_phase_success(self):
        import service.health as health
        health.track_phase("DISCOVER", 5.0, success=True)

    def test_track_phase_failure(self):
        import service.health as health
        health.track_phase("PLAN", 3.0, success=False)


class TestTrackLLM:
    """Test LLM tracking functions."""

    def test_track_llm_success(self):
        import service.health as health
        health.track_llm("fabric-prompts", 2.0, success=True)

    def test_track_llm_error(self):
        import service.health as health
        health.track_llm("coding-principles", 5.0, success=False)


class TestSetCurrentPhase:
    """Test set_current_phase."""

    def test_set_phase(self):
        import service.health as health
        health.set_current_phase("test-proj", "BUILD")
