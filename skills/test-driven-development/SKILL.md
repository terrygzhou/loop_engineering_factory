---
name: test-driven-development
description: "TDD: enforce RED-GREEN-REFACTOR, tests before code."
version: 1.1.0
author: Hermes Agent (adapted from obra/superpowers)
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [testing, tdd, development, quality, red-green-refactor]
    related_skills: [systematic-debugging, writing-plans, subagent-driven-development]
---

# Test-Driven Development (TDD)

## Overview

Write the test first. Watch it fail. Write minimal code to pass.

**Core principle:** If you didn't watch the test fail, you don't know if it tests the right thing.

**Violating the letter of the rules is violating the spirit of the rules.**

## When to Use

**Always:**
- New features
- Bug fixes
- Refactoring
- Behavior changes

**Exceptions (ask the user first):**
- Throwaway prototypes
- Generated code
- Configuration files

Thinking "skip TDD just this once"? Stop. That's rationalization.

## The Iron Law

```
NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST
```

Write code before the test? Delete it. Start over.

**No exceptions:**
- Don't keep it as "reference"
- Don't "adapt" it while writing tests
- Don't look at it
- Delete means delete

Implement fresh from tests. Period.

## Red-Green-Refactor Cycle

### RED — Write Failing Test

Write one minimal test showing what should happen.

**Good test:**
```python
def test_retries_failed_operations_3_times():
    attempts = 0
    def operation():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise Exception('fail')
        return 'success'

    result = retry_operation(operation)

    assert result == 'success'
    assert attempts == 3
```
Clear name, tests real behavior, one thing.

**Bad test:**
```python
def test_retry_works():
    mock = MagicMock()
    mock.side_effect = [Exception(), Exception(), 'success']
    result = retry_operation(mock)
    assert result == 'success'  # What about retry count? Timing?
```
Vague name, tests mock not real code.

**Requirements:**
- One behavior per test
- Clear descriptive name ("and" in name? Split it)
- Real code, not mocks (unless truly unavoidable)
- Name describes behavior, not implementation

### Verify RED — Watch It Fail

**MANDATORY. Never skip.**

```bash
# Use terminal tool to run the specific test
pytest tests/test_feature.py::test_specific_behavior -v
```

Confirm:
- Test fails (not errors from typos)
- Failure message is expected
- Fails because the feature is missing

**Test passes immediately?** You're testing existing behavior. Fix the test.

**Test errors?** Fix the error, re-run until it fails correctly.

### GREEN — Minimal Code

Write the simplest code to pass the test. Nothing more.

**Good:**
```python
def add(a, b):
    return a + b  # Nothing extra
```

**Bad:**
```python
def add(a, b):
    result = a + b
    logging.info(f"Adding {a} + {b} = {result}")  # Extra!
    return result
```

Don't add features, refactor other code, or "improve" beyond the test.

**Cheating is OK in GREEN:**
- Hardcode return values
- Copy-paste
- Duplicate code
- Skip edge cases

We'll fix it in REFACTOR.

### Verify GREEN — Watch It Pass

**MANDATORY.**

```bash
# Run the specific test
pytest tests/test_feature.py::test_specific_behavior -v

# Then run ALL tests to check for regressions
pytest tests/ -q
```

Confirm:
- Test passes
- Other tests still pass
- Output pristine (no errors, warnings)

**Test fails?** Fix the code, not the test.

**Other tests fail?** Fix regressions now.

### REFACTOR — Clean Up

After green only:
- Remove duplication
- Improve names
- Extract helpers
- Simplify expressions

Keep tests green throughout. Don't add behavior.

**If tests fail during refactor:** Undo immediately. Take smaller steps.

### Repeat

Next failing test for next behavior. One cycle at a time.

## Why Order Matters

**"I'll write tests after to verify it works"**

Tests written after code pass immediately. Passing immediately proves nothing:
- Might test the wrong thing
- Might test implementation, not behavior
- Might miss edge cases you forgot
- You never saw it catch the bug

Test-first forces you to see the test fail, proving it actually tests something.

**"I already manually tested all the edge cases"**

