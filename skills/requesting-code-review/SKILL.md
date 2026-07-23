---
name: requesting-code-review
description: Pre-commit code review — quality gates, security scan, auto-fix suggestions, conventional commit formatting
category: software-development
---

# Requesting Code Review

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

## Usage

Called as an aggregate pass after security-and-hardening in BUILD subgraph. Provides a quality gate before UAT.

## Related Skills

- `security-and-hardening` — pre-review security scan
- `code-simplification` — post-review simplification pass
- `git-workflow` — format review findings as conventional commits