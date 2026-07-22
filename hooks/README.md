# Hooks

[Hooks](https://docs.claude.com/en/docs/claude-code/hooks) run custom logic at Claude Code lifecycle events (for example `PreToolUse`, `PostToolUse`, `UserPromptSubmit`, `SessionStart`).

## Layout

```text
hooks/
├── library/           # hook scripts and the shared helper modules they load (*.py)
└── configs/
    └── universal/     # hook configuration files (*.yaml) consumed by command hooks
```

## Conventions

- Hook scripts are Python and live in `hooks/library/`. They are statically checked by Ruff, Mypy, Pyright, and ty via pre-commit, so keep them fully type-annotated.
- Shared helper modules (`hook_config_loader.py`, `hook_json_output.py`) live beside the hook scripts in `hooks/library/` and are loaded at runtime from the hook script's own directory, so they must be installed as siblings of the script (in `~/.claude/hooks/`).
- A script that reads a companion configuration file expects that file under `hooks/configs/universal/`, referenced from the hook event's `config` field.
- Read a hook's JSON event payload from stdin and emit hook output on stdout per the official hooks specification.

## Consuming a hook

Referenced from a toolbox environment YAML via the `hooks` key. Command hooks list their script (and optional config) in `hooks.files`, then wire it to an event in `hooks.events`. Every `hooks.files` entry must be referenced by a hook event (its `command` or `config` field); shared helper modules are not referenced by events, so deliver them through `files-to-download` instead:

```yaml
files-to-download:
  - source: "https://raw.githubusercontent.com/alex-feel/claude-code-artifacts-public/main/hooks/library/hook_config_loader.py"
    dest: "~/.claude/hooks/hook_config_loader.py"

hooks:
  files:
    - "https://raw.githubusercontent.com/alex-feel/claude-code-artifacts-public/main/hooks/library/my_hook.py"
    - "https://raw.githubusercontent.com/alex-feel/claude-code-artifacts-public/main/hooks/configs/universal/my_hook_config.yaml"
  events:
    - event: "PreToolUse"
      matcher: "Bash"
      type: "command"
      command: "my_hook.py"
      config: "my_hook_config.yaml"
```

The toolbox also supports `http`, `prompt`, and `agent` hook types (no script file). See the toolbox [Environment Configuration Guide](https://github.com/alex-feel/claude-code-toolbox/blob/main/docs/environment-configuration-guide.md).
