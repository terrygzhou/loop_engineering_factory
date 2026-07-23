---
name: observability-and-instrumentation
description: >
  Add structured logging, RED metrics, error tracking, and health
  endpoints to FastAPI services. Make the system observable from the
  outside — no guessing when things break. Covers Docker-compatible
  logging and monitoring patterns.
version: 1.0.0
author: hermes
triggers:
  - "observability"
  - "instrumentation"
  - "add logging"
  - "add metrics"
  - "monitoring"
  - "health check"
  - "structured logging"
  - "error tracking"
  - "add telemetry"
tools:
  - read_file
  - write_file
  - search_files
  - patch
---

# observability-and-instrumentation

## Purpose

Make the application observable: when something goes wrong, you should
be able to diagnose it from logs, metrics, and health checks without
adding debug prints. This skill covers the three pillars of
observability: logs, metrics, and health checks.

## Process

### 1. Structured logging

Replace print statements with structured JSON logging:

```python
import logging
import json
import sys
from datetime import datetime

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "request_id"):
            log_entry["request_id"] = record.request_id
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
            }
        return json.dumps(log_entry)

# Configure root logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)  # Docker reads stdout
handler.setFormatter(JSONFormatter())
logger.addHandler(handler)
```

**Logging rules:**
- Always log to `stdout` (Docker captures this)
- Never log to files in containers (use external storage if needed)
- Include correlation IDs (`request_id`) in every log line per request
- Use structured fields for key data (user_id, endpoint, duration)
- Never log secrets, passwords, or PII

### 2. RED metrics

Implement the RED method (Rate, Errors, Duration) for each endpoint:

```python
from prometheus_fastapi_instrumentator import Instrumentator
from fastapi import FastAPI

app = FastAPI()

Instrumentator().instrument(app).expose(app)

# This auto-instruments:
# - http_request_duration_seconds (histogram by method, endpoint, status)
# - http_request_total (counter by method, endpoint, status)
```

Or manual tracking for specific hot paths:

```python
import time
from collections import defaultdict

metrics = defaultdict(lambda: {"count": 0, "errors": 0, "total_duration": 0.0})

def track_metric(endpoint: str, duration: float, error: bool = False):
    m = metrics[endpoint]
    m["count"] += 1
    if error:
        m["errors"] += 1
    m["total_duration"] += duration

# In your route:
@router.get("/items")
async def list_items():
    start = time.perf_counter()
    try:
        result = await get_items()
        track_metric("GET /items", time.perf_counter() - start)
        return result
    except Exception:
        track_metric("GET /items", time.perf_counter() - start, error=True)
        raise
```

### 3. Health endpoints

Add health and readiness endpoints:

```python
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()

@router.get("/health")
async def health_check():
    """Liveness probe — always returns 200 if the process is running."""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

@router.get("/health/ready")
async def readiness_check(session: AsyncSession = Depends(get_db)):
    """Readiness probe — checks database connectivity."""
    try:
        await session.execute(text("SELECT 1"))
        return {"status": "ready", "database": "connected"}
    except Exception as e:
        return {"status": "not_ready", "database": str(e)}, 503
```

Docker compose integration:

```yaml
services:
  api:
    image: app-api
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health/ready"]
      interval: 10s
      timeout: 5s
      retries: 3
      start_period: 30s
```

### 4. Request correlation and tracing

Add a middleware to generate and propagate request IDs:

```python
from fastapi import Request
import logging
import uuid
import sys

logger = logging.getLogger(__name__)

class CorrelationIdMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            request_id = scope.get("headers", {}).get(
                b"x-request-id", uuid.uuid4().hex
            ).decode()
            scope["request_id"] = request_id

            # Inject into logging
            extra = {"request_id": request_id}
            logger.info(f"Request started: {scope['method']} {scope['path']}", extra=extra)

        await self.app(scope, receive, send)
```

### 5. Error tracking and reporting

Set up centralized error capture:

```python
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error(
        f"Unhandled exception: {exc}",
        extra={
            "request_id": getattr(request.state, "request_id", ""),
            "method": request.method,
            "path": request.url.path,
            "client_host": request.client.host if request.client else "",
        },
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={
            "error_code": "INTERNAL_ERROR",
            "message": "An unexpected error occurred",
            "request_id": getattr(request.state, "request_id", ""),
        },
    )
```

Optional: Integrate with Sentry for production error tracking:

```python
import sentry_sdk
from sentry_sdk.integrations.starlette import StarletteIntegration

sentry_sdk.init(
    dsn=os.getenv("SENTRY_DSN"),
    integrations=[StarletteIntegration()],
    traces_sample_rate=0.1,  # 10% of requests
)
```

### 6. Docker logging configuration

Ensure Docker output is machine-parseable:

```dockerfile
# Dockerfile
ENV LOG_FORMAT=json
ENV LOG_LEVEL=info
```

Compose override for development (human-readable):

```yaml
# docker-compose.override.yml
services:
  api:
    environment:
      - LOG_FORMAT=text
      - LOG_LEVEL=debug
```

## Pitfalls

- **Don't log everything indiscriminately.** Structured logs generate
  massive volume quickly. Use appropriate levels: DEBUG for dev, INFO
  for production.
- **Don't log sensitive data.** Passwords, tokens, API keys, and PII
  should never appear in logs — even in development.
- **Don't mix logging formats.** Pick JSON or text and stick with it
  per environment. Mixing breaks log aggregation.
- **Don't forget to measure logging overhead.** Excessive logging can
  slow down hot paths. Profile with and without logging if latency is
  tight.
- **Don't rely on health checks that always pass.** A health endpoint
  that only checks "is the process alive" misses the point — check
  dependencies too.
- **Don't instrument after the incident.** Add observability during
  development, not after something breaks in production.

## Verification

- Structured JSON logs are output to stdout for every request.
- Health endpoint (`/health`) returns 200 within 1 second.
- Readiness endpoint (`/health/ready`) checks database connectivity.
- Request IDs are generated and logged for every request.
- Unhandled exceptions are logged with full context.
- RED metrics are available (Prometheus endpoint or manual tracking).
- Docker healthcheck is configured and passes.
