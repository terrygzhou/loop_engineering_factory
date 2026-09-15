# llm-invocation

## Purpose
A single typed LLM invocation path (tools/llm.py) with bounded retries and
fail-fast error propagation.

## Requirements

### Requirement: Typed LLM errors
LLM failures SHALL surface as LLMError (fatal) or _LLMTimeout (retryable);
invoke_skill / invoke_skill_async SHALL return None on fatal failure — never
a sentinel string.

#### Scenario: Fatal error
- **WHEN** the LLM returns a non-retryable error (401/403/404/
  model-not-found)
- **THEN** invoke_skill returns None and callers must handle None

#### Scenario: Transient error retries
- **WHEN** the LLM returns a 5xx or timeout
- **THEN** the call retries with bounded exponential backoff (base 1.0s, cap
  15s, max 2 retries) before raising LLMError

### Requirement: All LLM traffic through tools/llm.py
Nodes SHALL invoke LLM skills only via invoke_skill / invoke_skill_async
(tools/llm.py); direct ChatOpenAI construction in nodes SHALL NOT occur.
Parallel calls SHALL use asyncio.gather (DEFINE source-driven + api-design;
PLAN four diagram calls).

#### Scenario: No LLM configured
- **WHEN** no LLM endpoint is configured (dry-run mode)
- **THEN** invoke_skill returns a "[DRY-RUN] …" string and the pipeline
  continues without real generation
