---
name: git-workflow
description: "Git workflow discipline: commit strategy, branching, worktrees, debugging, and GitHub CLI operations for AI agent development."
version: 1.0.0
author: Hermes Agent (merged from agent-skills + github-workflows)
category: github
metadata:
  hermes:
    tags: [git, workflow, commits, branching, worktrees, gh-cli, debugging]
    related_skills: [requesting-code-review, test-driven-development, subagent-driven-development]
---

# Git Workflow

Git is your safety net. Treat commits as save points, branches as sandboxes, and history as documentation. With AI agents generating code at high speed, disciplined version control is the mechanism that keeps changes manageable, reviewable, and reversible.

## When to Use

Always. Every code change flows through git.

---

## Commit Discipline

### 1. Commit Early, Commit Often

Each successful increment gets its own commit. Don't accumulate large uncommitted changes.

```
Work pattern:
  Implement slice → Test → Verify → Commit → Next slice

Not this:
  Implement everything → Hope it works → Giant commit
```

Commits are save points. If the next change breaks something, you can revert to the last known-good state instantly.

### 2. Atomic Commits

Each commit does one logical thing. Target **~100 lines per commit**. Changes over ~1000 lines should be split.

```bash
# Good: Each commit is self-contained
git log --oneline
a1b2c3d feat: add email validation to registration endpoint
d4e5f6g fix: handle edge case in payment processing
h7i8j9k test: add integration tests for user auth

# Bad: Everything mixed together
x1y2z3a Add feature, fix sidebar, update deps, refactor utils
```

### 3. Descriptive Messages (Conventional Commits)

```
<type>: <short description>

<optional body explaining why, not what>
```

**Types:**
- `feat` — New feature
- `fix` — Bug fix
- `refactor` — Code change that neither fixes a bug nor adds a feature
- `test` — Adding or updating tests
- `docs` — Documentation only
- `chore` — Tooling, dependencies, config

```bash
# Good: Explains intent
feat: add email validation to registration endpoint

Prevents invalid email formats from reaching the database.
Uses Pydantic schema validation at the route handler level,
consistent with existing validation patterns in auth.py.

# Bad: Describes what's obvious from the diff
fix: update auth.py
```

### 4. Keep Concerns Separate

Don't combine formatting changes with behavior changes. Don't combine refactors with features.

```bash
# Good: Separate concerns
git commit -m "refactor: extract validation logic to shared utility"
git commit -m "feat: add phone number validation to registration"

# Bad: Mixed concerns
git commit -m "refactor validation and add phone number field"
```

### 5. The Save Point Pattern

```
Agent starts work
    │
    ├── Makes a change
    │   ├── Test passes? → Commit → Continue
    │   └── Test fails? → Revert to last commit → Investigate
    │
    ├── Makes another change
    │   ├── Test passes? → Commit → Continue
    │   └── Test fails? → Revert to last commit → Investigate
    │
    └── Feature complete → All commits form a clean history
```

If an agent goes off the rails, `git reset --hard HEAD` takes you back to the last successful state.

---

## Change Summaries

After any modification, provide a structured summary. See `references/change-summary-pattern.md` for the full template.

```
CHANGES MADE:
- app/routers/reviews.py: Added POST endpoint with validation
- app/schemas/reviews.py: Added ReviewCreate schema

THINGS I DIDN'T TOUCH (intentionally):
- app/routers/auth.py: Has similar validation gap but out of scope
- app/services/email.py: Could use retry logic (separate task)

POTENTIAL CONCERNS:
- The schema is strict — rejects extra fields. Confirm this is desired.
- Added review service as new module — existing patterns followed
```

This catches wrong assumptions early and gives reviewers a clear map of the change. The "DIDN'T TOUCH" section shows you exercised scope discipline.

---

## Branching Strategy

### Trunk-Based Development (Recommended)

Keep `main` always deployable. Work in short-lived feature branches that merge back within 1-3 days.

```
main ──●──●──●──●──●──●──●──●──●──  (always deployable)
        ╲      ╱  ╲    ╱
         ●──●─╱    ●──╱    ← short-lived feature branches (1-3 days)
```

- **Dev branches are costs.** Every day a branch lives, it accumulates merge risk.
- **Feature flags > long branches.** Prefer deploying incomplete work behind flags.

### Branch Naming

```
feature/<short-description>   → feature/review-rating
fix/<short-description>       → fix/duplicate-tasks
chore/<short-description>     → chore/update-deps
refactor/<short-description>  → refactor/auth-module
```

