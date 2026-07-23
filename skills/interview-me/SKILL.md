---
name: interview-me
description: Elicit requirements from the user one question at a time to build a structured discovery document
category: software-development
---

# Interview Me

## Purpose

Structured requirement elicitation: ask focused questions one at a time, build a discovery document from the answers. Used in DISCOVER phase to gather project context before DEFINE.

## Interview Flow

```
Project Setup → Core Behavior → Data Model → API Surface → Integration → Constraints
```

### Questions

| # | Category | Question | Purpose |
|---|----------|----------|---------|
| 1 | core_behavior | What does this feature do? | Primary functionality |
| 2 | data_model | What entities and fields? | Domain model |
| 3 | api_surface | Methods, paths, auth? | Interface contract |
| 4 | validation | Input validation rules? | Data integrity |
| 5 | ui_template | Templates or UI requirements? | Presentation layer |
| 6 | integration | External services, DB, APIs? | Dependencies |
| 7 | deployment | Docker/infrastructure implications? | Deployment strategy |
| 8 | edge_cases | Known edge cases? | Risk identification |
| 9 | non_functional | Performance, security, monitoring? | Quality attributes |

## Output

Produces structured discovery notes:
```markdown
# {project_name} — Discovery Report

## Project Overview
{description}

## Requirements
- core_behavior: {answer}
- data_model: {answer}
- api_surface: {answer}
- validation: {answer}
- ui_template: {answer}
- integration: {answer}
- deployment: {answer}
- edge_cases: {answer}
- non_functional: {answer}

## Constraints
- {project_folder}
- {project_type}
```

## Usage

Called from `discover_node()` via `invoke_skill()` when the interview phase needs structured elicitation. The DISCOVER node handles the HIL interrupt flow; this skill shapes the output into a discovery document.

## Pitfalls

- Don't ask all questions at once — one at a time, wait for answer
- If the user gives a vague answer, ask a clarifying follow-up before moving on
- Skip questions the user explicitly says are not applicable — don't force every category
- Record "N/A" for skipped questions, don't leave them blank

## Related Skills

- `writing-plans` — takes discovery output and creates implementation plans
- `api-and-interface-design` — formalizes API contracts from interview findings
- `coding-principles` — guides technical decisions based on project domain