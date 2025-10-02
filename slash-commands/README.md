# Claude Code Slash Commands

Slash commands are shortcuts that control Claude's behavior during interactive sessions. They are simple Markdown files that define custom prompts and workflows.

## Using Slash Commands

### Option 1: Project-level (Recommended for teams)

Copy commands to your project:

```bash
# Create .claude/commands directory
mkdir -p .claude/commands

# Copy desired commands
cp slash-commands/library/<command-name>.md .claude/commands/
cp slash-commands/library/<another-command>.md .claude/commands/
```

### Option 2: User-level (Personal use)

Install commands for all projects:

```bash
# Windows
mkdir -p %USERPROFILE%\.claude\commands
copy slash-commands\library\<command-name>.md %USERPROFILE%\.claude\commands\

# Unix/Mac
mkdir -p ~/.claude/commands
cp slash-commands/library/<command-name>.md ~/.claude/commands/
```

## Command Format

Commands are Markdown files with optional YAML frontmatter:

### YAML Frontmatter (Optional)

Commands can include frontmatter at the top to configure behavior:

```yaml
---
description: Brief description of what this command does
argument-hint: "[expected format] [example: file.txt]"
allowed-tools: Bash, Read, Write  # Restrict tools (optional)
---
```

**Frontmatter Fields:**
- **description**: Brief description shown in command list
- **argument-hint**: Hints for expected arguments format
- **allowed-tools**: Comma-separated list of allowed tools

### Command Structure

1. **Filename**: The command name (without `.md` extension)
2. **Frontmatter**: Optional YAML configuration (see above)
3. **Content**: Markdown instructions for Claude
4. **Arguments**: Use `$ARGUMENTS` to access user input

## Creating Custom Commands

1. Create a new command file:
   ```bash
   touch my-command.md
   ```

2. Configure the frontmatter (optional):
   - Set `description` for command list
   - Add `argument-hint` to guide users
   - Restrict `allowed-tools` for safety

3. Write the command content using `$ARGUMENTS` for user input

4. Save to `.claude/commands/` or `~/.claude/commands/`

## Best Practices

1. **Clear Names**: Use descriptive command names
2. **Arguments**: Always use `$ARGUMENTS` for input
3. **Testing**: Test commands before sharing
4. **Documentation**: Write clear instructions in the command

## Advanced Features

### Bash Commands

Execute shell commands with `!`:
```markdown
!npm test
```

### File References

Reference files with `@`:
```markdown
Review @src/main.py
```

### Extended Thinking

For complex analysis:
```markdown
[Extended thinking required]
Analyze the architecture...
```

## Documentation

For detailed documentation on creating and using slash commands, see:
- [Official Claude Code Slash Commands Documentation](https://docs.anthropic.com/en/docs/claude-code/slash-commands)
