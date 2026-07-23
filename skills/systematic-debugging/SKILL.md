---
name: systematic-debugging
description: "4-phase root cause debugging: understand bugs before fixing."
version: 1.2.0
author: Hermes Agent (adapted from obra/superpowers)
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [debugging, troubleshooting, problem-solving, root-cause, investigation]
    related_skills: [test-driven-development, writing-plans, subagent-driven-development]
---

# Systematic Debugging

## Overview

Random fixes waste time and create new bugs. Quick patches mask underlying issues.

**Core principle:** ALWAYS find root cause before attempting fixes. Symptom fixes are failure.

**Violating the letter of this process is violating the spirit of debugging.**

## The Iron Law

```
NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST
```

If you haven't completed Phase 1, you cannot propose fixes.

## When to Use

Use for ANY technical issue:
- Test failures
- Bugs in production
- Unexpected behavior
- Performance problems
- Build failures
- Integration issues

**Use this ESPECIALLY when:**
- Under time pressure (emergencies make guessing tempting)
- "Just one quick fix" seems obvious
- You've already tried multiple fixes
- Previous fix didn't work
- You don't fully understand the issue

**Don't skip when:**
- Issue seems simple (simple bugs have root causes too)
- You're in a hurry (rushing guarantees rework)
- Someone wants it fixed NOW (systematic is faster than thrashing)

## The Four Phases

You MUST complete each phase before proceeding to the next.

---

## Phase 1: Root Cause Investigation

**BEFORE attempting ANY fix:**

### 1. Read Error Messages Carefully

- Don't skip past errors or warnings
- They often contain the exact solution
- Read stack traces completely
- Note line numbers, file paths, error codes

**Action:** Use `read_file` on the relevant source files. Use `search_files` to find the error string in the codebase.

### 2. Reproduce Consistently

- Can you trigger it reliably?
- What are the exact steps?
- Does it happen every time?
- If not reproducible → gather more data, don't guess

**Action:** Use the `terminal` tool to run the failing test or trigger the bug:

```bash
# Run specific failing test
pytest tests/test_module.py::test_name -v

# Run with verbose output
pytest tests/test_module.py -v --tb=long
```

### 3. Check Recent Changes

- What changed that could cause this?
- Git diff, recent commits
- New dependencies, config changes

**Action:**

```bash
# Recent commits
git log --oneline -10

# Uncommitted changes
git diff

# Changes in specific file
git log -p --follow src/problematic_file.py | head -100
```

### 4. Gather Evidence in Multi-Component Systems

**WHEN system has multiple components (API → service → database, CI → build → deploy):**

**BEFORE proposing fixes, add diagnostic instrumentation:**

For EACH component boundary:
- Log what data enters the component
- Log what data exits the component
- Verify environment/config propagation
- Check state at each layer

Run once to gather evidence showing WHERE it breaks.
THEN analyze evidence to identify the failing component.
THEN investigate that specific component.

### 5. Trace Data Flow

**WHEN error is deep in the call stack:**

- Where does the bad value originate?
- What called this function with the bad value?
- Keep tracing upstream until you find the source
- Fix at the source, not at the symptom

**Action:** Use `search_files` to trace references:

```python
# Find where the function is called
search_files("function_name(", path="src/", file_glob="*.py")

# Find where the variable is set
search_files("variable_name\\s*=", path="src/", file_glob="*.py")
```

### Phase 1 Completion Checklist

- [ ] Error messages fully read and understood
- [ ] Issue reproduced consistently
- [ ] Recent changes identified and reviewed
- [ ] Evidence gathered (logs, state, data flow)
- [ ] Problem isolated to specific component/code
- [ ] Root cause hypothesis formed

**STOP:** Do not proceed to Phase 2 until you understand WHY it's happening.

---

## Phase 2: Pattern Analysis

**Find the pattern before fixing:**

### 1. Find Working Examples

- Locate similar working code in the same codebase
- What works that's similar to what's broken?

**Action:** Use `search_files` to find comparable patterns:

```python
search_files("similar_pattern", path="src/", file_glob="*.py")
```

### 2. Compare Against References

- If implementing a pattern, read the reference implementation COMPLETELY
- Don't skim — read every line
- Understand the pattern fully before applying

### 3. Identify Differences

- What's different between working and broken?
- List every difference, however small
- Don't assume "that can't matter"

### 4. Understand Dependencies

- What other components does this need?
- What settings, config, environment?
- What assumptions does it make?

---

## Phase 3: Hypothesis and Testing

**Scientific method:**

