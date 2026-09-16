# build-delegation (delta)

## ADDED Requirements

### Requirement: BUILD prompt advisory context
The OpenHands build prompt SHALL include, as advisory (non-routing) sections,
exactly those of the following keys that are set in `artifacts`:
`arch_review_answers`, `arckit_product_backlog`,
`arckit_strategy_waves`, `arckit_data_model`,
`arckit_integration_standards`, `arckit_security_controls`,
`arckit_nfr_constraints`. Unset keys SHALL contribute no section: when
none of the keys is set the prompt SHALL be byte-identical to the prompt of a
run with no ArcKit context. Advisory sections SHALL NOT alter the
build_report.json manifest contract (Decision 1) or the BUILD retry budget.

#### Scenario: ArcKit context present
- **WHEN** BUILD runs with `arckit_data_model`,
  `arckit_integration_standards`, and `arch_review_answers` set
- **THEN** the build prompt contains three advisory sections with that
  content and the manifest contract is unchanged

#### Scenario: No ArcKit context
- **WHEN** no ArcKit-related key is set
- **THEN** the prompt is identical to the pre-change prompt (no empty
  sections, no sentinel markers)
