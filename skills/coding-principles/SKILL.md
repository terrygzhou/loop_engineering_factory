---
name: coding-principles
description: "Universal coding principles for AI agents — think before coding, keep it simple, make surgical changes, verify before shipping."
version: 1.0.0
author: Terry Zhou
metadata:
  hermes:
    tags: [coding, programming, python, debugging, implementation, software-engineering, ai-agent, best-practices, quality, code-review, bugfix]
---

# Coding Principles

Apply these principles to every coding task. They govern how you approach problems, write code, and verify results.

## Think Before Coding

Stop, map out a logical plan, and evaluate your approach before generating code.

**Mandatory planning phase — execute in this order:**
1. **List files** — enumerate every file that needs changes
2. **Outline approach** — 3-5 bullet points describing the implementation strategy
3. **Identify edge cases** — error paths, boundary conditions, failure modes

Then implement based on the plan.

**Deterministic output (equivalent to temperature=0.1, top_p=0.5):**
- Prefer the most obvious, standard solution — avoid creative exploration
- When multiple approaches exist, choose the most common/conventional one
- Do not speculate, improvise, or introduce novel patterns unless explicitly asked
- Code should be consistent and reproducible across runs

- Read existing code paths related to the task before writing new code
- Trace symbols to their definitions and usages — never guess API shapes
- Plan the minimal set of changes needed before touching files
- For multi-file changes, identify all affected files upfront

## Simplicity over Complexity

Write clear, modular, and minimal code.

- Prefer simple, readable solutions that solve the immediate problem
- Never over-engineer or add abstraction layers without proven need
- Keep functions short and focused on a single responsibility
- If you can solve it with stdlib instead of a dependency, do that

### Never slice non-sequence types
- **Symptom:** `v[:500]` on a dict raises `KeyError: slice(None, 500, None)`
- **Root cause:** Dicts don't support slicing. Truncation logic assumes all values are strings/lists.
- **Fix — type-check before slicing:**
  ```python
  def truncate_for_storage(value, limit=500):
      if isinstance(value, str):
          return value[:limit]
      if isinstance(value, list):
          return value[:limit]
      if isinstance(value, dict):
          return {k: str(v)[:limit] for k, v in value.items()}
      return str(value)[:limit]
  ```

### Surgical Changes

Alter only the exact blocks of code needed.

- Never rewrite whole files when a targeted `patch` will do
- Preserve existing structure, naming, and style unless explicitly asked to refactor
- Match the project's conventions — check neighboring files for import patterns, formatting, etc.
- Don't add drive-by refactors, renames, or cosmetic changes

## Verifiable Success Criteria

Always define how success is verified before implementing.

- Before coding: state what tests to run or how to verify manually (e.g. `curl` endpoint, browser check)
- After coding: actually run the tests, build, or verification command — don't just describe them
- If tests fail: fix the root cause, not just the symptom
- Never claim "this should work" — prove it with real tool output

## Record-Only Mode

When the user says "record issues as backlog items", "don't fix, just log", or "move on without fixing":

- Systematically test all features/pages
- Log each issue to `build/backlog.md` with ID, priority, page, summary, and details
- **DO NOT attempt fixes** — record and move to the next item
- Update the backlog summary table at the end with new counts
- This is an audit/discovery pass — fixes come in a later session

## When to Delegate or Debug

Not every task is a direct edit. Choose the right tool based on scope and symptoms.

### Multi-file tasks → `subagent-driven-development`

When a change touches **3+ independent files** or spans multiple layers (schema → service → router → test):

1. Load the skill: `skill_view(name='subagent-driven-development')`
2. Dispatch file-level changes to separate subagents via `delegate_task`
3. Each subagent owns one task with fresh context (no accumulated state)
4. Review outputs before proceeding — two-stage review (spec compliance, then code quality)
5. **Do NOT delegate** when: batch document creation, simple batch fixes, or a single tool call suffices

### Things break → `systematic-debugging`

When tests fail, endpoints error, or behavior is unexpected:

1. Load the skill: `skill_view(name='systematic-debugging')`
2. Follow the 4 phases: **Root Cause → Pattern Analysis → Hypothesis → Implementation**
3. Never fix symptoms without tracing the root cause first
4. If 3+ fixes fail, question the architecture — don't thrash
5. **Do NOT guess** — gather evidence at each boundary before proposing changes

### Decision flow

```
Task → How many files? → 1-2 files → direct patch/write_file
              → 3+ files → subagent-driven-development
Working? → No → systematic-debugging (4-phase)
         → Yes → Verifiable Success Criteria → ship

## Skill Loading Reality

`auto_load: true` in YAML frontmatter is a **soft hint** — marks the skill as "candidate" in the `<available_skills>` catalog. The LLM decides whether to `skill_view()`. **No guarantee.**

**Hard preload paths (guaranteed loading):**
- **CLI:** `hermes --skills coding-principles` (or shell alias: `alias hermes='hermes --skills coding-principles'`)
- **ACP (`hermes acp`):** Does NOT accept `--skills`. Workaround: add `BEFORE any coding task: skill_view(name='coding-principles')` to project-root `AGENTS.md` — auto-injected by `agent.coding_context: auto` (your default config)
- **No config-level `preload_skills` key** exists in `config.yaml` — do not assume one does

**Verification:** After a session starts, call `skill_view(name='coding-principles')` — if the skill loads without a tool call (content already known), hard preload worked.

## Skill Loading Reality

`auto_load: true` in the YAML frontmatter is a **soft hint** — it marks the skill as "candidate" in the `<available_skills>` catalog. The LLM decides whether to `skill_view()`. **No guarantee.**

**To guarantee loading:**
- **CLI:** `hermes --skills coding-principles` (or alias in `~/.bashrc`)
- **ACP:** No `--skills` flag support. Workaround: add `skill_view(name='coding-principles')` to the project's `AGENTS.md` (picked up by `coding_context: auto`)
- **No config-level `preload_skills` key** exists in `config.yaml` — don't assume one does

## How This Skill Loads

Hermes has no `auto_load` mechanism. This skill loads through two real paths:

1. **System prompt scanning** — Every session includes an `<available_skills>` block listing all installed skills with one-line descriptions. The system prompt directive requires scanning this block and calling `skill_view(name)` when the task matches. This skill fires on any coding-related task via its tags: `[coding, programming, python, debugging, implementation, software-engineering, ai-agent, best-practices, quality, code-review, bugfix]`.

2. **Explicit preload** — Use `hermes --skills coding-principles` or `hermes -s coding-principles` to inject it at session start (useful for focused coding sessions or ACP/IDE integration).

**ACP / VS Code integration** — When running `hermes acp` as an ACP server in VS Code (`formulahendry.acp-client`), skills load the same way: the `<available_skills>` block is in-context and the agent calls `skill_view()` when needed. No special config required beyond the standard `hermes acp` launch. To preload, add `--skills coding-principles` to the ACP command in your VS Code `settings.json`:
```json
{
  "acp.agents": {
    "Hermes Agent": {
      "command": "hermes",
      "args": ["acp", "--skills", "coding-principles"]
    }
  }
}
```