### 1. Form a Single Hypothesis

- State clearly: "I think X is the root cause because Y"
- Write it down
- Be specific, not vague

### 2. Test Minimally

- Make the SMALLEST possible change to test the hypothesis
- One variable at a time
- Don't fix multiple things at once

### 3. Verify Before Continuing

- Did it work? → Phase 4
- Didn't work? → Form NEW hypothesis
- DON'T add more fixes on top

### 4. When You Don't Know

- Say "I don't understand X"
- Don't pretend to know
- Ask the user for help
- Research more

---

## Phase 4: Implementation

**Fix the root cause, not the symptom:**

### 1. Create Failing Test Case

- Simplest possible reproduction
- Automated test if possible
- MUST have before fixing
- Use the `test-driven-development` skill

### 2. Implement Single Fix

- Address the root cause identified
- ONE change at a time
- No "while I'm here" improvements
- No bundled refactoring

### 3. Verify Fix

```bash
# Run the specific regression test
pytest tests/test_module.py::test_regression -v

# Run full suite — no regressions
pytest tests/ -q
```

### 4. If Fix Doesn't Work — The Rule of Three

- **STOP.**
- Count: How many fixes have you tried?
- If < 3: Return to Phase 1, re-analyze with new information
- **If ≥ 3: STOP and question the architecture (step 5 below)**
- DON'T attempt Fix #4 without architectural discussion

### 5. If 3+ Fixes Failed: Question Architecture

**Pattern indicating an architectural problem:**
- Each fix reveals new shared state/coupling in a different place
- Fixes require "massive refactoring" to implement
- Each fix creates new symptoms elsewhere

**STOP and question fundamentals:**
- Is this pattern fundamentally sound?
- Are we "sticking with it through sheer inertia"?
- Should we refactor the architecture vs. continue fixing symptoms?

**Discuss with the user before attempting more fixes.**

This is NOT a failed hypothesis — this is a wrong architecture.

---

## Red Flags — STOP and Follow Process

If you catch yourself thinking:
- "Quick fix for now, investigate later"
- "Just try changing X and see if it works"
- "Add multiple changes, run tests"
- "Skip the test, I'll manually verify"
- "It's probably X, let me fix that"
- "I don't fully understand but this might work"
- "Pattern says X but I'll adapt it differently"
- "Here are the main problems: [lists fixes without investigation]"
- Proposing solutions before tracing data flow
- **"One more fix attempt" (when already tried 2+)**
- **Each fix reveals a new problem in a different place**

**ALL of these mean: STOP. Return to Phase 1.**

**If 3+ fixes failed:** Question the architecture (Phase 4 step 5).

### Debug principle — keep it simple

**Rule:** Always prefer the smallest fix that resolves the root cause. Do not refactor, restructure, or add new abstractions while debugging. A one-line change that closes the gap beats a multi-file refactor every time. If the fix requires touching more than one file, reconsider whether you've found the actual root cause.

### Common Pitfalls

### Multi-layer cascade from single root cause
When a fundamental model mismatch exists (e.g., `customer_id` vs `user_id`), expect **three sequential errors across three layers**:

1. **Import/Name layer** — `NameError: name 'uuid' is not defined` (wrong import style)
2. **Service/model layer** — `TypeError: 'user_id' is an invalid keyword argument` (wrong column name)
3. **Schema/serialization layer** — `ValidationError: user_id Field required` (schema field mismatch)

**Rule:** Fix all three layers in one patch. Don't fix one error and re-test — you'll just hit the next error in the cascade. Verify the complete chain before deploying.

### Multi-component stack debugging (API → DB → JS → UI)
When a full-stack issue spans multiple layers, debug **bottom-up**:

1. **DB layer** — Verify data exists: `SELECT * FROM <table> WHERE ...` inside the container. Missing rows are a frequent root cause.
2. **API layer** — `curl` the endpoint and inspect JSON. Empty arrays, 0 values, or 404s point to missing data or query bugs.
3. **JS layer** — Check console for `await` gaps. Async `mount()` without `await` → stale state.
4. **UI layer** — Verify DOM state matches API response. Blank `<strong>` tags or `$0.00` often mean data hasn't arrived yet.

**Key rule:** Never assume the bug is in the layer you first observe. A blank UI could be caused by missing DB rows, an API returning empty data, a JS race condition, or a CSS hiding issue. Work bottom-up to isolate.
`background: linear-gradient(...)` is a CSS shorthand that resets ALL background sub-properties (image, color, size, position, etc). It will override inline `background-image: url(...)` set in HTML templates. Fix: use specific properties like `background-color` or `background-size` separately. Verify with `getComputedStyle(el).backgroundImage` in browser console.

