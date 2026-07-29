# Loop Engineering — Request/Response Logging Middleware

import time
import uuid
from contextvars import ContextVar

from log.logging import setup_logger, log_event

logger = setup_logger("api")

# ── Correlation ID context ──────────────────────────────────────
_correlation_id_var: ContextVar[str | None] = ContextVar("_correlation_id", default=None)


def generate_correlation_id() -> str:
    """Generate a 32-char hex correlation ID (UUID4 without dashes)."""
    return uuid.uuid4().hex


def get_correlation_id() -> str | None:
    """Get the current correlation ID."""
    return _correlation_id_var.get()


def set_correlation_id(cid: str) -> None:
    """Set the correlation ID in the current context."""
    _correlation_id_var.set(cid)


def reset_correlation_id() -> None:
    """Clear the correlation ID."""
    _correlation_id_var.set(None)


# ── Legacy log helpers ────────────────────────────────────────

def log_request(action: str, **kwargs):
    """Log API request/response with correlation ID and metadata."""
    log_event(logger, "api.request", action=action, **kwargs)


def log_llm_call(skill: str, phase: str, system_prompt: str, user_prompt: str, response: str, duration_s: float, model: str = "unknown"):
    """Log LLM prompt/response for debugging and auditing."""
    log_event(logger, "llm.call", skill=skill, phase=phase, model=model, duration_s=round(duration_s, 3),
              system_prompt_preview=system_prompt[:200], user_prompt_preview=user_prompt[:200],
              response_preview=response[:200])


# ── FastAPI Middleware ────────────────────────────────────────

class RequestLoggingMiddleware:
    """ASGI middleware that adds correlation IDs and logs requests."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.time()
        cid = generate_correlation_id()
        set_correlation_id(cid)

        try:
            await self.app(scope, receive, send)
        except Exception:
            duration = time.time() - start
            log_request("error", correlation_id=cid, duration_s=round(duration, 3))
            reset_correlation_id()
            raise
        finally:
            reset_correlation_id()

    async def dispatch(self, request, call_next):
        """Starlette-style dispatch for middleware chaining."""
        start = time.time()
        # Reuse client-provided correlation ID or generate new one
        cid = request.headers.get("X-Correlation-ID") or generate_correlation_id()
        set_correlation_id(cid)
        try:
            response = await call_next(request)
            response.headers["X-Correlation-ID"] = cid
            return response
        except Exception:
            log_request("error", correlation_id=cid, duration_s=round(time.time() - start, 3))
            raise
        finally:
            reset_correlation_id()
