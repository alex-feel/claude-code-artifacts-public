# Claude Code Artifacts

[![License: MIT](https://img.shields.io/github/license/alex-feel/claude-code-artifacts-public)](LICENSE) [![Validate Configs](https://github.com/alex-feel/claude-code-artifacts-public/actions/workflows/validate-configs.yml/badge.svg)](https://github.com/alex-feel/claude-code-artifacts-public/actions/workflows/validate-configs.yml) [![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/alex-feel/claude-code-artifacts-public)

A public library of reusable Claude Code artifacts — skills, hooks, rules, environment configurations, agents, and slash commands — ready to drop into any Claude Code setup.

## Overview

Each artifact here is a self-contained building block for [Claude Code](https://docs.claude.com/en/docs/claude-code/overview). Artifacts are consumed declaratively by the [Claude Code Toolbox](https://github.com/alex-feel/claude-code-toolbox) environment configuration system: you reference an artifact from a single environment YAML file (by raw URL or a shared `base-url`) and the toolbox installs it for you. Artifacts are also usable on their own — copy a rule, a hook, or a skill straight into your `~/.claude/` directory.

## Repository structure

```text
.
├── agents/library/            # subagent definitions (*.md)
├── skills/library/            # skills (<skill-name>/SKILL.md + supporting files)
├── hooks/
│   ├── library/               # hook scripts (*.py)
│   └── configs/               # hook configuration files (*.yaml)
├── rules/library/             # rule files (*.md)
├── slash-commands/library/    # slash command definitions (*.md)
├── environments/
│   ├── library/               # ready-to-use environment configs (*.yaml)
│   └── templates/             # environment templates with placeholders (*.yaml)
└── .github/                   # CI, issue forms, and the config validation model
```

Every artifact type carries its own short README describing the layout and conventions: [skills](skills/README.md), [hooks](hooks/README.md), [rules](rules/README.md), [environments](environments/README.md), [agents](agents/README.md), [slash commands](slash-commands/README.md).

## Using an artifact

Reference any file by its raw URL:

```text
https://raw.githubusercontent.com/alex-feel/claude-code-artifacts-public/main/<path>
```

For example, an environment YAML consumed by the toolbox might pull a rule and a subagent from here:

```yaml
name: "My Environment"

base-url: "https://raw.githubusercontent.com/alex-feel/claude-code-artifacts-public/main"

agents:
  - "agents/library/my-agent.md"

rules:
  - "rules/library/my-rule.md"
```

See the toolbox [Environment Configuration Guide](https://github.com/alex-feel/claude-code-toolbox/blob/main/docs/environment-configuration-guide.md) for the full YAML reference (skills, hooks, MCP servers, settings, inheritance, and more).

## Adding a new artifact

Read [CONTRIBUTING.md](CONTRIBUTING.md) for the full workflow. In short: place the artifact under the matching `<type>/library/` directory following that type's README, run the quality gate locally (`uv run pre-commit run --all-files`), and open a pull request. Environment configurations are additionally schema-validated in CI.

## Security

Please report vulnerabilities privately through [GitHub Security Advisories](https://github.com/alex-feel/claude-code-artifacts-public/security/advisories/new). See [SECURITY.md](SECURITY.md). Because artifacts can include executable hooks and setup commands, always review an artifact before installing it.

## License

Released under the [MIT License](LICENSE).
