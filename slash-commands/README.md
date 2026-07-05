# Slash commands

[Slash commands](https://docs.claude.com/en/docs/claude-code/slash-commands) are reusable prompts invoked as `/command-name`. Each is defined by a single Markdown file.

## Layout

```text
slash-commands/library/
└── <command-name>.md
```

## Conventions

- One command per file; the file name (kebab-case) becomes the command name.
- Optional YAML frontmatter can set fields such as `description`, `argument-hint`, `allowed-tools`, and `model`; the Markdown body is the prompt.
- Reference command arguments with `$ARGUMENTS` (or `$1`, `$2`, …) in the body.

## Consuming a slash command

Referenced from a toolbox environment YAML via the `slash-commands` key; each listed file is placed in `~/.claude/commands/`:

```yaml
slash-commands:
  - "https://raw.githubusercontent.com/alex-feel/claude-code-artifacts-public/main/slash-commands/library/my-command.md"
```

See the toolbox [Environment Configuration Guide](https://github.com/alex-feel/claude-code-toolbox/blob/main/docs/environment-configuration-guide.md).
