# Spec Delta: skill-registry

## MODIFIED: `PHASE_SKILL_MAP.md` reflects actual graph skill lookups

The `skills/PHASE_SKILL_MAP.md` document MUST list, per phase, exactly the
skills that the active graph node calls via `skills.get("<name>")` — no
more, no fewer.

### Scenarios

**Phase rows match code**
- DISCOVER row lists `fabric-prompts`, `coding-principles`, `idea-refine`
  (all ✅) — the three skills looked up in `graph/nodes/discover.py`.
- REFLECT row lists `git-workflow` (✅) — the only skill looked up in
  `graph/nodes/reflect.py`.
- SHIP row lists `git-workflow` (✅) — matching `graph/nodes/ship.py:158`.
- No phase row lists a skill that no node calls (e.g. `interview-me`,
  `context-engineering`, `using-agent-skills`, `deprecation-and-migration`).

**Superseded skills marked, not deleted**
- `writing-plans` and `git-workflow-and-versioning` appear with a
  "superseded by …" note rather than being silently removed, so a reader
  who sees one of these names elsewhere can follow the alias.

## ADDED: No new skills required for ArcKit advisory blocks

The ArcKit advisory-block pattern (advisory JSON context capped by
`bounds.context.arckit_advisory_max_chars`, byte-identical prompt when the
key is absent) is an established engineering convention, not a skill.
This change MUST NOT introduce a new `skills/<name>/SKILL.md` as a
prerequisite for consuming `arckit_product_backlog` or
`arckit_data_model`.
