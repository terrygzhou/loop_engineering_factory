# skill-registry

## Purpose
The SKILL.md skill library and its hot-reloading registry that every phase
prompt is built from.

## Requirements

### Requirement: Skill registry
The system SHALL load SKILL.md files from skills/ via tools/loader.py
build_skill_registry, caching by mtime so edits are picked up without a
restart.

#### Scenario: Skill hot-reload
- **WHEN** a SKILL.md file is modified on disk
- **THEN** the next registry lookup serves the updated content

### Requirement: Skill distillation
Prompts to the LLM SHALL be built from tools/distiller.distill_skill output
(purpose + process) and capped by the token/char limits in config/bounds.yaml
(enforced by tools/context_manager.prepare_context_for_llm).

#### Scenario: Context bounds
- **WHEN** a prepared context exceeds the bounds.yaml limits
- **THEN** prepare_context_for_llm trims it to fit before the LLM call
