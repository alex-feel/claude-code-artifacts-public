# Environment configurations

An environment configuration is a single YAML file that declares a complete Claude Code setup — agents, skills, rules, hooks, slash commands, MCP servers, settings, dependencies, and more — installed in one command by the [Claude Code Toolbox](https://github.com/alex-feel/claude-code-toolbox).

## Layout

```text
environments/
├── library/       # ready-to-use configurations (*.yaml), fully valid
└── templates/     # starting points with placeholder values (*.yaml)
```

## Conventions

- `library/` holds configurations that must be fully valid — they are schema-validated in CI on every pull request.
- `templates/` holds scaffolds with placeholders (for example `<your-base-url>`); these are intentionally excluded from strict validation.
- The schema is defined by `.github/environment_config.py`, which is synced from `claude-code-toolbox`. Do not edit that file here.

## Validating locally

```bash
uv run python .github/validate_configs.py environments/library --strict
```

## Consuming a configuration

Point the toolbox `setup-environment` command at a configuration's raw URL, or list the configuration under another config's `inherit` key to compose it. See the toolbox [Environment Configuration Guide](https://github.com/alex-feel/claude-code-toolbox/blob/main/docs/environment-configuration-guide.md) for the full YAML reference.
