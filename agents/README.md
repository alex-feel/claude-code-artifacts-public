# Claude Code Subagents

This directory contains example subagents for Claude Code.

## What are Subagents?

Subagents are specialized AI assistants that operate in isolated contexts within Claude Code. They are Markdown files with YAML frontmatter that define custom prompts, tool permissions, thinking modes, and invocation patterns. Each agent is designed for specific tasks and can be invoked proactively or on-demand based on defined triggers.

## Using These Subagents

### Option 1: Project-level (Recommended for teams)

Copy subagents to your project:

```bash
# Create .claude/agents directory in your project
mkdir -p .claude/agents

# Copy desired subagents
cp agents/library/code-reviewer.md .claude/agents/
cp agents/library/test-generator.md .claude/agents/
```

### Option 2: User-level (Personal use)

Install subagents for all projects:

```bash
# Windows
mkdir -p %USERPROFILE%\.claude\agents
copy agents\library\*.md %USERPROFILE%\.claude\agents\

# Unix/Mac
mkdir -p ~/.claude/agents
cp agents/library/*.md ~/.claude/agents/
```

## Sub-agent Format

Subagents are Markdown files with three parts:

1. **YAML Frontmatter**: Metadata
   - `name`: Identifier for the sub-agent (kebab-case)
   - `description`: Multi-line description (3-4 sentences):
     - First 2-3 sentences describe capabilities
     - **CRITICAL**: Last sentence MUST contain either "It should be used proactively" with specific triggers
   - `tools`: Comma-separated tool list (start with no-permission tools, add others as needed)
     - MCP server shortcuts supported (e.g., `mcp__context7` for all Context7 tools)
     - **IMPORTANT**: If using Write, must also include Edit and MultiEdit
   - `model`: Optional model preference (opus, sonnet, haiku) - most agents use opus
   - `color`: Optional agent color (red, blue, green, yellow, purple, orange, pink, cyan)

2. **System Prompt**: Markdown content with:
   - Mission statement
   - Cognitive framework with thinking mode (Think, Think more, Think a lot, Think longer, Ultrathink)
   - Operating rules and constraints
   - Execution workflow
   - Concurrent execution patterns (CRITICAL)
   - Error handling protocol
   - Quality metrics

3. **File Extension**: Must be `.md`

## Best Practices

1. **Single Responsibility**: Each sub-agent should focus on one domain
2. **Clear Invocation Triggers**: Last sentence of description MUST specify "It should be used proactively" with specific conditions
3. **Appropriate Tools**: Start with no-permission tools, add others only as needed
4. **Thinking Modes**: Choose appropriate cognitive depth (Think, Think more, Think a lot, Think longer, Ultrathink)
5. **Concurrent Execution**: ALWAYS batch related operations in single messages for performance
6. **Detailed Prompts**: Include mission statement, workflows, and quality metrics
7. **Version Control**: Commit project subagents to your repository

## Tool Permissions

Common tool configurations used by actual agents:

- **Analysis-only** (code-reviewer): `Glob, Grep, LS, Read, NotebookRead, Task, TodoWrite, BashOutput`
- **Content creation** (doc-writer): `Glob, Grep, LS, Read, NotebookRead, Task, TodoWrite, BashOutput, Write, Edit, MultiEdit, WebFetch, WebSearch`
- **Full development** (test-generator, refactoring): `Glob, Grep, LS, Read, NotebookRead, Task, TodoWrite, BashOutput, Write, Edit, MultiEdit, Bash`
- **Research-focused** (implementation-guide): Includes `mcp__context7__resolve-library-id, mcp__context7__get-library-docs` for library documentation access

**CRITICAL**: Always start with no-permission tools (Glob, Grep, LS, Read, NotebookRead, Task, TodoWrite, BashOutput), then add others as needed.

### MCP Server Tools

When using MCP (Model Context Protocol) tools, you can specify either individual tools or entire servers:

- **Individual MCP tools**: `mcp__serverName__toolName` (e.g., `mcp__context7__get-library-docs`)
- **All tools from MCP server**: `mcp__serverName` (e.g., `mcp__context7`)

Example allowing all Context7 tools:
```yaml
tools: Glob, Grep, LS, Read, NotebookRead, mcp__context7__resolve-library-id, mcp__context7__get-library-docs
```

This is equivalent to listing all Context7 tools individually but is more concise and maintainable.

## Documentation

For detailed documentation on creating and using subagents, see:
- [Official Claude Code Subagents Documentation](https://docs.anthropic.com/en/docs/claude-code/sub-agents)
