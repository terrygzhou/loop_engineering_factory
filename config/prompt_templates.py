"""Prompt templates for skill prompts.

These are the default prompt bodies used by the pipeline.  They can be
rewritten by REFLECT's ``apply_prompt_diff`` (structured diffs,
Decision 4 — see ``feedback/diff_engine.py``).  Each template is a
module-level string constant assigned with a triple-quoted literal.

To add a new template, follow the same pattern: a bare name followed by
a triple-quoted string.  The ``apply_prompt_diff`` regex is quote-aware
and handles values containing double-quote characters.
"""

interview_me = """\
Ask the user about the project goals, scope, and target audience.
Follow up on the data model and API surface.
Do not invent requirements — only record what the user says."""

spec_generation = """\
Write a markdown specification.
Section: "Use cases" — list them one per bullet.
End with an acceptance-test block."""

api_and_interface_design = """\
Design the API interfaces based on the specification.
For each endpoint, define:
- HTTP method, path, request schema, response schema
- Error codes and retry semantics
Document every endpoint in a single markdown table."""