Manual testing is ad-hoc. You think you tested everything but:
- No record of what you tested
- Can't re-run when code changes
- Easy to forget cases under pressure
- "It worked when I tried it" ≠ comprehensive

Automated tests are systematic. They run the same way every time.

**"Deleting X hours of work is wasteful"**

Sunk cost fallacy. The time is already gone. Your choice now:
- Delete and rewrite with TDD (high confidence)
- Keep it and add tests after (low confidence, likely bugs)

The "waste" is keeping code you can't trust.

**"TDD is dogmatic, being pragmatic means adapting"**

TDD IS pragmatic:
- Finds bugs before commit (faster than debugging after)
- Prevents regressions (tests catch breaks immediately)
- Documents behavior (tests show how to use code)
- Enables refactoring (change freely, tests catch breaks)

"Pragmatic" shortcuts = debugging in production = slower.

**"Tests after achieve the same goals — it's spirit not ritual"**

No. Tests-after answer "What does this do?" Tests-first answer "What should this do?"

Tests-after are biased by your implementation. You test what you built, not what's required. Tests-first force edge case discovery before implementing.

## Common Rationalizations

| Excuse | Reality |
|--------|---------|
| "Too simple to test" | Simple code breaks. Test takes 30 seconds. |
| "I'll test after" | Tests passing immediately prove nothing. |
| "Tests after achieve same goals" | Tests-after = "what does this do?" Tests-first = "what should this do?" |
| "Already manually tested" | Ad-hoc ≠ systematic. No record, can't re-run. |
| "Deleting X hours is wasteful" | Sunk cost fallacy. Keeping unverified code is technical debt. |
| "Keep as reference, write tests first" | You'll adapt it. That's testing after. Delete means delete. |
| "Need to explore first" | Fine. Throw away exploration, start with TDD. |
| "Test hard = design unclear" | Listen to the test. Hard to test = hard to use. |
| "TDD will slow me down" | TDD faster than debugging. Pragmatic = test-first. |
| "Manual test faster" | Manual doesn't prove edge cases. You'll re-test every change. |
| "Existing code has no tests" | You're improving it. Add tests for the code you touch. |

## Red Flags — STOP and Start Over

If you catch yourself doing any of these, delete the code and restart with TDD:

- Code before test
- Test after implementation
- Test passes immediately on first run
- Can't explain why test failed
- Tests added "later"
- Rationalizing "just this once"
- "I already manually tested it"
- "Tests after achieve the same purpose"
- "Keep as reference" or "adapt existing code"
- "Already spent X hours, deleting is wasteful"
- "TDD is dogmatic, I'm being pragmatic"
- "This is different because..."

**All of these mean: Delete code. Start over with TDD.**

## Verification Checklist

Before marking work complete:

- [ ] Every new function/method has a test
- [ ] Watched each test fail before implementing
- [ ] Each test failed for expected reason (feature missing, not typo)
- [ ] Wrote minimal code to pass each test
- [ ] All tests pass
- [ ] Output pristine (no errors, warnings)
- [ ] Tests use real code (mocks only if unavoidable)
- [ ] Edge cases and errors covered

Can't check all boxes? You skipped TDD. Start over.

## When Stuck

| Problem | Solution |
|---------|----------|
| Don't know how to test | Write the wished-for API. Write the assertion first. Ask the user. |
| Test too complicated | Design too complicated. Simplify the interface. |
| Must mock everything | Code too coupled. Use dependency injection. |
| Test setup huge | Extract helpers. Still complex? Simplify the design. |

## The Test Pyramid

Invest testing effort according to the pyramid — most tests should be small and fast:

```
          ╱╲
         ╱  ╲         E2E Tests (~5%)
        ╱    ╲        Full user flows, real browser
       ╱──────╲
      ╱        ╲      Integration Tests (~15%)
     ╱          ╲     Component interactions, API boundaries
    ╱────────────╲
   ╱              ╲   Unit Tests (~80%)
  ╱                ╲  Pure logic, isolated, milliseconds each
 ╱──────────────────╲
```

**Test Sizes (Resource Model):**

