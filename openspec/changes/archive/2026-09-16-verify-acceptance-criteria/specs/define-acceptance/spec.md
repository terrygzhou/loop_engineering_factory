# define-acceptance (spec)

## Purpose
Defines the machine-checkable acceptance-test block that DEFINE emits into
the generated spec.

## ADDED Requirements

### Requirement: Spec acceptance-test block
DEFINE SHALL emit, as part of `artifacts.spec_refined`, a fenced JSON block
`{"acceptance_tests": [{"id": "AT-NN", "check": "<local test command or
predicate>", "expect": "<expected result>"}]}` derived from the spec's user
stories and, when set, `artifacts.arckit_nfr_constraints`. The block SHALL
be valid JSON; `check` SHALL be a local command or predicate (no network
access). When no user stories or NFRs are available, the block SHALL be
omitted entirely (never an empty array, never a sentinel value). A fatal
LLM failure SHALL result in no block plus a warning event (Decision 3),
never a raised error.

#### Scenario: User stories and NFRs present
- **WHEN** DEFINE generates a spec with user stories and NFR constraints
- **THEN** the spec contains a valid acceptance-test block with at least
  one test per user story

#### Scenario: Nothing to derive tests from
- **WHEN** the spec has no user stories and no NFR constraints
- **THEN** no acceptance-test block is emitted and downstream nodes see
  no block

#### Scenario: Fatal LLM failure
- **WHEN** the spec LLM call fails fatally
- **THEN** the spec has no acceptance block, a warning event is logged,
  and the node returns without raising
