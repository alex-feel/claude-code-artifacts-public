# Claude Code Environment Configurations

This directory contains YAML configuration files that define complete environments for Claude Code. Each configuration can install dependencies, configure agents, set up MCP servers, add slash commands, and more.

## Installation and Usage

For instructions on how to install and use these environment configurations, please visit the **[Claude Code Toolbox](https://github.com/alex-feel/claude-code-toolbox)** repository.

The toolbox provides setup scripts and detailed instructions for:
- Installing configurations from repositories (like this one)
- Using local configuration files with sensitive data
- Loading configurations from private repositories
- Command-line options and authentication methods

## ⚠️ Security Notice

Environment configurations can execute commands and download scripts. **Only use configurations from trusted sources!**  **DO NOT trust configurations until carefully checked for all details!**

Configurations can contain:
- **API keys and secrets** for MCP servers
- **System commands** executed during installation
- **Hook scripts** that run automatically on Claude Code events
- **Remote dependencies** downloaded from the internet

## Configuration Structure

See details in [environment configurations](environments/templates/basic-template.yaml).

Each YAML file can contain:

```yaml
# REQUIRED: Display name for the environment
name: Display name for the environment

# OPTIONAL: Global command name to register (e.g., claude-myenv)
# When specified, must also include command-defaults section
command-name: claude-myenv

# OPTIONAL: Base URL override for all relative resource paths
# When set, all relative paths (agents, commands, etc.) resolve against this base
# Full URLs in resource lists still take priority over this setting
# Note: {path} placeholder is automatically appended if not present
base-url: https://raw.githubusercontent.com/my-org/my-configs/main
# Or explicitly specify where {path} should go:
# base-url: https://my-server.com/api/v2/{path}/raw

# OPTIONAL: Specific Claude Code version to install
# Use "latest" or a semantic version (e.g., "1.0.124", "2.0.0-beta.1")
# If not specified, installs the latest version
claude-code-version: "latest"  # or "1.0.124" for specific version

# OPTIONAL: Include co-authored-by attribution in commits (default: true)
include-co-authored-by: true

# OPTIONAL: Platform-specific dependency commands
dependencies:
    # Commands that run on all platforms
    common:
        - Command to install on all platforms
        - Another common dependency
    # Windows-specific commands
    windows:
        - Windows-specific command
        - winget install Example.Tool
    # macOS-specific commands
    mac:
        - macOS-specific command
        - brew install example-tool
    # Linux-specific commands
    linux:
        - Linux-specific command
        - apt-get install example-tool

# OPTIONAL: Agent markdown files
# Paths can be URLs, absolute paths, or relative to config file
agents:
    - Path to agent file (URL, absolute path, or relative to config file)

# OPTIONAL: MCP server configurations
# Two mutually exclusive types: HTTP/SSE (remote) or Stdio (local)
mcp-servers:
    # HTTP/SSE server (has transport and url, NO command)
    - name: my-api-server
      scope: user  # or 'project'
      transport: http  # or 'sse'
      url: https://api.example.com/mcp
      header: "Authorization: Bearer token"  # Optional

    # Stdio server (has command, NO transport/url/header)
    - name: local-tool
      scope: project
      command: npx @modelcontextprotocol/server-everything
      env: "PATH=/custom/path:$PATH"  # Optional

# OPTIONAL: Slash command files
# Paths can be URLs, absolute paths, or relative to config file
slash-commands:
    - Path to slash command file (URL, absolute path, or relative to config file)

# OPTIONAL: Output style files
# Paths can be URLs, absolute paths, or relative to config file
output-styles:
    - Path to output style file (URL, absolute path, or relative to config file)

# OPTIONAL: Hook configurations for automatic actions
hooks:
    # Hook script files to download (listed once, used by multiple events)
    files:
        - List of hook script files (URLs, absolute paths, or relative to config file)
    # Hook event configurations
    events:
        - event: Event name (PostToolUse, Notification, etc.)
          matcher: Regex pattern to match (optional)
          type: command
          command: Command to execute

# OPTIONAL: Model configuration
# Use official aliases or custom model names
model: sonnet  # default, sonnet, opus, haiku, sonnet[1m], opusplan, or claude-*

# OPTIONAL: Environment variables for Claude Code sessions
env-variables:
    BASH_DEFAULT_TIMEOUT_MS: "5000"
    MAX_MCP_OUTPUT_TOKENS: "50000"

# OPTIONAL: Permissions configuration
permissions:
    # Default permission mode (optional)
    defaultMode: acceptEdits  # default, acceptEdits, plan, bypassPermissions
    # Explicitly allowed actions (optional)
    allow:
        - WebFetch
        - mcp__context7__resolve-library-id, mcp__context7__get-library-docs
        - mcp__deepwiki__read_wiki_structure, mcp__deepwiki__read_wiki_contents, mcp__deepwiki__ask_question
        - Bash(git diff:*)
    # Explicitly denied actions (optional)
    deny:
        - Bash(rm:*)
        - Read(.env)
    # Actions requiring confirmation (optional)
    ask:
        - Bash(git push:*)
    # Additional accessible directories (optional)
    additionalDirectories:
        - ../other-project/

# OPTIONAL: Command launch defaults (required if command-name is specified)
# These two fields are mutually exclusive
command-defaults:
    # Use complete alternative system prompt (replaces default development prompt)
    output-style: Name of output style to use (optional)
    # OR append to Claude's default development prompt
    system-prompt: Path to additional system prompt file (URL, absolute path, or relative to config file)
```

### Model Configuration

**Available model aliases:**
- `default` - Recommended model based on your account
- `sonnet` - Latest Sonnet model for daily coding tasks
- `opus` - Most capable Opus model for complex reasoning
- `haiku` - Fast and efficient model for simple tasks
- `sonnet[1m]` - Sonnet with 1 million token context window
- `opusplan` - Hybrid mode (Opus for planning, Sonnet for execution)

**Custom model names:** You can also specify custom model names that start with `claude-` (e.g., `claude-opus-4-1-20250805`).

### Permissions Configuration

Controls how Claude Code interacts with your system:

**Permission Modes:**
- `default` - Prompts for permission on first use of each tool
- `acceptEdits` - Automatically accepts file edit permissions
- `plan` - Plan Mode - analyze without modifying files
- `bypassPermissions` - Skips all permission prompts (use with caution)

**Permission Rules:**
- `allow` - Explicitly allowed actions
- `deny` - Prohibited actions
- `ask` - Actions requiring user confirmation
- `additionalDirectories` - Extra directories Claude can access

### URL Support in Configurations

Environment configurations support flexible URL resolution for all file resources (agents, slash commands, output styles, hooks, and system prompts). This allows you to:
- Load configurations from one repository while fetching resources from others
- Mix resources from multiple sources in a single configuration
- Override the default resource location with custom URLs

**Resource Path Resolution Priority:**

1. **Full URLs** (highest priority) - `https://example.com/agent.md` used as-is
2. **base-url override** - If `base-url` is set, relative paths resolve against it
3. **Config URL derivation** - If config loaded from URL, relative paths inherit that base
4. **Local paths** (lowest priority):
   - **Absolute paths**: `/home/user/agent.md`, `C:\agents\agent.md`, `~/agent.md`
   - **Relative paths**: Resolved relative to **config file location**, not repo root

**Path Resolution Examples:**

```yaml
# Example 1: Full URLs (always used as-is)
agents:
    - https://raw.githubusercontent.com/org/repo/main/agents/agent.md
    - https://gitlab.com/api/v4/projects/123/repository/files/agents%2Fagent.md/raw?ref=main

# Example 2: base-url override (all relative paths use this base)
base-url: https://raw.githubusercontent.com/my-org/my-configs/main
# Note: {path} placeholder is automatically added if not present
agents:
    - agents/my-agent.md  # → https://raw.githubusercontent.com/my-org/my-configs/main/agents/my-agent.md
    - https://example.com/special.md  # Full URL still takes priority

# Example 3: Config loaded from URL (relative paths inherit base)
# If config loaded from: https://example.com/configs/env.yaml
# Then: agents/my-agent.md → https://example.com/agents/my-agent.md

# Example 4: Local paths when using local config file
# Config at: /home/user/myproject/config.yaml
agents:
    - agents/local-agent.md      # → /home/user/myproject/agents/local-agent.md
    - ../shared/agent.md         # → /home/user/shared/agent.md
    - /tmp/global-agent.md       # → /tmp/global-agent.md (absolute)
    - ~/personal-agent.md        # → /home/user/personal-agent.md (home expansion)

# Example 5: Mixed sources in one config
agents:
    - agents/local.md                    # Resolved based on priority
    - /absolute/path/to/agent.md         # Local absolute path
    - https://remote.com/agent.md        # Remote URL
    - ~/Documents/agents/personal.md     # Home directory expansion
```

**Authentication:** When fetching from private repositories, the same authentication methods (environment variables or command-line parameters) are used for all resources, regardless of their source. See the [Claude Code Toolbox](https://github.com/alex-feel/claude-code-toolbox) for detailed authentication instructions.

## Creating Custom Configurations

1. Create a new YAML file in
2. Define your environment using the structure above
3. Use the [Claude Code Toolbox](https://github.com/alex-feel/claude-code-toolbox) setup scripts to install your configuration
4. Your custom command will be registered globally

**Security Best Practices:**
- Store local configs in a secure location
- Add `*.local.yaml` or `*-private.yaml` to `.gitignore`
- Never commit files containing API keys or secrets
- Use environment variables for extra sensitive data
- Share config templates without actual keys

## Features

### Dependencies
Install any command-line tools or packages needed for your environment.

### Agents
Include specialized subagents for different tasks (code review, testing, documentation, etc.).

### MCP Servers
Configure Model Context Protocol servers. There are **TWO MUTUALLY EXCLUSIVE** types:

**HTTP/SSE Servers** (remote web-based):
- Use `transport: http` or `transport: sse`
- Require `url` field
- Optional `header` for authentication
- **Cannot** have `command` or `env` fields

**Stdio Servers** (local command-based):
- Use `command` field to specify executable
- Optional `env` for environment variables
- **Cannot** have `transport`, `url`, or `header` fields

These configuration types are completely separate - you cannot mix fields from both types in one server definition.

### Slash Commands
Add custom slash commands for common tasks like `/commit`, `/test`, `/refactor`.

### Output Styles
Configure how Claude formats its responses.

### Hooks
Set up automatic actions triggered by events:
- Linting on file changes
- Notifications for long-running tasks
- Custom scripts for specific file types

### Command Defaults
Configure how Claude starts in your environment:
- **output-style**: Use a complete alternative system prompt (e.g., for non-development roles like business analysis)
- **system-prompt**: Append additional context to Claude's default development prompt

**CRITICAL REQUIREMENTS**:
- `output-style` and `system-prompt` are **mutually exclusive** - you can only use one or the other, not both
- **Both** `command-name` and `command-defaults` must be present together or both omitted - you cannot have one without the other
- If you specify `command-name`, you MUST also specify `command-defaults` (and vice versa)

## Notes

- Configurations are downloaded from the repo at setup time
- All files are placed in `~/.claude/` directory
- Files are automatically overwritten by default (to preserve latest versions)