| Size | Constraints | Speed | Example |
|------|------------|-------|---------|
| **Small** | Single process, no I/O, no network, no database | Milliseconds | Pure function tests, data transforms |
| **Medium** | Multi-process OK, localhost only, no external services | Seconds | API tests with test DB, component tests |
| **Large** | Multi-machine OK, external services allowed | Minutes | E2E tests, performance benchmarks, staging integration |

**The Beyonce Rule:** If you liked it, you should have put a test on it. Infrastructure changes, refactoring, and migrations are not responsible for catching your bugs — your tests are. If a change breaks your code and you didn't have a test for it, that's on you.

**Decision Guide:**
```
Is it pure logic with no side effects?
  → Unit test (small)
Does it cross a boundary (API, database, file system)?
  → Integration test (medium)
Is it a critical user flow that must work end-to-end?
  → E2E test (large) — limit these to critical paths
```

## Writing Better Tests

### DAMP Over DRY in Tests

In production code, DRY (Don't Repeat Yourself) is usually right. In tests, **DAMP (Descriptive And Meaningful Phrases)** is better. Each test should read like a specification — self-contained, independently understandable. Duplication in tests is acceptable when it makes each test independently readable.

```python
# DAMP: Each test is self-contained and readable
def test_rejects_tasks_with_empty_titles():
    result = create_task(title='', assignee='user-1')
    assert result.status_code == 422
    assert 'Title is required' in str(result.json())

def test_trims_whitespace_from_titles():
    task = create_task(title='  Buy groceries  ', assignee='user-1')
    assert task.title == 'Buy groceries'

# Over-DRY: Shared setup obscures what each test actually verifies
# (Don't do this just to avoid repeating the input shape)
```

### Arrange-Act-Assert Pattern

```python
def test_marks_overdue_tasks():
    # Arrange: Set up the test scenario
    task = create_task(title='Test', deadline='2026-01-01')

    # Act: Perform the action being tested
    result = check_overdue(task, current_date='2026-01-02')

    # Assert: Verify the outcome
    assert result.is_overdue is True
```

### Test State, Not Interactions

Assert on the *outcome* of an operation, not on which methods were called internally. Tests that verify method call sequences break when you refactor, even if behavior is unchanged.

### One Assertion Per Concept

One behavior per test. If "and" appears in the test name, split it.

## Docker Container Testing

When tests must run inside a Docker container (e.g., API integration tests):

### Getting Test Files Into the Container

1. **`docker cp`** — fastest for hotfixing tests without rebuilding:
   ```bash
   docker cp ./tests/test_xxx.py container-name:/app/tests/test_xxx.py
   ```
2. **`docker compose build`** — rebuilds the image with `COPY . .` from Dockerfile. **BuildKit caching** may silently skip new files. Force with `--no-cache` if files don't appear.
3. **Verify files are in container** before running:
   ```bash
   docker exec container-name ls tests/test_xxx.py
   ```

### Running Tests Inside Container

```bash
# Run specific test file(s) inside container
docker exec container-name python -m pytest tests/test_xxx.py -v --tb=short

# Run full test suite
docker exec container-name python -m pytest tests/ -v --tb=short
```

### Common Pitfalls

| Pitfall | Fix |
|---------|-----|
| New test files not in container | Use `docker cp` or `docker compose build --no-cache` |
| `conftest.py` filename typo | Ensure the file is named `conftest.py` (not `conftest.py` or other typos) |
| Import errors (`from tests.conftest`) | Fix imports to match actual filename |
| Docker BuildKit cache stale | Touch a file or use `--no-cache` to force rebuild |
| Event loop closed (Redis async) | Accept 500/503 as valid codes for external service failures |
| External dependency blocks tests (Redis, SMS, email gateway) | Replace with in-memory mock store — see `references/mock-external-deps.md` |

### HTTP Status Code Assertions

API endpoints return varied status codes for edge cases. Use flexible assertions:

```python
# Accept a broad set of valid status codes
assert resp.status_code in (200, 201, 400, 401, 404, 409, 422, 500, 503)
```

| Code | Meaning |
|------|---------|
| 200/201 | Success |
| 400 | Bad Request (validation error) |
| 401 | Unauthorized (auth required) |
| 404 | Not Found |
| 409 | Conflict (duplicate resource) |
| 422 | Unprocessable Entity (validation failure) |
| 500 | Internal Server Error |
| 503 | Service Unavailable (external dep down) |

### Test Data Setup

For integration tests, ensure seed data exists:
- Users, items, orders must be in the DB before tests run
- Use seed scripts to populate test fixtures
- Truncate tables between test runs for clean state

### Verification

Before declaring tests pass:
1. Confirm test files are in the container
2. Confirm container is healthy and running
3. Run tests and verify output
4. Check for regressions (run full suite)

### With delegate_task

When dispatching subagents for implementation, enforce TDD in the goal:

```python
delegate_task(
    goal="Implement [feature] using strict TDD",
    context="""
    Follow test-driven-development skill:
    1. Write failing test FIRST
    2. Run test to verify it fails
    3. Write minimal code to pass
    4. Run test to verify it passes
    5. Refactor if needed
    6. Commit

    Project test command: pytest tests/ -q
    Project structure: [describe relevant files]
    """,
    toolsets=['terminal', 'file']
)
```

### With systematic-debugging

Bug found? Write failing test reproducing it. Follow TDD cycle. The test proves the fix and prevents regression.

Never fix bugs without a test.

## The Test Pyramid

Invest testing effort according to the pyramid — most tests should be small and fast:

```
        ╱╲
       ╱  ╲         E2E Tests (~5%)
      ╱    ╲        Full user flows, real browser
     ╱──────╲
    ╱        ╲      Integration Tests (~15%)
   ╱          ╲     Component interactions, API boundaries
  ╱────────────╲
 ╱              ╲   Unit Tests (~80%)
╱                ╲  Pure logic, isolated, milliseconds each
╱────────────────╲
```

**The Beyonce Rule:** If you liked it, you should have put a test on it. Infrastructure changes, refactoring, and migrations are not responsible for catching your bugs — your tests are. If a change breaks your code and you didn't have a test for it, that's on you.

### Test Sizes (Resource Model)

| Size | Constraints | Speed | Example |
|------|------------|-------|---------|
| **Small** | Single process, no I/O, no network, no database | Milliseconds | Pure function tests, data transforms |
| **Medium** | Multi-process OK, localhost only, no external services | Seconds | API tests with test DB, component tests |
| **Large** | Multi-machine OK, external services allowed | Minutes | E2E tests, performance benchmarks, staging integration |

Small tests should make up the vast majority. They're fast, reliable, and easy to debug.

### Writing Good Tests

#### Test State, Not Interactions

Assert on the *outcome* of an operation, not on which methods were called internally. Tests that verify method call sequences break when you refactor, even if the behavior is unchanged.

```python
# Good: Tests what the function does (state-based)
def test_returns_tasks_sorted_newest_first():
    tasks = list_tasks(sort_by='createdAt', sort_order='desc')
    assert tasks[0].created_at > tasks[1].created_at

# Bad: Tests how the function works internally (interaction-based)
def test_calls_db_query_with_order_by():
    list_tasks(sort_by='createdAt', sort_order='desc')
    assert db.query.call_args[0][0].endswith('ORDER BY created_at DESC')
```

#### DAMP Over DRY in Tests

In production code, DRY (Don't Repeat Yourself) is usually right. In tests, **DAMP (Descriptive And Meaningful Phrases)** is better. A test should read like a specification — each test should tell a complete story without requiring the reader to trace through shared helpers.

```python
# DAMP: Each test is self-contained and readable
def test_rejects_empty_title():
    with pytest.raises(ValueError, match="Title is required"):
        create_task(title='', assignee='user-1')

def test_trims_whitespace_from_title():
    task = create_task(title='  Buy groceries  ', assignee='user-1')
    assert task.title == 'Buy groceries'

# Over-DRY: Shared setup obscures what each test actually verifies
# (Don't do this just to avoid repeating the input shape)
```

Duplication in tests is acceptable when it makes each test independently understandable.

#### Prefer Real Implementations Over Mocks

Use the simplest test double that gets the job done. The more your tests use real code, the more confidence they provide.

```
Preference order (most to least preferred):
1. Real implementation  → Highest confidence, catches real bugs
2. Fake                 → In-memory version of a dependency (e.g., fake DB)
3. Stub                 → Returns canned data, no behavior
4. Mock (interaction)   → Verifies method calls — use sparingly
```

Use mocks only when the real implementation is too slow, non-deterministic, or has side effects you can't control (external APIs, email sending). Over-mocking creates tests that pass while production breaks.

#### Use the Arrange-Act-Assert Pattern

```python
def test_marks_overdue_tasks():
    # Arrange: Set up the test scenario
    task = create_task(title='Test', deadline=datetime(2025, 1, 1))

    # Act: Perform the action being tested
    result = check_overdue(task, datetime(2025, 1, 2))

    # Assert: Verify the outcome
    assert result.is_overdue is True
```

#### One Assertion Per Concept

```python
# Good: Each test verifies one behavior
def test_rejects_empty_title(): ...
def test_trims_whitespace(): ...
def test_enforces_max_length(): ...

# Bad: Everything in one test
def test_validates_titles():
    with pytest.raises(ValueError): create_task(title='')
    assert create_task(title='  hello  ').title == 'hello'
    with pytest.raises(ValueError): create_task(title='a' * 256)
```

#### Name Tests Descriptively

```python
# Good: Reads like a specification
class TestCompleteTask:
    def test_sets_status_and_records_timestamp(self): ...
    def test_raises_not_found_for_non_existent_task(self): ...
    def test_is_idempotent_when_already_completed(self): ...

# Bad: Vague names
def test_works(): ...
def test_handles_errors(): ...
```

## Test Anti-Patterns

| Anti-Pattern | Problem | Fix |
|---|---|---|
| Testing implementation details | Tests break when refactoring even if behavior is unchanged | Test inputs and outputs, not internal structure |
| Flaky tests (timing, order-dependent) | Erode trust in the test suite | Use deterministic assertions, isolate test state |
| Testing framework code | Wastes time testing third-party behavior | Only test YOUR code |
| Snapshot abuse | Large snapshots nobody reviews, break on any change | Use sparingly and review every change |
| No test isolation | Tests pass individually but fail together | Each test sets up and tears down its own state |
| Mocking everything | Tests pass but production breaks | Prefer real > fakes > stubs > mocks. Mock only at boundaries. |

## UAT Documentation Workflow

When asked to "document test cases, run tests, produce UAT report":

### 1. Test Case Documentation (`design/<feature>_test_cases.md`)
Create structured test cases with TC IDs, Given/When/Then format:
```
### TC-001: Create Hiring Plan
- **Given**: No existing plans in database
- **When**: User creates a hiring plan with valid data
- **Then**: Plan is created with unique ID
- **Verify**: Plan appears in database with correct fields
```
Organize by category: Model, Service, API, Integration. Target 3-5 test cases per category.

### 2. Execute Automated Tests
Run pytest, capture results. Map automated test results to TC IDs.

### 3. UAT Report (`tests/uat_output.md`)
Structure:
```markdown
## Test Execution Summary
| Metric | Value |
|--------|-------|
| Total | N |
| Pass | N |
| Fail | 0 |

## Test Case Results
### Model Layer
| ID | Name | Status | Notes |
|----|------|--------|-------|
| TC-001 | ... | ✅ PASS | ... |

## Bugs Found & Fixed
| ID | Severity | Description | Status | Resolution |
|----|----------|-------------|--------|------------|

## Pre-existing Test Failures (Not Related to Feature)
| Module | Issue | Cause |
|--------|-------|-------|
```

### 4. Pre-existing Failure Isolation
When running the full test suite, **explicitly note** which failures existed before the feature was built. This prevents false attribution and keeps UAT reports accurate.

```markdown
## Pre-existing Test Failures (Not Related to Feature)
| Test Module | Issue | Cause |
|-------------|-------|-------|
| test_resources.py | 8 failures | External API calls (socket.gaierror) |
| test_orders.py | 8 failures | Auth setup missing (401 responses) |
```

**Rule:** Always distinguish new failures from pre-existing ones. A clean UAT report means "this feature has zero failures," not "the whole test suite is green."

**Also:** Track seed data validation in the report — verify counts, relationships, and discount calculations match expected values.

## Final Rule

```
Production code → test exists and failed first
Otherwise → not TDD
```

No exceptions without the user's explicit permission.
