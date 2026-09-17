# Loop Factory — Phase × Skill Mapping

Maps each LangGraph phase to its agent-skills from `addyosmani/agent-skills`.
All skills are in `skills/` and auto-discovered by `tools/loader.py`.

## Legend

| Status | Meaning |
|--------|---------|
| ✅ | Loaded, active in graph |
| 📦 | Downloaded, ready to wire |
| 🔧 | Local custom skill (not from agent-skills) |
| 🚧 | Placeholder — not yet implemented |

## DISCOVER (requirement gathering)

| Skill | Status | Purpose |
|-------|--------|---------|
| `fabric-prompts` | ✅ | Prompt optimization |
| `coding-principles` | ✅ | Coding principles guidance |
| `idea-refine` | ✅ | Clarify and refine vague ideas into concrete specs |

## DEFINE (specification)

| Skill | Status | Purpose |
|-------|--------|---------|
| `spec-driven-development` | ✅ | Generate structured 6-section spec |
| `source-driven-development` | 📦 | Base decisions on existing codebase analysis |
| `api-and-interface-design` | ✅ | Design API contracts and interfaces |

## PLAN (implementation plan)

| Skill | Status | Purpose |
|-------|--------|---------|
| `planning-and-task-breakdown` | 📦 | Generate task breakdown and milestones |
| `doubt-driven-development` | ✅ | Challenge architectural assumptions |
| `documentation-and-adrs` | 📦 | Generate architecture decision records |
| `code-simplification` | ✅ | Ensure plan stays lean |

## ARCH_REVIEW (human gate)

No skills — human decision point only. Payload enriched with:
- Task breakdown from PLAN
- Spec summary from DEFINE
- Architecture diagrams

## BUILD (implementation)

| Skill | Status | Purpose |
|-------|--------|---------|
| `incremental-implementation` | ✅ | Build vertical slices |
| `frontend-ui-engineering` | ✅ | Frontend implementation guidance (injected into UI items in legacy fallback; OpenHands prompt carries UI guardrails) |
| `context-engineering` | 📦 | Maintain build context |
| `pre-commit-review` | 🔧 | Pre-commit quality gate (aggregate code quality pass after security-and-hardening in SECURITY_GATE) |

## SEED_DATA (test data)

| Skill | Status | Purpose |
|-------|--------|---------|
| `test-driven-development` | ✅ | Test data generation |
| `debugging-and-error-recovery` | 📦 | Handle build/test failures |

## VERIFY (verification)

| Skill | Status | Purpose |
|-------|--------|---------|
| `pre-commit-review` | 🔧 | Code quality review (multi-axis quality gate; superseded `code-review-and-quality`) |
| `security-and-hardening` | ✅ | Security audit |
| `debugging-and-error-recovery` | 📦 | Debug verification failures |
| `browser-testing-with-devtools` | 📦 | Browser-based E2E testing |

## SHIP (deployment)

| Skill | Status | Purpose |
|-------|--------|---------|
| `shipping-and-launch` | ✅ | Pre-launch checklist and rollback |
| `ci-cd-and-automation` | 📦 | CI/CD pipeline setup |
| `observability-and-instrumentation` | ✅ | Monitoring and observability |
| `performance-optimization` | ✅ | Performance audit |
| `git-workflow` | ✅ | Git operations and versioning (supersedes `git-workflow-and-versioning` — see note below) |

> Superseded: `git-workflow-and-versioning` is no longer referenced by any
> graph node; the SHIP/REFLECT nodes call `git-workflow` instead. Kept in
> `skills/` for reference.

## REFLECT (meta-reflection)

| Skill | Status | Purpose |
|-------|--------|---------|
| `git-workflow` | ✅ | Commit approved config diffs after REFLECT approval |

## Local Custom Skills (🔧)

| Skill | Phase | Purpose |
|-------|-------|---------|
| `architecture-diagram-generator` | PLAN | Mermaid diagram generation |
| `uat-workflow` | VERIFY/SHIP | UAT test execution |
| `production-deployment` | SHIP | Production deployment |
| `docker-compose-deployment` | BUILD/SHIP | Docker build and deploy |
| `fabric-prompts` | DISCOVER | Prompt optimization |
| `writing-plans` | PLAN | ⚠️ Superseded by `planning-and-task-breakdown` — kept for reference, no longer wired into any phase |

## Coverage Summary

- **Total agent-skills**: 24
- **Downloaded to project**: 24/24
- **Active in graph**: 15
- **Ready to wire**: 5
- **Local custom**: 7

## Wiring Priority

1. **HIGH**: `planning-and-task-breakdown` → PLAN (replaces legacy `writing-plans`)
2. **HIGH**: `pre-commit-review` → VERIFY
3. **MED**: `source-driven-development` → DEFINE
4. **MED**: `context-engineering` → BUILD
5. **MED**: `ci-cd-and-automation` → SHIP
6. **MED**: `documentation-and-adrs` → PLAN
7. **MED**: `browser-testing-with-devtools` → VERIFY
8. **LOW**: Remaining 📦 skills — phase-dependent based on project type