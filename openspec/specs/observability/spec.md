# observability

## Purpose
In-process metrics, distributed tracing, and per-cycle audit trails.

## Requirements

### Requirement: Health and metrics endpoints
service/health.py SHALL serve /health, /ready, and /metrics on the in-process
server :8081 inside the container (published as :48081 on the host),
exposing workflow_duration_seconds, phase_duration_seconds,
phase_errors_total, llm_calls_total, and active_workflows.

#### Scenario: Scrape
- **WHEN** a client GETs http://localhost:48081/metrics
- **THEN** the five Prometheus series above are present

### Requirement: Readiness probe
The health server SHALL serve /ready reporting component dependency status
(ChromaDB reachability).

#### Scenario: Dependency unreachable
- **WHEN** the ChromaDB service is unreachable and a client GETs /ready
- **THEN** the response reports the dependency as down while /health stays up

### Requirement: Distributed tracing
The system SHALL emit OpenTelemetry traces to the Phoenix collector
(:46006) via service/otel_instrumentor.py, and per-cycle audit JSONL records
to build/audit_logs/ via tools/audit_logger.py (AuditLog.log_node_input /
log_node_output from every node).

#### Scenario: Audit completeness
- **WHEN** a full cycle completes
- **THEN** every phase has input and output audit records under
  build/audit_logs/
