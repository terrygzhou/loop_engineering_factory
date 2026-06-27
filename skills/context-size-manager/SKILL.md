---
name: context-size-manager
description: Track and manage context window usage throughout the workflow. Enforce limits, warn on headroom depletion, and trigger compression before LLM calls.
triggers:
  - context-size
  - context-manager
  - window-size
  - token-budget
  - headroom
version: "1.0.0"
---

# Context Size Manager

## Purpose

Track context window usage throughout the workflow and enforce limits before LLM invocation.

## Process

1. Estimate token count for all accumulated context
2. Check headroom against model's max context window
3. Trigger compression if headroom falls below 20% reserve
4. Apply pruning to remove low-signal content
5. Report final context size and headroom percentage
6. Abort if compression still exceeds limits (fail fast)

## Estimates

- ~4 chars per token for prose
- ~3.5 chars per token for code
- System prompt overhead: ~200 tokens
- Reserve 20% for response

## Rules

- Always check headroom before LLM call
- Compress progressively — don't truncate abruptly
- Preserve task context at all costs
- Report when compression ratio exceeds 50% (context too large)
- Fail fast if total context exceeds model limits after compression
