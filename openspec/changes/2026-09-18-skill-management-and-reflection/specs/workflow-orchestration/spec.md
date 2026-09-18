# workflow-orchestration (delta)

## ADDED Requirements

### Requirement: REFLECT skill-performance review
REFLECT SHALL run a skill-performance review step AFTER config-diff
generation and BEFORE the human-approval gate. The review feeds an LLM
the cycle's performance signals and produces per-skill verdicts plus
next-iteration recommendations. The LLM prompt is built by
`feedback/skill_review.py` (pure helpers, no graph dependency).

Signals fed to the review (collected by
`build_skill_review_context(state)`):
- per-skill usage counts (from `state["feedback"]` `skill_invoked`
  entries),
- loop counters (`state["artifacts"]["loop_counts"]`),
- `test_errors`, `verify_status`, `acceptance_results`,
- the cycle's own proposed config diffs
  (`state["artifacts"]["proposed_diffs"]`).

LLM output (JSON, parsed by `run_skill_review`):
- `verdicts`: one per used skill — `{skill, verdict:
  keep|improve|retire, signal, rationale}`
- `recommendations`: 1–3 entries —
  `{skill, action, target, suggestion, priority}`

Persistence:
- `artifacts.skill_review` (JSON string, matching the `proposed_diffs`
  convention) in the node's returned `artifacts` delta.
- `storage/skill_recommendations.json` — the persistent cross-cycle
  artifact the next DISCOVER/DEFINE cycle reads.
- A `feedback` entry `{"action": "skill_reviewed", "status": ...,
  "verdict_count": N}`.

Decision 3 compliance: when the LLM is `None` (dry-run) or the call
fails, the review is recorded as `{"status": "unavailable", "reason":
...}` and the node still completes — the review SHALL NOT raise and
SHALL NOT block the REFLECT phase.

#### Scenario: Review runs and persists on a passing cycle
- **WHEN** `reflect_node` completes a cycle with a working LLM
- **THEN** `artifacts.skill_review` is a JSON string with
  `status: "ok"` and at least one verdict, AND
  `storage/skill_recommendations.json` exists with the same verdicts,
  AND a `skill_reviewed` feedback entry was recorded

#### Scenario: LLM unavailable degrades, never raises
- **WHEN** `reflect_node` runs with `get_llm()` returning `None`
- **THEN** `artifacts.skill_review` decodes to
  `{"status": "unavailable", "reason": ...}` and the node returns
  normally (no exception, `next_phase` still `"END"`)

### Requirement: Advisory skill-recommendation injection
The next DISCOVER/DEFINE cycle SHALL inject the prior REFLECT
skill-review recommendations as advisory prompt context. The block is
rendered by `tools/skill_recommendations.py::skill_recommendations_block`
(reads `storage/skill_recommendations.json`) and appended:
- in DISCOVER, to the fabric-principles prompt in
  `_generate_requirement_via_fabric`;
- in DEFINE, inside `_arckit_advisory_context` (which already feeds
  both parallel source-driven + api-design prompts, so one edit covers
  both).

Byte-identity: when the file is absent or has no recommendations, the
block is the empty string and the prompt is byte-identical to the
pre-feature behavior. The block is advisory (non-routing) context —
it SHALL NOT influence `route_phase` or any gate.

#### Scenario: Recommendations present → block appended
- **WHEN** `storage/skill_recommendations.json` exists with
  non-empty `recommendations`
- **THEN** the DISCOVER fabric prompt and the DEFINE advisory context
  contain a `SKILL RECOMMENDATIONS` section listing each
  `{skill, priority, suggestion}`

#### Scenario: No file → byte-identical prompt
- **WHEN** `storage/skill_recommendations.json` does not exist (or has
  no recommendations)
- **THEN** `skill_recommendations_block()` returns `""` and the
  DISCOVER/DEFINE prompts are byte-identical to a run without this
  feature
