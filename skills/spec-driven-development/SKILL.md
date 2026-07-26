---
name: spec-driven-development
description: Creates specs before coding. Use when starting a new project, feature, or significant change and no specification exists yet.
---

# Spec-Driven Development

## Overview

Write a structured specification before writing any code. The spec is the shared source of truth — it defines what we're building, why, and how we'll know it's done.

## When to Use

- Starting a new project or feature
- Requirements are ambiguous or incomplete
- The change touches multiple files or modules
- You're about to make an architectural decision

**When NOT to use:** Single-line fixes, typo corrections, or changes where requirements are unambiguous and self-contained.

## The Six Core Areas

Write a spec document covering:

1. **Objective** — What are we building and why? Who is the user? What does success look like?
2. **Commands** — Full executable commands with flags (build, test, lint, dev).
3. **Project Structure** — Directory layout with descriptions.
4. **Code Style** — One real code snippet showing style. Naming conventions, formatting rules.
5. **Testing Strategy** — Framework, test locations, coverage requirements, test levels.
6. **Boundaries** — Three-tier system:
   - **Always do:** Run tests before commits, follow naming conventions, validate inputs
   - **Ask first:** Database schema changes, adding dependencies, changing CI config
   - **Never do:** Commit secrets, edit vendor directories, remove failing tests without approval

## Spec Template

```markdown
# Spec: [Project/Feature Name]

## Objective
[What we're building and why. User stories or acceptance criteria.]

## Tech Stack
[Framework, language, key dependencies with versions]

## Commands
[Build, test, lint, dev — full commands]

## Project Structure
[Directory layout with descriptions]

## Code Style
[Example snippet + key conventions]

## Testing Strategy
[Framework, test locations, coverage requirements, test levels]

## Boundaries
- Always: [...]
- Ask first: [...]
- Never: [...]

## Success Criteria
[How we'll know this is done — specific, testable conditions]

## Open Questions
[Anything unresolved that needs human input]
```

## Surface Assumptions Immediately

Before writing spec content, list assumptions:

```
ASSUMPTIONS I'M MAKING:
1. This is a web application (not native mobile)
2. Authentication uses session-based cookies (not JWT)
3. The database is PostgreSQL (based on existing schema)
→ Correct me now or I'll proceed with these.
```

Don't silently fill in ambiguous requirements. The spec's purpose is to surface misunderstandings *before* code gets written.

## Reframe Instructions as Success Criteria

Translate vague requirements into concrete conditions:

```
REQUIREMENT: "Make the dashboard faster"

REFRAMED SUCCESS CRITERIA:
- Dashboard LCP < 2.5s on 4G connection
- Initial data load completes in < 500ms
- No layout shift during load (CLS < 0.1)
→ Are these the right targets?
```

## Verification

Before proceeding, confirm:

- [ ] The spec covers all six core areas
- [ ] Success criteria are specific and testable
- [ ] Boundaries (Always/Ask First/Never) are defined
- [ ] The spec is saved to a file in the repository