- Branch from `main`
- Keep branches short-lived (merge within 1-3 days)
- Delete branches after merge

---

## Working with Worktrees

For parallel subagent work, use git worktrees. See `references/parallel-worktrees.md` for setup and subagent dispatch pattern.

```bash
# Quick start
git worktree add ../project-feature-a feature/task-creation
git worktree add ../project-feature-b feature/user-settings

# Each worktree is a separate directory with its own branch
ls ../
  project/              ← main branch
  project-feature-a/    ← task-creation branch
  project-feature-b/    ← user-settings branch

# When done, merge and clean up
git worktree remove ../project-feature-a
```

**Benefits for agent workflows:**
- Multiple subagents can work on different features simultaneously
- No branch switching needed (each directory has its own branch)
- If one experiment fails, delete the worktree — nothing is lost
- Changes are isolated until explicitly merged

---

## Pre-Commit Hygiene

Before every commit:

```bash
# 1. Check what you're about to commit
git diff --staged

# 2. Ensure no secrets
git diff --staged | grep -i "password\|secret\|api_key\|token"

# 3. Run tests (Python/pytest)
python -m pytest --tb=no -q

# 4. Run linting (if installed)
which ruff && ruff check . 2>&1 | tail -10
```

---

## Using Git for Debugging

```bash
# Find which commit introduced a bug
git bisect start
git bisect bad HEAD
git bisect good <known-good-commit>
# Git checkouts midpoints; run your test at each to narrow down
# git bisect reset when done

# View what changed recently
git log --oneline -20
git diff HEAD~5..HEAD -- src/

# Find who last changed a specific line
git blame path/to/file.py

# Search commit messages for a keyword
git log --grep="validation" --oneline

# Stash changes temporarily
git stash push -m "WIP: review feature"
git stash pop
```

---

## GitHub CLI Operations

### Authentication

```bash
# Interactive login
gh auth login

# Check status
gh auth status

# Token-based (headless/CI)
gh auth login --with-token <<< 'ghp_...'
```

**Token scopes needed:** `repo` (full), `workflow`, `delete_repo`

### First SSH Connection (Headless)

```bash
# Accept GitHub host key non-interactively
ssh-keyscan github.com >> ~/.ssh/known_hosts

# Or inline for a single push
GIT_SSH_COMMAND="ssh -o StrictHostKeyChecking=accept-new" git push origin main
```

### Common Commands

```bash
# Branch/PR
gh pr create                    # Create PR
gh pr view <number>             # View PR
gh pr check-runs                # Status checks
gh pr checkout <number>         # Checkout PR branch

# Issues
gh issue create                 # Create issue
gh issue list --label "bug"     # Filter by label

# Repo
gh repo create owner/repo --private --source . --remote origin
```

### Auto-Creating Repos

```bash
# Check if repo exists before creating
gh repo view owner/repo --json name --jq ".name" || \
gh repo create owner/repo --private --source . --remote origin
```

**Pre-requisites:** `gh` CLI installed, authenticated, git identity configured.

---

## Handling Generated Files

- **Commit:** `.env.example`, migrations, lock files
- **Do NOT commit:** `.env`, `.env.*` (except `.example`), build output, `node_modules/`
- **Have a `.gitignore`** covering: `.env`, `.env.local`, `*.pem`, `__pycache__/`, `.pytest_cache/`, `dist/`, `build/`

---

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "I'll commit when the feature is done" | One giant commit is impossible to review, debug, or revert. Commit each slice. |
| "The message doesn't matter" | Messages are documentation. Future you (and future agents) will need context. |
| "I'll squash it all later" | Squashing destroys the development narrative. Prefer clean incremental commits. |
| "Branches add overhead" | Short-lived branches are free. Long-lived branches are the problem. |
| "I don't need a .gitignore" | Until `.env` with production secrets gets committed. Set it up immediately. |

---

## Red Flags

- Large uncommitted changes accumulating
- Commit messages like "fix", "update", "misc"
- Formatting changes mixed with behavior changes
- No `.gitignore` in the project
- Committing `.env`, build artifacts, or secrets
- Long-lived branches that diverge from main
- Force-pushing to shared branches

---

## Verification

For every commit:

- [ ] Commit does one logical thing
- [ ] Message explains the why, follows conventional commit types
- [ ] Tests pass before committing
- [ ] No secrets in the diff
- [ ] No formatting-only changes mixed with behavior changes
- [ ] `.gitignore` covers standard exclusions
