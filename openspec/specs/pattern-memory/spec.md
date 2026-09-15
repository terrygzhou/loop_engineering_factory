# pattern-memory

## Purpose
Self-improvement: archives each cycle's outcome to ChromaDB and proposes
structured config changes for human approval.

## Requirements

### Requirement: Pattern storage
The system SHALL store cycle records in ChromaDB (feedback/chroma_client.py:
init_collections, store_pattern) and retrieve similar past cycles via
query_patterns (top_k default 3); storage failures SHALL be graceful
(return [] / None), never aborting the pipeline.

#### Scenario: No Chroma available
- **WHEN** the ChromaDB service is unreachable
- **THEN** store_pattern and query_patterns fail gracefully and the pipeline
  continues

### Requirement: Structured config diffs
REFLECT SHALL produce structured config diffs ({section, key, op, value}
entries via feedback/diff_engine.py generate_config_diffs), validate them with
dry_run_validation before apply, and require human approval when
human_approval_required=true.

#### Scenario: Diff validation
- **WHEN** REFLECT generates config diffs
- **THEN** dry_run_validation runs them against a copy before any apply, and
  unapproved diffs are not written to config/
