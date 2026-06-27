---
name: architecture-diagram-generator
description: Generate architecture diagrams from workflow artifacts (spec, plan, tasks). Supports Mermaid, PlantUML, and C4 models. Creates visual representations of system design, data flow, and component relationships.
triggers:
  - architecture-diagram
  - system-design
  - component-diagram
  - sequence-diagram
  - c4-model
  - mermaid-diagram
  - plantuml
version: "1.0.0"
---

# Architecture Diagram Generator

## Purpose

Generate architecture diagrams from workflow artifacts as deliverables for user review. Creates visual representations of system design, component relationships, and data flows.

## Process

1. Analyze spec_refined for system components and relationships
2. Extract API contracts to map endpoints and data models
3. Parse implementation plan for architectural patterns
4. Generate Mermaid diagram with component, sequence, and data flow views
5. Create C4 model (Context, Container, Component, Code)
6. Output structured diagram file alongside implementation artifacts
7. Present diagram for user review before BUILD phase

## Diagram Types

- **Component Diagram**: System components and their relationships
- **Sequence Diagram**: Request flow and interaction patterns
- **Data Flow Diagram**: Entity relationships and data movement
- **Deployment Diagram**: Infrastructure and deployment topology

## Output Format

```
build/
└── diagrams/
    ├── component-diagram.mmd
    ├── sequence-diagram.mmd
    ├── data-flow.mmd
    └── deployment-diagram.mmd
```

## Rules

- Generate diagrams from actual spec/plan content
- Include all components mentioned in artifacts
- Mark unknown/assumed components clearly
- Create diagrams that can be visually reviewed
- Support both Mermaid (default) and PlantUML formats
- Validate diagram syntax before output
