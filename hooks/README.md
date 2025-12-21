# Claude Code Hooks

Event-driven automation scripts that enhance Claude Code's functionality by responding to various events during your coding sessions.

## What are hooks?

Hooks are scripts that automatically run in response to specific events in Claude Code, such as file edits, tool usage, or notifications. They enable automatic linting, formatting, validation, and custom workflows.

## Quick Start

### Using Existing Hooks

1. **Through Environment Configuration:**
   Include hooks in your environment YAML file:
   ```yaml
   hooks:
     files:
       - hooks/library/<your-hook>.py
     events:
       - event: PostToolUse
         matcher: Edit|Write
         type: command
         command: <your-hook>.py
   ```

2. **Manual Installation:**
   Copy hook files to `~/.claude/hooks/` and update `~/.claude/settings.json`:
   ```json
   {
     "hooks": {
       "PostToolUse": [
         {
           "matcher": "Edit|Write",
           "hooks": [
             {
               "type": "command",
               "command": ".claude/hooks/<your-hook>.py"
             }
           ]
         }
       ]
     }
   }
   ```

## Creating Custom Hooks

### Hook Script Structure

```python
#!/usr/bin/env python
"""
Hook description
"""
import json
import sys

# Read event data from stdin
event = json.load(sys.stdin)

# Extract relevant information
tool_name = event.get("tool_name")
tool_input = event.get("tool_input", {})
tool_response = event.get("tool_response", {})

# Your logic here
# ...

# Exit codes:
# 0 - Success
# 1 - Error (stops execution)
# 2 - Warning (sends feedback to Claude)
sys.exit(0)
```

### Event Data Structure

Each event receives JSON data via stdin containing:
- `tool_name`: The tool that was used (Write, Edit, etc.)
- `tool_input`: Input parameters passed to the tool
- `tool_response`: Response from the tool execution

### Best Practices

1. **Fast Execution**: Keep hooks lightweight and fast
2. **Error Handling**: Always handle exceptions gracefully
3. **Cross-Platform**: Ensure compatibility across OS platforms
4. **Silent Operations**: Avoid unnecessary output to stdout
5. **Meaningful Feedback**: Use stderr and exit codes for feedback

## Configuration

### Environment Configuration Structure

When using hooks in environment configurations, you need both `files` and `events` sections:

- **`files`**: List of hook script files to download (URLs, absolute paths, or relative to config file)
- **`events`**: Configuration specifying when and how to run the hooks

```yaml
hooks:
  # Files to download and install
  files:
    - hooks/library/<hook-name>.py
    - https://raw.githubusercontent.com/<user>/<repo>/main/hooks/<hook>.py
    - /absolute/path/to/<hook>.py

  # Event configurations
  events:
    - event: PostToolUse
      matcher: "\.py$"
      type: command
      command: <hook-name>.py
```

## Advanced Configuration

### Matcher Patterns

The `matcher` field supports regex patterns to filter when hooks run:
- `Edit|Write` - Run on any file edit
- `\.py$` - Run only for Python files
- `test_.*\.js$` - Run only for JavaScript test files
- `\.md$` - Run only for Markdown files
- `package\.json$` - Run only for package.json files

### Hook Types

Currently supported type:
- `command`: Execute a shell command or script

### Environment Variables

Hooks have access to standard environment variables plus:
- Working directory is the project root
- PATH includes system and user paths

## Troubleshooting

### Hook Not Running
- Check `~/.claude/settings.json` for correct configuration
- Ensure hook file has execute permissions (Unix/macOS)
- Verify the hook file path is correct

### Hook Errors
- Check hook script for syntax errors
- Ensure dependencies are installed
- Test the hook script manually with sample JSON input

### Debugging Tips
- Add logging to a file for debugging
- Use exit code 2 to send messages back to Claude
- Test with simple echo/print statements first

## Advanced Usage

### Chaining Hooks
Multiple hooks can run for the same event:

**In environment YAML configuration:**
```yaml
hooks:
  files:
    - hooks/library/<my-formatter>.py
    - hooks/library/<my-linter>.py
    - hooks/library/<my-tester>.py
  events:
    - event: PostToolUse
      matcher: "\.py$"
      type: command
      command: <my-formatter>.py
    - event: PostToolUse
      matcher: "\.py$"
      type: command
      command: <my-linter>.py
    - event: PostToolUse
      matcher: "\.py$"
      type: command
      command: <my-tester>.py
```

**Resulting settings.json:**
```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "\.py$",
        "hooks": [
          {"type": "command", "command": "py C:/Users/user/.claude/hooks/<my-formatter>.py"},
          {"type": "command", "command": "py C:/Users/user/.claude/hooks/<my-linter>.py"},
          {"type": "command", "command": "py C:/Users/user/.claude/hooks/<my-tester>.py"}
        ]
      }
    ]
  }
}
```

### Conditional Execution
Use matchers and exit codes to create conditional workflows:
```python
# Example: Only format files in certain directories
import os

file_path = tool_input.get("file_path", "")
if "/src/" in file_path or "/lib/" in file_path:
    # Run your formatting logic
    format_code(file_path)
    sys.stderr.write(f"Formatted {file_path}\n")
    sys.exit(0)
else:
    # Skip formatting for other directories
    sys.stderr.write(f"Skipping {file_path} (not in src/lib)\n")
    sys.exit(0)
```

## Documentation

For detailed documentation on creating and using hooks, see:
- [Official Claude Code Hooks Documentation](https://docs.claude.com/en/docs/claude-code/hooks-guide)
