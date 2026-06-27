---
name: context-pruning
description: Remove low-signal content from context before LLM calls. Prioritize high-value context and prune verbose or redundant information.
triggers:
  - prune
  - context-pruning
  - context-filter
  - low-signal
  - context-reduce
version: "1.0.0"
---

# Context Pruning

## Purpose

Prune low-signal content from context windows to improve LLM focus and reduce token waste.

## Process

1. Score each context block by relevance (spec > code > logs > debug)
2. Keep high-scoring blocks intact
3. Compress medium-scoring blocks to essential content
4. Drop low-scoring blocks entirely
5. Verify total fits within available headroom
6. Report what was pruned and why

## Priority Order

1. Spec and requirements (highest)
2. Code and implementation details
3. Error messages and stack traces
4. Log output and debug info
5. Conversation history (lowest — summarize to key decisions)

## Rules

- Never prune the primary task or goal
- Preserve error details that affect the current task
- Summarize long logs to first/last entries with counts
- Drop duplicate or near-duplicate content
- Report pruning decisions for auditability