### Alembic migration drift — missing tables
When SQLAlchemy models define tables (e.g., `products`, `categories`) but Alembic migrations don't include them, `Base.metadata.create_all()` may have created the tables at runtime, but Alembic `alembic upgrade head` won't know about them. **Always verify migrations cover ALL model tables.** Run `alembic current` and `alembic history` to check. Symptom: Alembic thinks a table doesn't exist when the DB actually has it. Fix: add the missing `CREATE TABLE` statements to the latest migration, or run `alembic revision --autogenerate` to sync.

### FastAPI query params vs JSON body
When wiring frontend fetch calls to FastAPI endpoints, check the endpoint signature: `async def foo(email: str, ...)` expects query params — use `fetch('/foo?email=...')`. `async def foo(body: SomeSchema, ...)` expects JSON — use `fetch('/foo', {body: JSON.stringify(...)})`. Mismatch produces 422 errors. Check the endpoint signature first.

### FastAPI 422 with unknown query param (e.g., `kw`) — `Depends(None)` anti-pattern
**Most common root cause:** `db: AsyncSession = Depends(None)` in a dependency function. `Depends(None)` is an unresolvable dependency placeholder that corrupts FastAPI's OpenAPI schema, generating a phantom `kw` query parameter in the validation spec.
- **Fix:** Replace `Depends(None)` with `Depends(get_db)` and import `get_db` from `app.database`.
- **Never use `Depends(None)` as a placeholder** — it is not "no dependency"; it is an unresolved slot that breaks schema generation.

### FastAPI 422 with unknown query param (e.g., `kw`) — stale state
When protected endpoints return `422` expecting a query parameter (e.g., `kw`) that has zero source code references:

**Root cause candidates:**
1. **Stale OpenAPI spec / middleware** — a previous version registered a global dependency requiring the param; container wasn't fully rebuilt.
2. **Cached Pydantic schema** — stale `__pycache__/` or precompiled `.pyc` files inside the container from an older build.
3. **Stale container state** — `docker compose restart` preserves the old image; only `docker compose build` + `docker compose up` replaces it.

**Diagnostic steps:**
```bash
# 1. Check OpenAPI spec for the param
curl -s http://localhost:8010/openapi.json | python3 -m json.tool | grep -i 'kw'
# 2. Check for stale __pycache__ in container
docker exec <container> find /app -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null
# 3. Force full rebuild (not just restart)
docker compose build --no-cache api
docker compose up -d api
```

**Rule:** If `grep -rn 'kw' app/` returns zero results, the issue is container state, not source code. Always do a full `docker compose build --no-cache` after schema/dependency changes.

### FastAPI trailing slash — 307 redirect trap
FastAPI enforces trailing slashes on collection endpoints (`GET /api/v1/items/`) but NOT on action endpoints (`POST /api/v1/auth/login`). Calling `POST /login/` → 307 Temporary Redirect to `/login`. Curl without `-L` loses the redirect body → empty JSON or `Expecting value` parse error. **Always call action endpoints WITHOUT trailing slashes**, or use `curl -L` to follow redirects.

### Frontend "Network error" — non-JSON 500 response
When a FastAPI endpoint returns a 500 error, the response is an HTML error page, not JSON. The frontend `fetch()` call does `res.json()` → `SyntaxError: Unexpected token < in JSON` → caught by `catch` block → displays "Network error. Please try again."

**Root cause:** Backend service exception (e.g., `store_refresh_token()` Redis failure) → unhandled → 500 HTML → `res.json()` throws.

**Fix:** Wrap backend dependency calls in `try/catch` for graceful degradation. For Redis:
```python
try:
    await redis_client.store_refresh_token(user_id, refresh_token)
except Exception as e:
    logger.warning(f"Redis store_refresh_token failed: {e}")
```

**Verify:** After fix, test with `curl -s -X POST http://localhost:8000/api/v1/auth/login -H 'Content-Type: application/json' -d '{"email":"...","password":"..."}'` — should return JSON `{"access_token": "...", "refresh_token": "..."}`.

### FastAPI route ordering — static paths before parameterized
FastAPI matches routes top-to-bottom. `GET /{resource_id}` will catch requests for `GET /slots`, `GET /brands`, etc. if defined first — treating the literal path as a UUID parameter → 500 error. **Always define static routes (`/slots`, `/cancel`, `/brands`) BEFORE parameterized routes (`/{id}`).** Symptom: "invalid UUID" error for a valid endpoint. Fix: move the static route above the catch-all.

