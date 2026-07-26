---
name: fabric-prompts
description: >
  Use Fabric (danielmiessler/fabric) for prompt optimization, auditing, and comparison.
  Fabric is installed at ~/.local/bin/fabric with 254+ built-in patterns and 3 custom
  prompt engineering patterns: prompt_optimizer, prompt_audit, prompt_compare.
---

# Fabric Prompt Engineering

Fabric is installed on this system and configured with Anthropic (DeepSeek Anthropic-compatible) as the backend. It provides 254+ built-in patterns and 3 custom prompt engineering patterns.

## Quick Reference

| Pattern | Purpose | Command |
|---------|---------|---------|
| `prompt_optimizer` | Transform a draft prompt into a production-grade prompt | `echo "prompt" \| fabric -p prompt_optimizer -m anthropic/claude-sonnet-4-5` |
| `prompt_audit` | Score and critique a prompt's quality (1-5 per criterion) | `echo "prompt" \| fabric -p prompt_audit -m anthropic/claude-sonnet-4-5` |
| `prompt_compare` | Compare two prompts and produce a best-of-both hybrid | `echo -e "## PROMPT A\n...\n\n## PROMPT B\n..." \| fabric -p prompt_compare -m anthropic/claude-sonnet-4-5` |
| `improve_prompt` | (Built-in) OpenAI-style prompt improvement | `echo "prompt" \| fabric -p improve_prompt -m anthropic/claude-sonnet-4-5` |
| `summarize_prompt` | (Built-in) Summarize what a prompt does | `echo "prompt" \| fabric -p summarize_prompt -m anthropic/claude-sonnet-4-5` |
| `greybeard_secure_prompt_engineer` | (Built-in) Security-hardened prompt generation | `echo "prompt" \| fabric -p greybeard_secure_prompt_engineer -m anthropic/claude-sonnet-4-5` |

## Usage Workflow

### Optimize a Prompt

```bash
echo "Your draft prompt here" | fabric -p prompt_optimizer -m anthropic/claude-sonnet-4-5
```

The optimizer produces a complete Markdown prompt with:
- **IDENTITY and PURPOSE** — Expert role assignment
- **INPUT** — What the AI receives
- **INSTRUCTIONS** — Numbered steps
- **OUTPUT FORMAT** — Structure, length, style constraints
- **SAFETY GUARDS** — Injection protection and edge cases

### Audit a Prompt

```bash
echo "Your prompt to review" | fabric -p prompt_audit -m anthropic/claude-sonnet-4-5
```

Returns a scorecard (1-5 per criterion), strengths, critical issues, improvements ranked by priority, and red flags.

### Compare Two Prompts

```bash
printf "## PROMPT A\n%s\n\n## PROMPT B\n%s\n" "$prompt_a" "$prompt_b" | fabric -p prompt_compare -m anthropic/claude-sonnet-4-5
```

Returns a verdict, dimension-by-dimension comparison, key differences, and a recommended hybrid prompt.

## Environment

- **Binary**: `~/.local/bin/fabric` (v1.4.455)
- **Config**: `~/.config/fabric/.env`
- **Custom patterns**: `~/.config/fabric/custom_patterns/`
- **Backend**: DeepSeek Anthropic-compatible endpoint (`claude-sonnet-4-5`)
- **Models**: Use `-m anthropic/claude-sonnet-4-5` for reliable results

## Pitfalls

- **Always specify `-m anthropic/claude-sonnet-4-5`** — the default model may not be set or may use an invalid API key
- **Pipe input via `echo` or `printf`** — Fabric reads from stdin
- **Multi-line prompts** — Use `printf` or here-docs, not simple `echo` for prompts with special characters
- **prompt_compare requires `## PROMPT A` / `## PROMPT B` delimiters** — without them, the pattern can't distinguish the two inputs
- **Fabric patterns live in `~/.config/fabric/patterns/`** — do not edit these directly; use custom patterns in `~/.config/fabric/custom_patterns/` instead (survive updates)

## Updating Patterns

```bash
fabric -U          # Update built-in patterns from GitHub
fabric --listpatterns  # List all available patterns
```

## Strategies

Fabric supports prompt strategies (CoT, self-refine, etc.):
```bash
echo "prompt" | fabric -p prompt_optimizer --strategy cot -m anthropic/claude-sonnet-4-5
```

Available strategies: `cot`, `cod`, `tot`, `aot`, `ltm`, `self-consistent`, `self-refine`, `reflexion`, `standard`

List with: `fabric --liststrategies`

### Embedding ToT→CoT Directly in Prompts

When you can't call Fabric at runtime (e.g., hardcoded prompts in application code), embed the ToT→CoT pattern directly:

```markdown
## REASONING PHASE (Tree of Thought)
Generate 3 candidate approaches, evaluate each, and select the best:

- **Approach A** — [description]
- **Approach B** — [description]  
- **Approach C** — [description]

For each approach, assign a score (1-5) based on [relevant criteria]. Then state which approach you're using and why.

## EXECUTION PHASE (Chain of Thought)
Follow this sequential process:

**Step 1 — [Task]**: [Specific instruction]
**Step 2 — [Task]**: [Specific instruction]
...
```

This replicates Fabric's `--strategy tot` followed by `--strategy cot` behavior natively in any LLM prompt. The ToT phase forces exploration of alternatives before committing; the CoT phase ensures step-by-step reasoning with explicit justification at each stage. See `references/tot-cot-embedding.md` for detailed examples.

## Concise Output

Fabric's `prompt_optimizer` produces verbose output by default. To get a shorter, more focused result:

```bash
echo "Optimize this prompt but keep it 50% shorter than a standard Fabric output — be extremely concise:\n\n[your prompt here]" | fabric -p prompt_optimizer -m anthropic/claude-sonnet-4-5
```

This pre-briefs the optimizer to be concise, producing a tighter prompt in one pass. Run it twice if needed - first to get the optimized structure, then again with the concise instruction applied to the output.

## Optimize-Then-Execute

When you have a vague user prompt describing code changes, use the three-pass workflow: optimize → audit → execute yourself. See `references/optimize-then-execute.md`.

See `references/concise-optimization.md` for the full workflow.
