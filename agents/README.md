# Agents

Agents (subagents) are specialized assistants Claude Code can delegate to — for code review, research, debugging, or any focused workflow. Each is defined by a single Markdown file with YAML frontmatter.

## Layout

```text
agents/library/
└── <agent-name>.md
```

## Conventions

- One agent per file, named in kebab-case.
- Start the file with YAML frontmatter describing the agent — typically `name`, `description`, optional `tools`, and optional `model` — followed by the agent's system prompt in Markdown.
- Write a precise `description`: it is what the main agent uses to decide when to delegate.
- Semantic XML-style tags in the prompt must be balanced — checked by the `validate-xml-tags` pre-commit hook.

## Consuming an agent

Referenced from a toolbox environment YAML via the `agents` key; each listed file is placed in `~/.claude/agents/`:

```yaml
agents:
  - "https://raw.githubusercontent.com/alex-feel/claude-code-artifacts-public/main/agents/library/my-agent.md"
```

See the toolbox [Environment Configuration Guide](https://github.com/alex-feel/claude-code-toolbox/blob/main/docs/environment-configuration-guide.md).
