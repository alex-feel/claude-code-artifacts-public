# Claude Code Output Styles

Output styles allow you to adapt Claude Code's behavior and communication style for different purposes while maintaining core capabilities like file operations, script execution, and task tracking.

## Overview

Output styles completely modify Claude Code's system prompt to change how it:
- Communicates with users
- Structures responses
- Approaches problem-solving
- Presents information

Unlike agents (which handle specific delegated tasks), output styles change Claude Code's entire personality and approach.

**Note**: Claude Code has built-in output styles (default, explanatory, learning) available via the `/output-style` command. Output styles can be created for specialized use cases and customized communication approaches beyond the default options.

## Installation and Deployment

### Installing Custom Output Styles

Custom output styles can be installed and deployed through environment configurations. For detailed instructions on setting up environments that include output styles, please visit the **[Claude Code Toolbox](https://github.com/alex-feel/claude-code-toolbox)** repository.

The toolbox provides:
- Automated setup scripts for Windows, macOS, and Linux
- Environment configuration files that bundle output styles with other components
- Support for private repositories and authentication
- Command-line tools for managing output styles

### Environment Configuration Integration

Output styles can be included in environment YAML files:
```yaml
name: My Custom Environment
command-name: claude-custom

output-styles:
    - path/to/custom-style.md
    - https://raw.githubusercontent.com/org/repo/main/styles/another-style.md

command-defaults:
    output-style: custom-style  # Set as default for this environment
```

## Key Differences from Other Features

| Feature | Purpose | Scope |
|---------|---------|-------|
| **Output Styles** | Change entire communication style | Complete system prompt replacement |
| **Agents** | Delegate specific tasks | Task-specific with tool restrictions |
| **CLAUDE.md** | Add project context | Appends to existing prompt |
| **Slash Commands** | Quick actions | Specific command execution |

## Using Output Styles

### Manual Installation

To manually install an output style:
1. Place the markdown file in `~/.claude/output-styles/` (user-level)
2. Or place it in `.claude/output-styles/` (project-level)
3. Use the `/output-style` command to activate it

### Changing Output Style

Use the `/output-style` command in Claude Code to:
1. View available styles
2. Switch to a different style
3. Create new custom styles

### Storage Locations

Output styles can be stored at two levels:

1. **User-level**: `~/.claude/output-styles/` (available across all projects)
2. **Project-level**: `.claude/output-styles/` (specific to current project)

## Creating Custom Output Styles

Create output styles using a markdown file with YAML frontmatter. Each output style requires:

1. **YAML frontmatter** with name and description
2. **System prompt** defining the new behavior
3. **Core capability preservation** (file operations, etc.)

### Example Structure

```markdown
---
name: my-custom-style
description: Brief description of what this style does
---

# System Prompt Title

You are Claude Code with [specific characteristics].

## Communication Style
[Define how to communicate]

## Problem-Solving Approach
[Define approach to tasks]

## Response Structure
[Define how to structure responses]
```

## Best Practices

1. **Preserve Core Functionality**: Always maintain file operations, script execution, and task tracking
2. **Clear Purpose**: Define a specific use case for each style
3. **Consistent Behavior**: Ensure predictable responses within the style
4. **User-Friendly**: Make the style intuitive and helpful
5. **Documentation**: Include examples of how the style changes behavior

## Documentation

For detailed documentation on creating and using output styles, see:
- [Official Claude Code Output Styles Documentation](https://docs.anthropic.com/en/docs/claude-code/output-styles)
