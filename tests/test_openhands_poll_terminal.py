"""
Tests for the terminal-404 fix in _poll_conversation (openhands_build).

When the OpenHands agent-server restarts mid-BUILD, its in-memory
conversation store is wiped and every poll returns 404. Before the fix,
the poller looped until BUILD_TIMEOUT (a 20+ minute stall). Now a 404
is terminal: _poll_conversation returns None immediately and the
delegate falls back to the local subgraph.

Conventions follow tests/test_w2_wayforward.py: plain pytest +
monkeypatch, no LLM calls, no aiosqlite, no real asyncio.to_thread.
"""

import httpx
from types import SimpleNamespace

from graph.nodes import openhands_build as ob


class FakeClient:
    """Records .get() calls and serves queued responses (or raises)."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []  # one entry per .get(url, **kw) call

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _resp(status_code, body):
    return SimpleNamespace(status_code=status_code, json=lambda: body)


def _patch_sleep(monkeypatch):
    sleeps = []
    monkeypatch.setattr(ob.time, "sleep", lambda s: sleeps.append(s))
    return sleeps


# ── 1. 404 is terminal ───────────────────────────────────────────────


def test_poll_404_is_terminal(monkeypatch):
    sleeps = _patch_sleep(monkeypatch)
    client = FakeClient([_resp(404, {"detail": "Not Found"})])

    result = ob._poll_conversation(client, "conv-x", "key", timeout=3600)

    assert result is None
    assert len(client.calls) == 1  # no retry loop
    assert sleeps == []  # never slept


# ── 2. success path intact ───────────────────────────────────────────


def test_poll_finished_still_returns_response(monkeypatch):
    _patch_sleep(monkeypatch)
    client = FakeClient(
        [
            _resp(200, {"execution_status": "running"}),
            _resp(200, {"execution_status": "finished"}),
            _resp(200, {"response": "done"}),
        ]
    )

    result = ob._poll_conversation(client, "conv-x", "key", timeout=3600)

    assert result == "done"
    assert len(client.calls) == 3
    assert client.calls[-1][0].endswith("/agent_final_response")


# ── 3. transient error keeps looping ─────────────────────────────────


def test_poll_transient_error_keeps_looping(monkeypatch):
    sleeps = _patch_sleep(monkeypatch)
    client = FakeClient(
        [
            httpx.HTTPError("connection reset"),
            _resp(200, {"execution_status": "finished"}),
            _resp(200, {"response": "done"}),
        ]
    )

    result = ob._poll_conversation(client, "conv-x", "key", timeout=3600)

    assert result == "done"
    assert len(client.calls) == 3
    assert len(sleeps) == 1  # one sleep after the transient error


# ── 4. delegate falls back when the poll returns None ───────────────


def test_delegate_falls_back_when_poll_lost(monkeypatch, tmp_path):
    monkeypatch.setattr(ob, "_build_prompt", lambda state: "build it")
    monkeypatch.setattr(
        ob, "_create_conversation", lambda client, prompt, pp, key: "conv-x"
    )
    monkeypatch.setattr(ob, "_poll_conversation", lambda *a, **k: None)

    fallback_calls = []

    def fake_local(state):
        fallback_calls.append(state)
        return {"phase": "BUILD", "artifacts": {"build_status": "pass"}}

    monkeypatch.setattr(ob, "_run_local_subgraph", fake_local)

    class FakeHttpxClient:
        def __enter__(self):
            return object()

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(ob.httpx, "Client", lambda **kw: FakeHttpxClient())

    oh_cfg = SimpleNamespace(url="http://gateway:8000", secret_key="k", timeout=60)
    state = {"project_path": str(tmp_path), "artifacts": {}}

    result = ob._delegate_to_openhands(state, oh_cfg)

    assert fallback_calls == [state]  # called exactly once, with state
    assert result == {"phase": "BUILD", "artifacts": {"build_status": "pass"}}
