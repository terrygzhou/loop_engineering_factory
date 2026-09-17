# pattern-memory (delta)

## MODIFIED Requirements

### Requirement: Structured REFLECT diffs (Decision 4)
REFLECT SHALL express prompt-template changes as structured diffs
`{section: <template_name>, key: "template_body", op: "replace",
value: <new text>}` — the same shape already used for config diffs —
never as free LLM text spliced verbatim into source.

`feedback/diff_engine.py:apply_prompt_diff` SHALL:
- locate the target template with a quote-aware match (the existing
  triple-quoted body, even when it contains `"` characters),
- build the replacement by escaping the value (triple-quote-safe),
- validate the candidate file with `compile()` BEFORE writing to disk —
  a non-compiling replacement leaves the original file untouched,
- keep the legacy `diffs["changes"]` list input shape accepted
  (each `change` is routed through the structured path; backward
  compatible with existing REFLECT call sites).

#### Scenario: Prompt diff containing quotes applies safely
- **WHEN** a structured diff's `value` contains `"` characters and
  newlines
- **THEN** the template in `config/prompt_templates.py` is rewritten
  with the escaped value and the file still compiles

#### Scenario: Bad replacement is rejected
- **WHEN** the composed replacement does not compile
- **THEN** `apply_prompt_diff` returns False, logs the rejection, and
  `config/prompt_templates.py` is byte-identical to before the call
