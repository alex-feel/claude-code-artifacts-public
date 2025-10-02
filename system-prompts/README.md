# System Prompts for Claude Code

System prompts define specialized roles and expertise that guide Claude's behavior throughout development sessions. They establish domain-specific practices, tool usage patterns, and quality standards.

## Installation and Deployment

### Installing System Prompts

System prompts can be installed and deployed through environment configurations. For detailed instructions on setting up environments that include system prompts, please visit the **[Claude Code Toolbox](https://github.com/alex-feel/claude-code-toolbox)** repository.

The toolbox provides:
- Automated setup scripts for Windows, macOS, and Linux
- Environment configuration files that bundle system prompts with other components
- Support for private repositories and authentication
- Command-line tools for managing system prompts

### Environment Configuration Integration

System prompts can be included in environment YAML files:
```yaml
name: My Custom Environment
command-name: claude-custom

command-defaults:
    system-prompt: https://raw.githubusercontent.com/org/repo/main/styles/custom-system-prompt.md  # Set as default for this environment
```

### Manual Usage

#### Using System Prompts in Interactive Mode

As of Claude Code v1.0.51, the `--append-system-prompt` flag works in interactive mode:

```bash
# Start Claude Code with a specific role
# Git Bash/Linux/macOS:
claude --append-system-prompt "$(cat system-prompts/library/<your-prompt>.md)"

# Or reference the file directly (may not work on all systems)
claude --append-system-prompt @system-prompts/library/<your-prompt>.md

# Windows (PowerShell/CMD) - use the automated setup script which creates working wrappers
```

**Windows Users**: The `$(cat file)` syntax works in Git Bash. For PowerShell and CMD, use the automated setup which creates proper wrappers.

### Using System Prompts in Non-Interactive Mode

```bash
# Execute a task with a specific system prompt
# Git Bash/Linux/macOS:
claude -p "Review this codebase for security issues" \
  --append-system-prompt "$(cat system-prompts/library/<your-prompt>.md)"

# Windows users: Use the custom command created by setup (e.g., claude-<your-role>)

# Combine with other flags
claude -p "Optimize database queries" \
  --append-system-prompt "$(cat system-prompts/library/<your-prompt>.md)" \
  --model opus \
  --max-turns 10
```

**Note**: The `@file` syntax may not work reliably. Use `$(cat file)` for better compatibility.

## Creating Custom System Prompts

### Creating From Existing Prompts

1. **Start with an existing system prompt:**
   - Choose a prompt from `system-prompts/library/` that matches your domain
   - Use it as a foundation for your custom role

2. **Copy an existing prompt:**
   ```bash
   cp system-prompts/library/<existing-prompt>.md system-prompts/library/<my-role>.md
   ```

3. **Customize the content:**
   - Update role definition and expertise areas
   - Add domain-specific requirements
   - Define subagent usage patterns
   - Specify quality standards and practices

### Key Sections to Customize

#### Role Definition
Define the agent's expertise and primary responsibilities:
```markdown
You are **Claude Code, a [Role Title]** specializing in [domain].
```

#### Core Practices
Establish mandatory workflows and standards:
```markdown
### CRITICAL: [Practice Name]
[Detailed requirements and procedures]
```

#### Subagent Integration
Define when to use specialized agents:
```markdown
#### Subagent: `agent-name`
- **Purpose** – [What this agent does]
- **Invocation trigger** – [When to use]
```

#### Domain-Specific Requirements
Add sections specific to your domain:
```markdown
## [Domain Area]
### [Specific Practice]
[Requirements and procedures]
```

## Best Practices

### 1. Enforce Concurrent Execution
Always include concurrent execution patterns to maximize performance:
```markdown
### CRITICAL: CONCURRENT EXECUTION FOR ALL ACTIONS
Dispatch every set of logically related operations in a single message...
```

### 2. Define Clear Subagent Triggers
Specify exactly when subagents should be invoked:
```markdown
Use PROACTIVELY whenever you:
- Write or modify code
- Prepare for pull requests
- Need code quality assessment
```

### 3. Include Quality Gates
Define mandatory quality checks:
```markdown
### CRITICAL: Static Analysis and Pre-Commit Quality Gate
- Run pre-commit hooks
- Zero warnings required
- All tests must pass
```

### 4. Specify Tool Usage
Define which tools to use and when:
```markdown
### CRITICAL: Package Management with `uv`
- Work only inside virtual environments
- Use `uv` for all operations
```

### CI/CD Integration

Use system prompts in automated workflows:

```yaml
# GitHub Actions example
- name: Code Review with Python Prompt
  run: |
    claude --append-system-prompt @system-prompts/library/python-developer.md \
      -p "Review the changes in this PR for Python best practices"
```

### Docker Integration

```dockerfile
# Include system prompt in container
FROM ubuntu:22.04
COPY system-prompts/library/python-developer.md /claude/prompts/
ENV CLAUDE_SYSTEM_PROMPT=/claude/prompts/python-developer.md
```

### Common Issues and Solutions

| Issue | Solution |
|-------|----------|
| Prompt too long | Split into focused sections, remove redundancy |
| Subagents not invoked | Add explicit "Use PROACTIVELY" triggers |
| Conflicting instructions | Prioritize with "CRITICAL" markers |
| Poor performance | Emphasize concurrent execution patterns |

## Version Compatibility

- **Interactive mode support**: v1.0.51+
- **File reference syntax** (`@file`): All versions
- **Direct content**: All versions

## Official Documentation

- [Claude Code CLI Reference](https://docs.anthropic.com/en/docs/claude-code/cli-reference)
- [SDK Usage](https://docs.anthropic.com/en/docs/claude-code/sdk)
- [Output Styles](https://docs.anthropic.com/en/docs/claude-code/output-styles)
- [Security Best Practices](https://docs.anthropic.com/en/docs/claude-code/security)
