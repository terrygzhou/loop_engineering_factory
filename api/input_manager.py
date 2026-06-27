"""
Async input management — replaces blocking input() with async input queues,
timeout handling, and WebSocket support for non-blocking workflow input.
"""
import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class InputRequest:
    """A single input request that the workflow is waiting to collect."""
    request_id: str
    phase: str
    question: str
    timeout: int = 300
    created_at: float = field(default_factory=time.time)
    response: Optional[dict] = None
    resolved: bool = False

    @property
    def is_expired(self) -> bool:
        return time.time() - self.created_at > self.timeout


class InputManager:
    """
    Manages async input requests for the workflow.
    Replaces blocking input() with async queues that support timeouts.
    """

    def __init__(self, default_timeout_s: int = 300, auto_approve_on_timeout: bool = True):
        self._requests: Dict[str, InputRequest] = {}
        self._default_timeout = default_timeout_s
        self._auto_approve_on_timeout = auto_approve_on_timeout

    def create_request(self, phase: str, question: str, timeout: Optional[int] = None) -> InputRequest:
        """Create a new input request and return it."""
        req = InputRequest(
            request_id=str(uuid.uuid4()),
            phase=phase,
            question=question,
            timeout=timeout or self._default_timeout,
        )
        self._requests[req.request_id] = req
        return req

    async def collect_input(self, req: InputRequest) -> dict:
        """
        Collect input for a request with timeout.
        Returns the collected input or auto-response on timeout.
        """
        while not req.resolved and not req.is_expired:
            await asyncio.sleep(0.5)

        if req.response:
            return req.response

        # Timeout — auto-approve or return default
        if self._auto_approve_on_timeout:
            return {"approved": True, "auto_approved": True}
        return {"approved": False, "feedback": "Timeout — no response received"}

    def submit_response(self, request_id: str, response: dict) -> bool:
        """Submit a response for a pending input request."""
        req = self._requests.get(request_id)
        if not req or req.resolved:
            return False
        req.response = response
        req.resolved = True
        return True

    def get_pending(self) -> list[InputRequest]:
        """Get all pending (non-resolved) input requests."""
        return [r for r in self._requests.values() if not r.resolved]

    def get_active_requests(self) -> Dict[str, InputRequest]:
        """Get active request IDs for pending inputs."""
        return {k: v for k, v in self._requests.items() if not v.resolved}

    def cleanup_resolved(self, keep_seconds: int = 60) -> int:
        """Remove resolved requests older than keep_seconds."""
        cutoff = time.time() - keep_seconds
        resolved = [
            r for r in self._requests.values()
            if r.resolved and r.created_at < cutoff
        ]
        for r in resolved:
            del self._requests[r.request_id]
        return len(resolved)
