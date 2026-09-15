# human-in-the-loop

## Purpose
Human approval gates that pause the pipeline for operator decisions, a
headless auto-approve mode, and the ACHG safety interlock.

## Requirements

### Requirement: HIL gates
The system SHALL pause at DISCOVER (project setup + interview, merged into one
node) and at ARCH_REVIEW using langgraph interrupt(); the compile-time
interrupt_after list SHALL apply only when auto_approve is off.

#### Scenario: Auto-approve bypass
- **WHEN** auto_approve=true in config or --auto-approve on the CLI
- **THEN** the graph compiles without interrupt_after and no HIL pauses fire

#### Scenario: Architectural reject
- **WHEN** a reviewer rejects at ARCH_REVIEW with feedback
- **THEN** the flow returns to PLAN with user_review_comments set

### Requirement: Interactive HIL cycle
The interactive CLI SHALL prompt at DISCOVER (project_setup + interview) and
at ARCH_REVIEW (approve/reject); approval SHALL advance to BUILD and rejection
SHALL loop back to PLAN carrying the reviewer's feedback.

#### Scenario: Approve at ARCH_REVIEW
- **WHEN** the reviewer approves the architecture at ARCH_REVIEW
- **THEN** the workflow advances to BUILD

### Requirement: ACHG safety interlock
When any ACHG board decision in the scanned ArcKit context is PENDING
(graph/achg_scanner.py has_pending_achg / pending_achg_ids), ARCH_REVIEW
auto-approval SHALL be blocked and an explicit human approve or reject SHALL be
required.

#### Scenario: PENDING ACHG blocks auto-approve
- **WHEN** auto-approve reaches ARCH_REVIEW and scan_achg_context reports a
  PENDING ACHG board decision
- **THEN** the gate pauses for an explicit human decision instead of
  auto-advancing

### Requirement: ArcKit auto-ingestion
When valid ArcKit artefacts (ADMP/REQ/STKE/OAAL/PRIN) are present in the
context folder, DISCOVER SHALL auto-populate setup and interview answers and
skip their interrupts (EYW-171).

#### Scenario: Valid ArcKit context
- **WHEN** DISCOVER runs with a valid ArcKit artefact set
- **THEN** the setup and interview HIL pauses are skipped and answers come
  from the artefacts

#### Scenario: Unrecognised status is PENDING
- **WHEN** an ACHG board status is unrecognised
- **THEN** it is normalised to PENDING and the interlock applies
