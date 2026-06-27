---
name: headroom-context-compression
description: Compress tool outputs, logs, RAG chunks, and conversation context to fit within LLM context windows. Calculate headroom, truncate proportionally, and maintain high-signal content.
triggers:
  - headroom
  - compress
  - context-compression
  - truncate
  - context-size
version: "1.0.0"
---

# Headroom Context Compression

## Purpose

Manage context window headroom by compressing tool outputs, logs, RAG chunks, and conversation context to fit within LLM limits.

## Process

1. Calculate current context token usage
2. Determine available headroom (max_tokens - current_tokens - reserve)
3. Compress content proportionally — truncate from ends of each chunk
4. Preserve high-signal content: first/last N chars of each chunk
5. Report compression ratio and remaining headroom
6. If still over limit, apply more aggressive truncation

## Rules

- Reserve 20% of context window for LLM response
- Compress proportionally across all chunks
- Preserve first 200 and last 200 chars of each chunk
- Report compressed size and remaining headroom
- Never drop entire chunks if partial preservation is possible
