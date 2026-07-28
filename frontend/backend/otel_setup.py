
"""
OpenTelemetry setup — manual tracer (no auto-instrumentation deps).
Wire into FastAPI startup; wrap LangGraph workflow nodes with spans.
"""
import os

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter


def setup_otel():
    """Set up OTel tracing. Returns the tracer provider."""
    endpoint = os.environ.get(
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "http://otel-collector:4318/v1/traces",
    )
    service_name = os.environ.get("OTEL_SERVICE_NAME", "loop-orchestrator")

    provider = TracerProvider()
    exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    from opentelemetry import context
    # Attach service name
    provider.resource.attributes["service.name"] = service_name
    return provider


def get_tracer(name="loop"):
    """Get a tracer by name (call after setup_otel)."""
    return trace.get_tracer(name)
