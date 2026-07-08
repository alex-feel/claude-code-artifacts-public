# Claude Code Artifacts

<p align="center">
  <img src=".github/images/banner.png" alt="A public library of reusable Claude Code artifacts — skills, hooks, rules, environment configurations, agents, and slash commands — ready to drop into any Claude Code setup." width="100%">
</p>

[![License: MIT](https://img.shields.io/github/license/alex-feel/claude-code-artifacts-public)](LICENSE) [![Validate Configs](https://github.com/alex-feel/claude-code-artifacts-public/actions/workflows/validate-configs.yml/badge.svg)](https://github.com/alex-feel/claude-code-artifacts-public/actions/workflows/validate-configs.yml) [![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/alex-feel/claude-code-artifacts-public)

A public library of reusable Claude Code artifacts — skills, hooks, rules, environment configurations, agents, and slash commands — ready to drop into any Claude Code setup.

Each artifact is a self-contained building block for [Claude Code](https://docs.claude.com/en/docs/claude-code/overview). You can consume it two ways: reference it from a single environment YAML file and let the [Claude Code Toolbox](https://github.com/alex-feel/claude-code-toolbox) install it for you (by raw URL or a shared `base-url`), or copy a rule, a hook, or a skill straight into your `~/.claude/` directory.

The sections below are a catalog of what is available today, grouped by artifact type. Each entry links to the artifact itself and to that type's README for conventions and installation details.

## Skills

[Agent Skills](https://docs.claude.com/en/docs/claude-code/skills) are multi-file packages that extend Claude Code with specialized, progressively disclosed capabilities. They live under [`skills/library/`](skills/library/); see [`skills/README.md`](skills/README.md) for the layout, conventions, and the two ways to install one.

### `dynamic-workflow-patterns`

Pattern taxonomy and orchestration discipline for Claude Code dynamic workflows: which of the six workflow patterns fits a task, which agent roles to combine for each task family, which model to route to each role, and how to keep a run alive through server errors (for example HTTP 529), recover interrupted runs, and honor token budgets. Load it before authoring or running a Workflow script rather than hand-rolling one from memory. See [`skills/library/dynamic-workflow-patterns/SKILL.md`](skills/library/dynamic-workflow-patterns/SKILL.md).

## Hooks

[Hooks](https://docs.claude.com/en/docs/claude-code/hooks) run custom logic at Claude Code lifecycle events such as `PreToolUse`, `PostToolUse`, `UserPromptSubmit`, and `SessionStart`. Scripts live under [`hooks/library/`](hooks/library/); see [`hooks/README.md`](hooks/README.md) for conventions and how to wire a hook to an event.

### `idle_notification.py`

Sends a desktop notification when Claude Code goes idle — waiting for your input after roughly 60 seconds of inactivity — so you can step away and be pulled back when Claude needs you. Wires to the `Notification` event with the `idle_prompt` matcher and falls back across notification backends per platform (desktop notifier, then a platform command-line fallback). See [`hooks/library/idle_notification.py`](hooks/library/idle_notification.py).

### `status_line.py`

Renders a colored Claude Code status line from the session JSON on stdin: model name, project directory, git branch (with `main`/`master` flagged in red), session id, added and removed line counts, compact 5h/7d rate-limit usage, an update-available indicator, and an optional custom suffix. Bracketed segments appear only when enabled and present. See [`hooks/library/status_line.py`](hooks/library/status_line.py).

Both hooks read their optional YAML configuration through the shared [`hooks/library/hook_config_loader.py`](hooks/library/hook_config_loader.py) helper, so install it alongside whichever hook you use.

## Using an artifact

Every artifact is a plain file addressable by its raw URL:

```text
https://raw.githubusercontent.com/alex-feel/claude-code-artifacts-public/main/<path>
```

The [Claude Code Toolbox](https://github.com/alex-feel/claude-code-toolbox) installs artifacts from a single environment YAML file. For example, wiring the idle-notification hook to the `Notification` event:

```yaml
hooks:
  files:
    - "https://raw.githubusercontent.com/alex-feel/claude-code-artifacts-public/main/hooks/library/idle_notification.py"
    - "https://raw.githubusercontent.com/alex-feel/claude-code-artifacts-public/main/hooks/library/hook_config_loader.py"
  events:
    - event: "Notification"
      matcher: "idle_prompt"
      type: "command"
      command: "idle_notification.py"
```

Skills install through the toolbox `skills` key or the `skills` CLI; each type's README shows the exact shape. See the toolbox [Environment Configuration Guide](https://github.com/alex-feel/claude-code-toolbox/blob/main/docs/environment-configuration-guide.md) for the full YAML reference (skills, hooks, MCP servers, settings, inheritance, and more).

## Adding a new artifact

Read [CONTRIBUTING.md](CONTRIBUTING.md) for the full workflow. In short: place the artifact under the matching `<type>/library/` directory following that type's README, update this README's catalog (see [CLAUDE.md](CLAUDE.md)), run the quality gate locally (`uv run pre-commit run --all-files`), and open a pull request. Environment configurations are additionally schema-validated in CI.

## Security

Please report vulnerabilities privately through [GitHub Security Advisories](https://github.com/alex-feel/claude-code-artifacts-public/security/advisories/new). See [SECURITY.md](SECURITY.md). Because artifacts can include executable hooks and setup commands, always review an artifact before installing it.

## License

Released under the [MIT License](LICENSE).
