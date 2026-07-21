"""
OpenTelemetry instrumentation for Loop Engineering.

Architecture:
    orchestrator (OTel SDK) → OTel Collector → Phoenix UI

Graceful degradation — never crashes if OTel is unavailable.
"""
import time
from contextlib import contextmanager
from typing import Any, Optional

# Graceful import — OTel may not be installed
_import_error: Optional[str] = None
try:
    from opentelemetry import trace  # type: ignore
    from opentelemetry.sdk.resources import Resource  # type: ignore
    from opentelemetry.sdk.trace import TracerProvider  # type: ignore
    from opentelemetry.sdk.trace.export import BatchSpanProcessor  # type: ignore
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter  # type: ignore
except ImportError as e:
    _import_error = str(e)

__all__ = ["tracer", "OTelTracer"]

_configured = False

def setup_otel() -> bool:
    """Configure OTel SDK. Idempotent — returns False if already configured."""
    global _configured
    if _configured:
        return False
    if _import_error:
        return False

    from config.loader import config as _cfg
    resource = Resource.create({
        "service.name": _cfg.services.otel.service_name,
        "service.version": "1.0.0",
    })
    provider = TracerProvider(resource=resource)
    endpoint = _cfg.services.otel.endpoint
    exporter = OTLPSpanExporter(endpoint=endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _configured = True
    return True

class OTelTracer:
    """Facade for OTel tracing — graceful degradation if OTel unavailable."""

    def __init__(self):
        self._configured = False
        self._root_cm: Any = None
        self._root_span: Any = None

    def configure(self):
        """Enable OTel if available."""
        if not self._configured:
            setup_otel()
            self._configured = True

    def is_configured(self) -> bool:
        return self._configured and _import_error is None

    # ── Workflow lifecycle ──

    def start_workflow(self, project_name: str, spec_text: str = ""):
        """Open the root workflow span."""
        if not self.is_configured():
            return None
        cm = trace.get_tracer("workflow").start_as_current_span(
            "workflow.run",
            attributes={
                "workflow.project": project_name,
                "workflow.spec": spec_text[:2000] if spec_text else "",
            },
        )
        self._root_cm = cm
        self._root_span = cm.__enter__()
        self._root_span.add_event("workflow.started")
        return self._root_span

    def end_workflow(self, status: str = "completed", error: Optional[str] = None):
        """Close the root workflow span."""
        if self._root_span:
            self._root_span.add_event(
                f"workflow.{status}",
                attributes={"status": status, "error": error or ""},
            )
            self._root_span.end()
        if self._root_cm:
            self._root_cm.__exit__(None, None, None)
            self._root_cm = None
        self._root_span = None

    # ── Phase spans ──

    def record_phase(self, phase: str, duration_s: float, success: bool = True, **attrs):
        """Emit a phase-completed span."""
        if not self.is_configured():
            return
        span = trace.get_tracer("workflow").start_span(
            f"phase.{phase.lower()}",
            attributes={
                "phase": phase,
                "duration_s": round(duration_s, 3),
                "success": success,
                **attrs,
            },
        )
        if not success:
            span.add_event("phase.error")
        span.end()

    # ── LLM spans ──

    def record_llm_call(self, skill: str, model: str, prompt_len: int,
                        response_len: int, duration_s: float, error: Optional[str] = None):
        """Emit a span for each LLM invocation.

        Uses OpenInference semantic conventions so Phoenix can extract
        model name, token counts, and cost from standard attributes.
        """
        if not self.is_configured():
            return
        total_tokens = prompt_len + response_len
        # OpenInference semantic conventions (v0.1.0+)
        span = trace.get_tracer("llm").start_span(
            "llm.invoke",
            attributes={
                # ── OpenInference: standard attributes ──
                "gen_ai.operation.name": "chat.completions",
                "gen_ai.request.model": model,
                "gen_ai.request.type": "chat",
                "gen_ai.request.input.token_usage": prompt_len,
                "gen_ai.response.model": model,
                "gen_ai.response.output.token.usage": response_len,
                "gen_ai.usage.total_tokens": total_tokens,
                "gen_ai.usage.input_tokens": prompt_len,
                "gen_ai.usage.output_tokens": response_len,
                # ── Custom: skill context ──
                "llm.skill": skill,
                "llm.duration_s": round(duration_s, 3),
                "workflow.duration_s": round(duration_s, 3),
            },
        )
        if error:
            span.add_event("llm.error", attributes={"error": error[:2000]})
            span.set_status(trace.StatusCode.ERROR, error)
        span.end()

    # ── Error recording ──

    def record_error(self, phase: str, error: str):
        """Attach an error event to the active span."""
        if self._root_span:
            self._root_span.add_event(
                "workflow.error",
                attributes={"phase": phase, "error": error[:2000]},
            )

    # ── Context manager for phases ──

    @contextmanager
    def phase_span(self, phase: str, **attrs):
        """Context manager that auto-timers phases and records metrics."""
        start = time.time()
        cm = None
        span = None
        try:
            if self.is_configured():
                cm = trace.get_tracer("workflow").start_as_current_span(
                    f"phase.{phase.lower()}",
                    attributes={"phase": phase, **attrs},
                )
                span = cm.__enter__()
                yield span
                span.set_attribute("duration_s", round(time.time() - start, 3))
                span.end()
            else:
                yield None
        except Exception as e:
            self.record_error(phase, str(e))
            raise
        finally:
            if cm:
                cm.__exit__(None, None, None)

# Module-level singleton — import anywhere
tracer = OTelTracer()
