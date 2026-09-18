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
| `interview-me` | ✅ | Structured user interview to extract requirements |

## DEFINE (specification)

| Skill | Status | Purpose |
|-------|--------|---------|
| `spec-driven-development` | ✅ | Generate structured 6-section spec |
| `source-driven-development` | ✅ | Base decisions on existing codebase analysis |
| `api-and-interface-design` | ✅ | Design API contracts and interfaces |

## PLAN (implementation plan)

| Skill | Status | Purpose |
|-------|--------|---------|
| `planning-and-task-breakdown` | ✅ | Generate task breakdown and milestones |
| `doubt-driven-development` | ✅ | Challenge architectural assumptions |
| `documentation-and-adrs` | 📦 | Generate architecture decision records |
| `code-simplification` | 📦 | Ensure plan stays lean |

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
| `performance-optimization` | 📦 | Performance audit |
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
- **Active in graph**: 16
- **Ready to wire**: 7
- **Local custom**: 7

## Wiring Priority

1. **HIGH**: `pre-commit-review` → VERIFY
2. **HIGH**: `documentation-and-adrs` → PLAN
3. **MED**: `context-engineering` → BUILD
4. **MED**: `ci-cd-and-automation` → SHIP
5. **MED**: `browser-testing-with-devtools` → VERIFY
6. **LOW**: `code-simplification` → PLAN
7. **LOW**: `performance-optimization` → SHIP
8. **LOW**: Remaining 📦 skills — phase-dependent based on project type

## Skill Management (Feature 1)

Skills are managed through the Web API (`tools/skill_manager.py` is the single
source of truth; the loader auto-picks up add/remove on disk):

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/skills` | GET | List every skill + version + active-in-graph flag |
| `/api/skills/register` | POST | Register a new skill from raw SKILL.md text |
| `/api/skills/remove` | POST | Remove a skill by name |
| `/api/skills/update` | POST | Pull one skill from a configured GitHub source |
| `/api/skills/sync` | POST | Sync every skill from every source in `config/skill_sources.yaml` |
| `/api/skills/recommendations` | GET | Read the persistent skill-review output |

GitHub sources are config-driven (`config/skill_sources.yaml`); no repo is
hardcoded in the manager.

## REFLECT Skill Review (Feature 2)

REFLECT now runs a skill-performance review (after config diffs, before the
HIL gate). Signals: per-skill usage counts, loop counters, test_errors,
acceptance_results, proposed config diffs. Output: per-skill verdicts
(keep/improve/retire) + 1–3 next-iteration recommendations, stored in
`artifacts.skill_review` and `storage/skill_recommendations.json`. The next
DISCOVER/DEFINE cycle injects the recommendations as advisory prompt context.
LLM failure degrades to `status: unavailable` (Decision 3), never raises.