# Rules

Rules are Markdown files that encode standing guidance — coding standards, security policies, workflow conventions — installed into a user's `~/.claude/rules/` directory so Claude Code applies them across sessions.

## Layout

```text
rules/library/
└── <rule-name>.md
```

## Conventions

- One rule per file, named in kebab-case (for example `hugo-development.md`).
- Write the rule as clear, self-contained guidance. State the principle and how to apply it rather than enumerating brittle special cases.
- Keep prose in American English, one paragraph per physical line (Markdown line-length linting is disabled for this reason).

## Consuming a rule

Referenced from a toolbox environment YAML via the `rules` key; each listed file is placed in `~/.claude/rules/`:

```yaml
rules:
  - "https://raw.githubusercontent.com/alex-feel/claude-code-artifacts-public/main/rules/library/my-rule.md"
```

See the toolbox [Environment Configuration Guide](https://github.com/alex-feel/claude-code-toolbox/blob/main/docs/environment-configuration-guide.md).
