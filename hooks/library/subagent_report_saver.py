#!/usr/bin/env python3
"""
Subagent Report Saver Hook for Claude Code.

This hook intercepts SubagentStop events and instructs the agent to save a
comprehensive work report to the context server before stopping. This ensures
all subagent work is properly documented and preserved for future reference.

The hook blocks the stop action (exit code 2) and provides detailed instructions
via stderr for the agent to create and save their work report.

Trigger: SubagentStop
Exit Codes:
  - 0: Silent pass-through (on errors or invalid events)
  - 2: Block stop and provide instructions (on valid SubagentStop)
"""

import json
import os
import sys
from pathlib import Path


def read_session_id() -> str | None:
    """
    Read the current session ID from the .claude/.session_id file.

    Returns:
        The session ID string if found, None otherwise
    """
    project_dir = os.environ.get('CLAUDE_PROJECT_DIR')
    if not project_dir:
        return None

    session_id_file = Path(project_dir) / '.claude' / '.session_id'
    if not session_id_file.exists():
        return None

    try:
        session_id = session_id_file.read_text(encoding='utf-8').strip()
        return session_id or None
    except Exception:
        return None


def format_instruction_message(session_id: str) -> str:
    """
    Format the instruction message for the agent.

    Args:
        session_id: The current session ID

    Returns:
        Formatted instruction message for stderr
    """
    return f'''IMPORTANT! Work documentation required before stopping.

Please complete the following before stopping:

1. Create a comprehensive Markdown report of your work results including:
   ## Summary
   - Brief overview of what was accomplished

   ## Work Performed
   - Detailed list of all tasks completed

   ## Results Achieved
   - Detailed documentation, outcomes, deliverables, etc.
   - Examples (code, etc.), URIs (URLs, etc.)
   - Other references (version numbers, filenames, entity names, lines in code, etc.)

2. Save the report using mcp__context-server__store_context with these parameters:
   - thread_id: '{session_id}'
   - source: 'agent'
   - text: [your complete Markdown report]
   - metadata: {{
       "agent_name": "[your agent name]",
       "task_type": "[implementation/research/review/etc]"
     }}
   - tags: ["report", "subagent:[your-name]", plus relevant content tags]

3. After successfully saving the report, do NOT pass it to the calling party, just tell that the task is done.

This ensures your work is documented and preserved for future reference. Ultrathink.'''


def main() -> None:
    """Main hook execution function."""
    try:
        # Read input from stdin
        input_data = json.load(sys.stdin)

        # Extract and validate hook event name
        hook_event_name = input_data.get('hook_event_name', '')
        if hook_event_name != 'SubagentStop':
            # Not a SubagentStop event, pass through silently
            sys.exit(0)

        # Check if stop_hook_active to prevent infinite loops
        stop_hook_active = input_data.get('stop_hook_active', False)
        if stop_hook_active:
            # Hook is already active, allow stop to prevent loops
            sys.exit(0)

        # Read session ID for the report storage
        session_id = read_session_id()
        if not session_id:
            # No session ID available, can't instruct proper storage
            # Still block with generic instructions
            session_id = 'current-session'

        # Format and output the instruction message
        instruction = format_instruction_message(session_id)
        print(instruction, file=sys.stderr)

        # Exit with code 2 to block the stop and deliver instructions
        sys.exit(2)

    except json.JSONDecodeError:
        # Invalid JSON input, fail silently
        sys.exit(0)
    except Exception:
        # Any other error, fail silently
        sys.exit(0)


if __name__ == '__main__':
    main()
