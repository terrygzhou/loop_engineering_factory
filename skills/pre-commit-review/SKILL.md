---
name: pre-commit-review
description: Pre-commit code review — multi-axis quality review (style, structure, maintainability, conventions), security scan, auto-fix suggestions, conventional commit formatting
category: software-development
---

# Pre-Commit Review

## Purpose

Aggregate code quality pass after IMPLEMENT completion in BUILD subgraph. Reviews generated code for style, structure, maintainability, and adherence to project conventions.

## Review Checklist

### Structure & Organization
- Module-level separation of concerns
- Proper file naming conventions (snake_case for Python, camelCase for JS)
- Import organization (stdlib → third-party → local)
- Avoid circular dependencies

### Readability
- Function names express intent (verb + noun)
- Comments explain why, not what
- Line length under 120 chars
- Consistent indentation and spacing

### Error Handling
- Specific exception types over bare `except:`
- Fail-fast principle — don't swallow errors silently
- Retry logic with exponential backoff for transient failures
- Meaningful error messages for debugging

### Testing Readiness
- Functions are unit-testable (no hidden side effects)
- Dependencies injected, not created internally
- Clear input/output contracts
- Mockable external calls

## Review Output Format

```markdown
# Code Review — {project_name}

## Summary
- Files reviewed: {count}
- Lines of code: {loc}
- Issues found: {n}

## Findings

### Critical (n)
1. {issue description} — {file}:{line}
   Fix: {suggested fix}

### Warning (n)
1. {issue description} — {file}:{line}

### Info (n)
1. {style note} — {file}:{line}

## Verdict: {PASS|REVISION NEEDED}
```

## Auto-Fix Patterns

| Pattern | Before | After |
|---------|--------|-------|
| Wildcard import | `from module import *` | `from module import specific` |
| Bare except | `except:` | `except (ExpectedError, UnexpectedError):` |
| Hardcoded path | `Path("/app/data")` | `Path(config.paths.data_dir)` |
| String concat | `f"select * from {table}"` | `SELECT ... WHERE id = :id` |

## Multi-Axis Review Dimensions

Every review evaluates code across these dimensions (merged from the multi-axis code-review discipline). **The approval standard:** approve a change when it definitely improves overall code health, even if it isn't perfect — the goal is continuous improvement. Don't block a change because it isn't exactly how you would have written it.

### Style

- Consistent naming, indentation, and spacing across the change
- No "clever" tricks where a straightforward approach works; could this be done in fewer lines?
- No dead-code artifacts: no-op variables, backwards-compat shims, or "removed" comments

### Structure

- Is a new conditional bolted onto an unrelated flow? That's a design smell — push the logic into its own helper, state, or policy instead of tangling an existing path
- Do repeated conditionals on the same shape appear? They signal a missing model or dispatcher; a "temporary" branch is usually permanent debt
- Keep file size in check: a small diff that pushes a file past ~1000 total lines — extract helpers or modules first

### Maintainability

- Can another engineer (or agent) understand this code without the author explaining it?
- Abstractions earn their complexity — don't generalize until the third use case
- Does this refactor reduce complexity or just relocate it? Count the concepts a reader must hold; prefer the restructuring that makes whole branches or layers disappear over one that re-centralizes the same logic

### Conventions

- Does the change follow existing patterns, or does it introduce a new one? If new, is it justified?
- Does it maintain clean module boundaries, with dependencies flowing in the right direction?
- Does it keep feature-specific logic in its owning layer instead of leaking it into a shared module?
- Are type boundaries explicit — no gratuitous `any`/`unknown`/optional/casts or silent fallbacks papering over an unclear invariant?

### Correctness

- Does the code do what it claims — match the spec or task requirements?
- Are edge cases handled (null, empty, boundary values)?
- Are error paths handled, not just the happy path?
- Does it pass all tests, and are the tests actually testing the right things?

### Error-Handling Patterns

- Specific exception types over bare `except:`; fail-fast, don't swallow errors silently
- Retry logic with exponential backoff for transient failures
- Meaningful error messages for debugging

### Testing Readiness

- Functions are unit-testable (no hidden side effects); dependencies injected, not created internally
- Clear input/output contracts; mockable external calls
- Bug fixes carry a regression test

## Structural Remedies

When you flag a structural problem, propose the move — not just the problem. A review that only says "this is complex" leaves the author guessing. Reach for a named restructuring:

- Replace a chain of conditionals with a typed model or an explicit dispatcher
- Collapse duplicate branches into a single clearer flow
- Separate orchestration from business logic so each reads on its own
- Move feature-specific logic out of a shared module into the package that owns the concept
- Reuse the canonical helper instead of a bespoke near-duplicate
- Make a type boundary explicit so downstream branching disappears
- Delete a pass-through wrapper that adds indirection without clarifying the API
- Extract a helper, or split a large file into focused modules

Prefer the remedy that removes moving pieces over one that spreads the same complexity around.

## Usage

Called as an aggregate pass after security-and-hardening in BUILD subgraph. Provides a quality gate before UAT.

## Related Skills

- `security-and-hardening` — pre-review security scan
- `code-simplification` — post-review simplification pass
- `git-workflow` — format review findings as conventional commits