### Service method mismatch — get vs get_or_create
When a service exposes both `get_X` and `get_or_create_X`, and the router calls `get_X`, every request returns 404 until the record is manually seeded. **Always use `get_or_create` for user-scoped optional records** (profiles, settings, preferences) — auto-enroll on first access. Symptom: "Not found" on every endpoint hit. Fix: change `get_profile()` → `get_or_create_profile()` in the router.

### `uuid.UUID()` import-style mismatch — `NameError` vs silent `AttributeError`
When a module imports `from uuid import uuid4, UUID` (class import) instead of `import uuid` (module import), code that uses `uuid.UUID(...)` fails with `NameError: name 'uuid' is not defined`. This produces a 500 error on the affected endpoint.

**Two failure modes:**
1. **`NameError`** — `uuid.UUID(string)` when `uuid` module is not imported. Fix: change to `UUID(string)` using the class import.
2. **`AttributeError: 'UUID' object has no attribute 'replace'`** — Double conversion `uuid.UUID(uuid.UUID(x))` or `UUID(UUID(x))` — the inner call returns a UUID object, the outer call calls `.replace()` on it. Fix: use `UUID(x)` once, where `x` is a string.

**Diagnose:**
```bash
docker logs <container> --tail 40 2>&1 | grep -A 5 'Traceback'
```
Look for `NameError: name 'uuid' is not defined` or `AttributeError: 'UUID' object has no attribute 'replace'`.

**Fix pattern:**
```python
# Import style — pick ONE
from uuid import uuid4, UUID  # class import — use UUID(...)
# import uuid                  # module import — use uuid.UUID(...)

# Double conversion — WRONG
rid = uuid.UUID(resource_id)
resource = await db.get(Resource, uuid.UUID(rid))  # second UUID() on already-converted UUID

# Double conversion — CORRECT
resource = await db.get(Resource, UUID(resource_id))  # single conversion
```

**Scan for all instances:**
```bash
grep -rn 'uuid\.UUID\|UUID(UUID\|UUID(uuid' app/services/
```

**Rule:** Always verify the import style before using `uuid.UUID()`. If `UUID` is imported directly, use `UUID(...)`. Never nest `UUID()` calls — the argument should be a string, not an already-converted UUID object.

### SQLAlchemy DATE column vs string — TWO failure modes
When a FastAPI string parameter is used with a SQLAlchemy `Date` mapped column, PostgreSQL throws type errors in TWO distinct places:

1. **WHERE clause** — `operator does not exist: date = character varying`. Cast the string to a Python `date` object: `date_obj = datetime.strptime(date, "%Y-%m-%d").date()`, then use `Model.date == date_obj`.

2. **INSERT (model instantiation)** — `invalid input for query argument $N: '2026-06-02' ('str' object has no attribute 'toordinal')`. When creating the model instance, pass `date_obj` not the raw string: `Booking(..., date=date_obj, ...)`.

**Critical:** Fixing the WHERE clause without fixing the INSERT produces a second failure. Both paths need the cast. Fix together, not iteratively.

### Common Rationalizations

| Excuse | Reality |
|--------|---------|
| "Issue is simple, don't need process" | Simple issues have root causes too. Process is fast for simple bugs. |
| "Emergency, no time for process" | Systematic debugging is FASTER than guess-and-check thrashing. |
| "Just try this first, then investigate" | First fix sets the pattern. Do it right from the start. |
| "I'll write test after confirming fix works" | Untested fixes don't stick. Test first proves it. |
| "Multiple fixes at once saves time" | Can't isolate what worked. Causes new bugs. |
| "Reference too long, I'll adapt it differently" | Partial understanding guarantees bugs. Read it completely. |
| "I see the problem, let me fix it" | Seeing symptoms ≠ understanding root cause. |
| "One more fix attempt" (after 2+ failures) | 3+ failures = architectural problem. Question the pattern, don't fix again. |

## Web Frontend Pitfalls

### CSS Shorthand Override Traps

When debugging missing or wrong visual content (images, backgrounds, gradients):

- **`background: X` is a SHORTHAND** that resets ALL background sub-properties (`background-image`, `background-color`, `background-size`, `background-position`, etc.). Even if the HTML template sets `style="background-image: url(...)"`, a CSS rule with `background: linear-gradient(...)` will wipe it out.
- **Fix:** Use the specific property instead. Replace `background: linear-gradient(...)` with `background-color: ...` when you want inline `background-image` to take precedence.
- **Debug technique:** Use `getComputedStyle(el).backgroundImage` in the browser console — if it returns empty but the inline style is set, a CSS shorthand is overriding it.

