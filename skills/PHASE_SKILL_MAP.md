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
| `interview-me` | ✅ | Structured user interview for requirements |
| `idea-refine` | 📦 | Clarify and refine vague ideas into concrete specs |
| `context-engineering` | 📦 | Build project context for downstream phases |

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

## SEED_DATA (test data)

| Skill | Status | Purpose |
|-------|--------|---------|
| `test-driven-development` | ✅ | Test data generation |
| `debugging-and-error-recovery` | 📦 | Handle build/test failures |

## VERIFY (verification)

| Skill | Status | Purpose |
|-------|--------|---------|
| `code-review-and-quality` | 📦 | Code quality review |
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
| `git-workflow-and-versioning` | 📦 | Git operations and versioning |

## REFLECT (meta-reflection)

| Skill | Status | Purpose |
|-------|--------|---------|
| `using-agent-skills` | 📦 | Agent skill usage analysis |
| `deprecation-and-migration` | 📦 | Deprecation and migration strategy |

## Local Custom Skills (🔧)

| Skill | Phase | Purpose |
|-------|-------|---------|
| `architecture-diagram-generator` | PLAN | Mermaid diagram generation |
| `uat-workflow` | VERIFY/SHIP | UAT test execution |
| `production-deployment` | SHIP | Production deployment |
| `docker-compose-deployment` | BUILD/SHIP | Docker build and deploy |
| `fabric-prompts` | DEFINE | Prompt optimization |
| `writing-plans` | PLAN | Legacy — superseded by `planning-and-task-breakdown` |

## Coverage Summary

- **Total agent-skills**: 24
- **Downloaded to project**: 23/24 (all except `using-agent-skills` — meta-reference only)
- **Active in graph**: 12
- **Ready to wire**: 11
- **Local custom**: 7

## Wiring Priority

1. **HIGH**: `planning-and-task-breakdown` → PLAN (replaces legacy `writing-plans`)
2. **HIGH**: `code-review-and-quality` → VERIFY
3. **MED**: `debugging-and-error-recovery` → SEED_DATA / VERIFY
4. **MED**: `idea-refine` → DISCOVER
5. **LOW**: Remaining 📦 skills — phase-dependent based on project type