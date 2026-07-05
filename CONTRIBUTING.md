# Contributing

Thanks for helping grow the Claude Code Artifacts library. This guide covers how to add an artifact, the conventions each type follows, and the quality gate your change must pass.

## Ways to contribute

Add a new artifact under the matching `<type>/library/` directory following that type's README, run the quality gate, and open a pull request. Every artifact here is maintained through pull requests.

## Where each artifact goes

Follow the README inside each type directory for the exact layout and naming:

| Type | Location | Read first |
| ---- | -------- | ---------- |
| Skill | `skills/library/<skill-name>/SKILL.md` | [skills/README.md](skills/README.md) |
| Hook | `hooks/library/*.py` (+ `hooks/configs/*.yaml`) | [hooks/README.md](hooks/README.md) |
| Rule | `rules/library/*.md` | [rules/README.md](rules/README.md) |
| Environment configuration | `environments/library/*.yaml` (+ `environments/templates/`) | [environments/README.md](environments/README.md) |
| Agent | `agents/library/*.md` | [agents/README.md](agents/README.md) |
| Slash command | `slash-commands/library/*.md` | [slash-commands/README.md](slash-commands/README.md) |

## Local setup

This repository uses [uv](https://docs.astral.sh/uv/) for dependency management and [pre-commit](https://pre-commit.com/) for the quality gate.

```bash
uv sync
uv run pre-commit install
```

## Quality gate

Run the full gate before opening a pull request:

```bash
uv run pre-commit run --all-files
```

This runs Ruff, Mypy, Pyright, and ty on Python hooks, Markdown linting, XML-tag validation on skill and agent Markdown, JSON/YAML syntax checks, and lock-file freshness.

For environment configurations, validate against the schema (this also runs in CI on pull requests):

```bash
uv run python .github/validate_configs.py environments/library --strict
```

## Commits and pull requests

- This repository uses [Conventional Commits](https://www.conventionalcommits.org/) (enforced by commitizen). Example: `feat: add code-review skill`.
- Keep each pull request focused on one artifact or one coherent change.
- Never include secrets. Review your artifact's runtime behavior — hooks and environment configurations execute on a user's machine.