### FastAPI Endpoint Mismatch

When wiring frontend fetch calls to FastAPI endpoints:

- Check whether the endpoint expects **query params** (`email: str`) vs **JSON body** (`body: PydanticModel`). Using `JSON.stringify()` when the endpoint expects query params (or vice versa) produces 422/400 errors that look like data validation failures but are actually transport mismatches.
- **Debug technique:** Read the endpoint signature first. `async def register(email: str, ...)` = query params. `async def register(body: SomeSchema, ...)` = JSON body.

## Quick Reference

| Phase | Key Activities | Success Criteria |
|-------|---------------|------------------|
| **1. Root Cause** | Read errors, reproduce, check changes, gather evidence, trace data flow | Understand WHAT and WHY |
| **2. Pattern** | Find working examples, compare, identify differences | Know what's different |
| **3. Hypothesis** | Form theory, test minimally, one variable at a time | Confirmed or new hypothesis |
| **4. Implementation** | Create regression test, fix root cause, verify | Bug resolved, all tests pass |

## Hermes Agent Integration

### Investigation Tools

Use these Hermes tools during Phase 1:

- **`search_files`** — Find error strings, trace function calls, locate patterns
- **`read_file`** — Read source code with line numbers for precise analysis
- **`terminal`** — Run tests, check git history, reproduce bugs
- **`web_search`/`web_extract`** — Research error messages, library docs

### With delegate_task

For complex multi-component debugging, dispatch investigation subagents:

```python
delegate_task(
    goal="Investigate why [specific test/behavior] fails",
    context="""
    Follow systematic-debugging skill:
    1. Read the error message carefully
    2. Reproduce the issue
    3. Trace the data flow to find root cause
    4. Report findings — do NOT fix yet

    Error: [paste full error]
    File: [path to failing code]
    Test command: [exact command]
    """,
    toolsets=['terminal', 'file']
)
```

### With test-driven-development

When fixing bugs:
1. Write a test that reproduces the bug (RED)
2. Debug systematically to find root cause
3. Fix the root cause (GREEN)
4. The test proves the fix and prevents regression

## Real-World Impact

From debugging sessions:
- Systematic approach: 15-30 minutes to fix
- Random fixes approach: 2-3 hours of thrashing
- First-time fix rate: 95% vs 40%
- New bugs introduced: Near zero vs common

**No shortcuts. No guessing. Systematic always wins.**

## Python/Docker/FastAPI Debugging Patterns

When debugging Python/Docker/FastAPI projects specifically:

### Docker-specific debug patterns

- **Container is not picking up file changes**: Docker volumes may cache or require rebuild. Force `docker compose build --no-cache` or stop/restart the container.
- **ModuleNotFoundError inside container**: Check the mount path — the code may be mounted under `/app/` but imports expect a different root. Use `docker exec container ls /app/` to verify.
- **Health check reports unhealthy but service works**: Qdrant container's healthcheck uses `wget` which is NOT in the image. Verify with `curl -s http://container:port/healthz` instead.
- **DNS resolution fails between containers**: Even after `docker network connect`, container hostname resolution may fail. Use `host.docker.internal` via `extra_hosts` to bypass Docker DNS.
- **Post-merge conflicts**: After Docker merge conflicts, verify `docker-compose.yml` is valid with `docker compose config`. Fix YAML syntax before attempting deployment.

### FastAPI-specific debug patterns

- **Router not registered**: If endpoint returns 404, check BOTH `routers/__init__.py` (import) AND `main.py` (`app.include_router()`). Both are required.
- **Trailing slash 307**: `@router.get("/")` on a prefixed router creates `/prefix/` (with trailing slash). Requests to `/prefix` get 307. Fix: use `@router.get("")` instead.
- **Static routes before dynamic**: FastAPI requires `@router.get("/summary")` before `@router.get("/{id}")`. Wrong order causes 404 on static paths.
- **500 on UUID param with non-UUID value**: Endpoints accepting UUID path params crash on non-UUID values. Add try/except before `db.get()`.

### Agent-skill adoption debugging

When agents fail to adopt skills from a shared directory:
1. Verify the skill exists at the expected path
2. Check if the skill was actually loaded (skill loading is per-session)
3. The skill reference must be in the prompt or skill list to trigger adoption
4. See `references/agent-skills-adoption.md` for specific adoption patterns

## Support Files

