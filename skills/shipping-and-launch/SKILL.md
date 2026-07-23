---
name: shipping-and-launch
description: >
  Pre-launch checklist, feature flags, rollback plans, and launch
  safety procedures for FastAPI services in Docker. Ensures deployments
  are safe, reversible, and monitored from the moment they go live.
version: 1.0.0
author: hermes
triggers:
  - "ship"
  - "launch"
  - "deploy"
  - "release"
  - "go live"
  - "pre-launch"
  - "rollout plan"
  - "feature flag"
  - "rollback"
  - "production ready"
tools:
  - read_file
  - write_file
  - search_files
  - patch
  - terminal
---

# shipping-and-launch

## Purpose

Provide a structured approach to shipping features safely. Every
significant feature should have a launch plan that covers rollout,
monitoring, and rollback — reducing the cost of mistakes from
"rewrite everything" to "flip a flag."

## Process

### 1. Pre-launch checklist

Before marking anything as ready for production:

```
## Pre-Launch Checklist

### Code quality
- [ ] All tests pass (unit, integration)
- [ ] No failing linters (ruff, mypy)
- [ ] No TODO/FIXME comments in new code
- [ ] Secrets are environment variables, not hardcoded
- [ ] Dependencies are pinned (requirements.txt, Dockerfile)

### API surface
- [ ] All new endpoints documented in OpenAPI/Swagger
- [ ] Request validation works for edge cases (empty, null, oversized)
- [ ] Error responses follow the standardized contract
- [ ] Authentication/authorization is enforced on new endpoints

### Data
- [ ] Database migrations written and tested (Alembic)
- [ ] Migration is backward compatible (can deploy code before DB)
- [ ] Rollback migration exists
- [ ] Seed data / default values defined where needed

### Performance
- [ ] New endpoints meet SLA latency targets
- [ ] Load tested with realistic data volume
- [ ] Database indexes added for new queries
- [ ] No N+1 queries in new code paths

### Observability
- [ ] Structured logging added for new operations
- [ ] Key business events are logged (creation, deletion, failures)
- [ ] Health check covers new dependencies
- [ ] Error tracking captures new exception types

### Security
- [ ] Input validation prevents injection (SQL, XSS in Jinja2)
- [ ] Sensitive data not logged or exposed in responses
- [ ] Rate limiting applied if needed
- [ ] CORS configured correctly

### Docker
- [ ] Dockerfile builds cleanly (no warnings)
- [ ] Multi-stage build produces minimal image
- [ ] Non-root user configured
- [ ] Healthcheck passes
- [ ] docker-compose.yml updated if needed
```

### 2. Feature flags

Wrap new features behind feature flags for controlled rollout:

```python
# config/flags.py
import os

FEATURES = {
    "new_items_api": os.getenv("FEATURE_NEW_ITEMS_API", "false").lower() == "true",
    "dark_mode": os.getenv("FEATURE_DARK_MODE", "false").lower() == "true",
}

# routes/items.py
from config.flags import FEATURES

@router.post("/items")
async def create_item(body: CreateItemRequest):
    if not FEATURES["new_items_api"]:
        raise HTTPException(
            status_code=501,
            detail="This feature is not yet enabled",
        )
    # ... normal implementation
```

Rollout strategy with Docker environment variables:

```yaml
# docker-compose.staging.yml
services:
  api:
    environment:
      - FEATURE_NEW_ITEMS_API=true   # Enable in staging first
      - FEATURE_DARK_MODE=false

# docker-compose.production.yml
services:
  api:
    environment:
      - FEATURE_NEW_ITEMS_API=true   # Enable in production
      - FEATURE_DARK_MODE=false
```

### 3. Rollback plan

Document the rollback procedure **before** deploying:

```
## Rollback Plan for v1.2 (Items API)

### Trigger conditions
- P95 latency > 2s on new endpoints
- Error rate > 5% on new endpoints
- Data corruption detected
- Critical security vulnerability found

### Rollback steps
1. Revert feature flag:
   docker-compose -f production.yml exec api bash -c \
     "export FEATURE_NEW_ITEMS_API=false && uvicorn main:app --reload"

2. If database migration is irreversible, run rollback migration:
   docker-compose -f production.yml exec api alembic downgrade -1

3. Redeploy previous version:
   docker tag app-api:v1.1 app-api:latest
   docker-compose -f production.yml up -d

### Rollback verification
- Confirm /health/ready returns 200
- Verify old endpoints still work
- Check error logs for 10 minutes post-rollback
```

### 4. Launch sequence

Execute the launch in stages:

1. **Deploy to staging** — Run full integration tests.
2. **Enable feature flag in staging** — Verify new feature works.
3. **Deploy to production** — Feature flag OFF by default.
4. **Verify production health** — Health checks pass, no errors.
5. **Enable feature flag for internal** — Limited rollout to team.
6. **Monitor for 1 hour** — Check metrics, logs, error rates.
7. **Enable feature flag for all** — Full rollout.
8. **Monitor for 24 hours** — Watch for edge cases and load issues.

### 5. Post-launch monitoring

For the first 24–48 hours after launch:

- Watch error rates on new endpoints (alert if > 1%)
- Monitor P95/P99 latency trends
- Check for unhandled exceptions in logs
- Verify database query performance hasn't degraded
- Watch for unusual patterns in request volume

Set up simple alerting:

```python
# In your logging middleware
ERROR_RATE_THRESHOLD = 0.05  # 5%

if error_rate > ERROR_RATE_THRESHOLD:
    logger.critical(
        f"Error rate exceeded threshold: {error_rate:.1%}",
        extra={"error_rate": error_rate, "endpoint": endpoint},
    )
    # TODO: Send alert to Slack, PagerDuty, etc.
```

## Pitfalls

- **Don't launch without a rollback plan.** If you can't roll back in
  under 5 minutes, your launch is risky. Feature flags make rollback
  instant.
- **Don't skip staging.** Testing directly in production is not a
  strategy — it's gambling.
- **Don't enable feature flags by default in production.** They should
  start OFF and be toggled ON when you're ready.
- **Don't forget to remove old feature flags.** After a feature is
  stable for 2–4 weeks, remove the flag and clean up the conditional
  code. Feature flag debt accumulates fast.
- **Don't launch on Friday.** Deploy on Monday–Wednesday to allow
  recovery time if something goes wrong.
- **Don't launch and walk away.** Stay available for at least the first
  hour after enabling a feature.

## Verification

- Pre-launch checklist is complete (all boxes checked).
- Feature flags are implemented and togglable via environment variables.
- Rollback plan is documented and rehearsed (in staging).
- Health checks pass in production before feature flag is enabled.
- Monitoring and alerting are active for new endpoints.
- Post-launch review is scheduled for 24 hours after full rollout.
