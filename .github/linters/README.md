# Super-Linter config files

These files are picked up by the `super-linter` GitHub Action
(`.github/workflows/super-linter.yml`) via `LINTER_RULES_PATH=.github/linters`.
Edit the files here to override the linters' built-in defaults without
touching the workflow.

| File | Linter | What it does |
|------|--------|--------------|
| `.markdown-lint.yml` | `markdownlint` (MARKDOWN) | Permissive rules for the 35 SKILL.md + docs files |
| `.hadolint.yaml` | Hadolint (DOCKERFILE_HADOLINT) | Ignores DL3008/DL3015/DL3013/DL4006/DS-0002/DS-0026/SC2086 (see in-file comments) |
| `.shellcheckrc` | ShellCheck (BASH) | No extra flags; default severity |

## Adding a new linter

1. Pick a `VALIDATE_<TOOL>` identifier from the [super-linter docs](https://github.com/super-linter/super-linter).
2. Set `VALIDATE_<TOOL>: "true"` in the `env:` block of `.github/workflows/super-linter.yml`.
   Super-linter v8 dropped the v7 `ENABLE` comma-list: every linter the
   workflow does not explicitly toggle is auto-defaulted to `false`, so
   adding one `VALIDATE_*=true` line is enough to enable a new linter
   without disabling anything else.
3. If the linter needs a config file, drop it in this directory and
   point `<TOOL>_CONFIG_FILE` at it in the workflow if the default
   name is not what you want.

## Status (checked 2026-09-17)

All 4 `VALIDATE_*` linters pass on the current tree after formatting the 4
YAML files flagged by Prettier (`config/guardrails.yaml`,
`config/bounds.yaml`, `docker-compose.yml`,
`observability/promtail/promtail-config.yaml`). The local validation
was done with:

```
docker run --rm \
  -e RUN_LOCAL=true -e VALIDATE_ALL_CODE_BASE=true \
  -e IGNORE_GITIGNORED_FILES=true -e IGNORE_GENERATED_FILES=true \
  -e LINTER_RULES_PATH=.github/linters \
  -e VALIDATE_MARKDOWN=true \
  -e VALIDATE_DOCKERFILE_HADOLINT=true \
  -e VALIDATE_BASH=true \
  -e VALIDATE_YAML_PRETTIER=true \
  -v "$PWD":/tmp/lint -w /tmp/lint \
  ghcr.io/super-linter/super-linter:latest
```

If a future linter addition flips the gate red on a push, the
`super-linter-log` artifact uploaded by the workflow has the full
per-linter output.
