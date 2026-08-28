---
name: performance-optimization
description: >
  Measure-first performance optimization for FastAPI services. Profile
  before optimizing, use Core Web Vitals for frontend, enforce SLA
  targets, and apply proven techniques (caching, batching, query
  optimization) only where metrics show a problem.
version: 1.0.0
author: hermes
triggers:
  - "slow"
  - "performance"
  - "optimize"
  - "speed up"
  - "latency"
  - "benchmark"
  - "profile"
  - "performance issue"
  - "too slow"
  - "needs to be faster"
tools:
  - read_file
  - write_file
  - search_files
  - patch
  - terminal
---

# performance-optimization

## Purpose

Optimize performance based on measured data, not intuition. Profile the
system, identify bottlenecks, apply targeted fixes, and verify
improvement. Prevents the most common performance anti-pattern:
optimizing the wrong thing.

## Process

### 1. Establish baseline metrics

Before changing anything, measure the current performance:

**For FastAPI endpoints:**
```bash
# Install httpie and ab (Apache Benchmark) for quick testing
pip install httpie
sudo apt install apache2-utils

# Measure request latency
ab -n 100 -c 10 http://localhost:8000/api/v1/items
curl -w "\nDNS: %{time_namelookup}\nConnect: %{time_connect}\nTTFB: %{time_starttransfer}\nTotal: %{time_total}\n" http://localhost:8000/api/v1/items
```

**For Jinja2 templates:**
- Measure template render time with `time` decorator
- Check if template includes heavy logic or large data sets

**Key metrics to record:**
- P50, P95, P99 latency per endpoint
- Requests per second (RPS)
- Memory usage (RSS)
- CPU utilization
- Database query count and time per request

### 2. Identify the bottleneck

Profile the slow path:

```python
# Add to your FastAPI app for profiling
import cProfile
import pstats
from io import StringIO


@app.middleware("http")
async def profile_request(request: Request, call_next):
    if request.query_params.get("profile"):
        pr = cProfile.Profile()
        pr.enable()
        response = await call_next(request)
        pr.disable()
        s = StringIO()
        ps = pstats.Stats(pr, stream=s).sort_stats("cumulative")
        ps.print_stats(20)
        print(s.getvalue())
        return response
    return await call_next(request)
```

Common bottleneck locations in FastAPI + Docker stacks:

| Location | Symptoms | Fix |
|---|---|---|
| N+1 queries | Slow list endpoints | Eager loading, batch queries |
| Missing DB indexes | Slow lookups | Add indexes on filtered columns |
| Template rendering | Slow HTML routes | Precompute data, cache templates |
| Large JSON payloads | Slow serialization | Field selection, pagination |
| Uncompressed responses | High bandwidth | Enable gzip/brotli middleware |
| Cold starts | First request slow | Keep-alive, pre-warm endpoints |

### 3. Apply targeted optimizations

**Priority order — fix in this order:**

1. **Database optimization** (highest ROI)
   - Add missing indexes: `CREATE INDEX idx_items_name ON items(name)`
   - Use `SELECT` only needed columns, not `SELECT *`
   - Batch queries instead of per-item lookups
   - Use `joinedload`/`subqueryload` for relationships

2. **Caching**
   - Response caching for read-heavy endpoints:
     ```python
     from fastapi_cache import FastAPICache
     from fastapi_cache.backends.inmemory import InMemoryBackend

     FastAPICache.init(InMemoryBackend(), prefix="redis")


     @router.get("/items", response_model=list[ItemResponse])
     @cache(expire=60)  # Cache for 60 seconds
     async def list_items(): ...
     ```
   - For Docker deployments, consider Redis as external cache

3. **Serialization optimization**
   - Limit response fields with `response_model`
   - Paginate list responses (never return all rows)
   - Use `json_encoders` for efficient datetime serialization

4. **Middleware optimization**
   - Enable gzip/brotli compression:
     ```python
     from starlette.middleware.gzip import GZipMiddleware

     app.add_middleware(GZipMiddleware, minimum_size=1000)
     ```
   - Reduce middleware chain (each adds overhead)

5. **Async correctness**
   - Ensure all I/O is async (database, HTTP calls, file I/O)
   - Don't block the event loop with synchronous code
   - Use `asyncpg` instead of `psycopg2` for PostgreSQL

6. **Container optimization**
   - Multi-stage Docker builds to reduce image size
   - Use `uvicorn` with multiple workers: `uvicorn main:app --workers 4`
   - Set appropriate timeout and keepalive values

### 4. Verify improvement

After each optimization, re-measure with the same benchmark:

```
BEFORE: P95 latency = 250ms, RPS = 40
AFTER:  P95 latency = 80ms,  RPS = 120
```

Keep a changelog of optimizations and their impact.

### 5. Document SLA targets

Define and document performance targets:

```
SLA Targets:
- P95 API response time: < 200ms
- P99 API response time: < 500ms
- Template render time: < 100ms
- Database query time: < 50ms (single), < 200ms (paginated list)
- Uptime: 99.9%
- Max concurrent users: 100
```

## Pitfalls

- **Don't optimize without measuring.** The slowest part of your system
  is rarely what you think it is. Profile first.
- **Don't add caching prematurely.** Caching adds complexity and
  eventual consistency problems. Only cache what's actually slow.
- **Don't ignore the database.** 80% of performance issues in web
  apps are database-related (missing indexes, N+1 queries, full scans).
- **Don't optimize for the happy path only.** Profile the P99 case,
  not just the average.
- **Don't forget about the frontend.** A 50ms backend is wasted if the
  Jinja2 template renders in 500ms.
- **Don't over-complicate with microservices** to solve a single
  endpoint's slowness. Fix the endpoint first.

## Verification

- Baseline metrics documented before optimization.
- Each optimization has a before/after measurement.
- SLA targets defined and tracked.
- P95 and P99 latency improved for the targeted endpoints.
- No regressions in other endpoints.
- Docker container still builds and runs within resource limits.
