---
name: code-simplification
description: "Simplify code by reducing complexity while preserving exact behavior. Post-implementation cleanup pass."
version: 1.0.0
author: Hermes Agent (adapted from addyosmani/agent-skills)
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [refactoring, simplification, code-quality, readability]
    related_skills: [test-driven-development, requesting-code-review, fastapi-jinja2-feature-build]
---

# Code Simplification

## Overview

Simplify code by reducing complexity while preserving exact behavior. The goal is not fewer lines — it's code that is easier to read, understand, modify, and debug. Every simplification must pass a simple test: "Would a new team member understand this faster than the original?"

**Core principle:** Don't change what the code does — only how it expresses it.

## When to Use

- After a feature is working and tests pass, but the implementation feels heavier than it needs to be
- During code review when readability or complexity issues are flagged
- When you encounter deeply nested logic, long functions, or unclear names
- When refactoring code written under time pressure
- When consolidating related logic scattered across files
- After merging changes that introduced duplication or inconsistency

**When NOT to use:**
- Code is already clean and readable — don't simplify for the sake of it
- You don't understand what the code does yet — comprehend before you simplify
- The code is performance-critical and the "simpler" version would be measurably slower
- You're about to rewrite the module entirely — simplifying throwaway code wastes effort

## The Five Principles

### 1. Preserve Behavior Exactly

All inputs, outputs, side effects, error behavior, and edge cases must remain identical. If you're not sure a simplification preserves behavior, don't make it.

### 2. Reduce Nesting

Every nested block (if/else, for, while) inside another nested block adds cognitive load. Flatten by:
- Early returns (guard clauses)
- Extracting nested logic into named functions
- Using comprehensions where appropriate
- Inverting conditions to handle the common case first

```python
# Before: Nested
def process_order(order):
    if order.user_id:
        if order.items:
            if order.items.count() > 0:
                if order.status == 'active':
                    return calculate_total(order)
            else:
                raise EmptyOrderError()
        else:
            raise MissingItemsError()
    else:
        raise InvalidUserError()

# After: Guard clauses
def process_order(order):
    if not order.user_id:
        raise InvalidUserError()
    if not order.items:
        raise MissingItemsError()
    if order.items.count() == 0:
        raise EmptyOrderError()
    if order.status != 'active':
        return 0
    return calculate_total(order)
```

### 3. Extract Helpers

When a function does multiple things, extract each thing into a named helper. The function name becomes documentation.

```python
# Before: Long function
def process_booking(booking):
    # 80 lines of mixed validation, calculation, and persistence
    ...

# After: Composed from named helpers
def process_booking(booking):
    validate_booking(booking)
    charge = calculate_booking_charge(booking)
    persist_booking(booking, charge)
    send_confirmation(booking, charge)
    return booking
```

### 4. Rename for Clarity

A name should reveal intent, not implementation. Good names:
- Use domain language (match the spec)
- Are specific, not generic (`calculate_rental_charge` not `calc`)
- Avoid unnecessary context (`user_id` not `id` when it's already in `user_service.py`)
- Spell out abbreviations unless they're universally understood (`count` not `cnt`)

### 5. Remove Dead Code

Code that isn't called is a liability. Remove:
- Unused functions, classes, imports
- Commented-out code (git has the history)
- Debug print statements
- TODO comments older than 30 days (if you can't resolve it, delete the comment and move the task to backlog)

## The Simplification Process

```
1. UNDERSTAND   — Read the code, understand what it does
2. TEST         — Confirm tests pass before any changes
3. SIMPLIFY     — Apply one principle at a time, small steps
4. VERIFY       — Run tests after each change
5. REPEAT       — Next simplification
```

**Rule:** Never apply multiple simplifications in one pass. Make one change, run tests, repeat. This keeps you from introducing subtle behavior changes.

## Common Patterns to Apply

### Replace Conditional with Guard Clause

```python
# Before
def validate_user(user):
    result = None
    if user.is_active:
        if user.email:
            if user.is_verified:
                result = True
            else:
                result = False
        else:
            result = False
    else:
        result = False
    return result

# After
def validate_user(user):
    if not user.is_active:
        return False
    if not user.email:
        return False
    return user.is_verified
```

### Replace Parallel Collections with a Dict/Class

```python
# Before: Parallel lists
names = ['Alice', 'Bob', 'Charlie']
ages = [30, 25, 35]

# After: Structured data
users = [
    {'name': 'Alice', 'age': 30},
    {'name': 'Bob', 'age': 25},
    {'name': 'Charlie', 'age': 35},
]
```

### Extract Constant for Magic Value

```python
# Before
if booking.duration_days > 30:

# After
MAX_BOOKING_DAYS = 30
if booking.duration_days > MAX_BOOKING_DAYS:
```

### Replace Boolean Flag with Named Return

```python
# Before
found = False
for item in items:
    if matches(item):
        found = True
        break
return found

# After
return any(matches(item) for item in items)
```

## Verification

Before declaring simplification complete:

1. All tests pass
2. Run the feature end-to-end
3. Ask: "Would someone reading this for the first time understand it faster?"

**Red flags that you've gone too far:**
- You can't explain why the new version is better
- The new version has more lines than the original
- You had to change function signatures to "make it clean"

## Integration with Other Skills

**test-driven-development:** Run tests before and after every simplification step. Never simplify without test coverage.

**requesting-code-review:** Code review flags complexity issues — use this skill to fix them.

**fastapi-jinja2-feature-build:** After Phase 4 (wiring up), do a simplification pass on the new code.

