# plan-architecture-diagrams (spec)

## Purpose
Defines PLAN's architecture-diagram generation: the base 4-view set and the
use-case-driven UML sequence views.

## ADDED Requirements

### Requirement: PLAN architecture diagram set
PLAN SHALL generate four base Mermaid views — component, sequence (generic),
data flow, deployment — from the spec/plan/tasks/doubt context, and SHALL
generate one Mermaid `sequenceDiagram` per available use case, keyed in
`artifacts.diagrams` as `sequence_<slug>`. Use cases SHALL be extracted from
`artifacts.arckit_nfr_constraints` (`use_cases`) when set, else from the
interview/spec user-flow content, else not at all. When no use case is
available, the generic sequence view SHALL be the fallback and behaviour SHALL
be identical to the pre-change diagram set. All views SHALL be converted to
PNG via the existing pipeline and carried in `artifacts.diagram_pngs`.

#### Scenario: Use cases present
- **WHEN** PLAN runs with three use cases in `arckit_nfr_constraints`
- **THEN** `artifacts.diagrams` holds the four base views plus three
  `sequence_*` views, one per use case

#### Scenario: No use cases
- **WHEN** PLAN runs with no use cases from any source
- **THEN** the diagram set is exactly the four base views (generic sequence
  view included), as before this change

#### Scenario: LLM failure degrades, never raises
- **WHEN** a diagram LLM call returns None (fatal LLM failure, Decision 3)
- **THEN** that diagram is a placeholder marker and PLAN completes without
  raising
