#!/usr/bin/env python3
"""
Claude Code Hook: Task Session ID Context Integration

This hook ensures session ID context is included in task descriptions
when spawning subagents using the Task tool. It reads the existing session ID
from the .session_id file and provides guidance to the model to include it
for better context continuity across agent hierarchy.

Triggers on: PreToolUse (Task)
Target: Task tool operations
Action: Guide model to include session ID context in task descriptions

Exit Codes:
- 0: Success (session ID context present, not found, or not a Task tool)
- 2: Guidance provided to include session ID context (blocking)
"""

import json
import os
import sys
from contextlib import suppress
from pathlib import Path
from typing import Any

# Type alias for JSON-like values that can be recursively processed
JSONValue = str | int | float | bool | None | dict[str, Any] | list[Any]


def contains_session_id(text: str | None, session_id: str) -> bool:
    """
    Check if text contains the session ID.

    Args:
        text: Text to check for session ID
        session_id: The session ID to look for

    Returns:
        bool: True if session ID is found, False otherwise
    """
    if not text or not session_id:
        return False

    # Check if the session ID appears in the text
    return session_id in text


def check_session_id_in_tool_input(tool_input: dict[str, Any], session_id: str) -> bool:
    """
    Check if session ID exists anywhere in the tool input.

    Recursively searches through all string values in the tool_input
    to find the session ID.

    Args:
        tool_input: The tool input dictionary
        session_id: The session ID to search for

    Returns:
        bool: True if session ID is found, False otherwise
    """
    def search_for_session_id(obj: JSONValue) -> bool:
        """Recursively search for session ID in any string value."""
        if isinstance(obj, str):
            return contains_session_id(obj, session_id)
        if isinstance(obj, dict):
            for value in obj.values():
                if search_for_session_id(value):
                    return True
        elif isinstance(obj, list):
            for item in obj:
                if search_for_session_id(item):
                    return True
        return False

    return search_for_session_id(tool_input)


def read_session_id(claude_project_dir: str) -> str | None:
    """
    Read the existing session ID from the .session_id file.

    Args:
        claude_project_dir: The Claude project directory path

    Returns:
        str | None: The session ID if found, None otherwise
    """
    try:
        # Construct the session ID file path
        session_id_file = os.path.join(claude_project_dir, '.claude', '.session_id')
        session_id_path = Path(session_id_file)

        if session_id_path.exists():
            with suppress(OSError):
                existing_session_id = session_id_path.read_text(encoding='utf-8').strip()
                if existing_session_id:
                    return existing_session_id
    except Exception:
        pass

    return None


def generate_session_context(session_id: str) -> str:
    """
    Generate session ID context string.

    Args:
        session_id: The session ID to include in context

    Returns:
        str: Formatted session ID context
    """
    return (
        f'SESSION CONTEXT: Use session ID {session_id} for this task. '
        'This maintains context and continuity across the agent hierarchy.\n'
    )


def main() -> None:
    """Main hook execution."""
    try:
        # Read JSON input from stdin
        input_data = json.load(sys.stdin)

        # Extract and validate event and tool
        hook_event_name = input_data.get('hook_event_name', '')
        tool_name = input_data.get('tool_name', '')

        # Initial validation - exit silently if conditions not met
        if hook_event_name != 'PreToolUse':
            sys.exit(0)

        if tool_name != 'Task':
            sys.exit(0)

        # Get Claude project directory
        claude_project_dir = os.environ.get('CLAUDE_PROJECT_DIR')
        if not claude_project_dir:
            sys.exit(0)

        # Read existing session ID from file
        session_id = read_session_id(claude_project_dir)
        if not session_id:
            # No session ID found, allow the operation to proceed
            sys.exit(0)

        # Extract tool input
        tool_input = input_data.get('tool_input', {})

        # Check if session ID is already present anywhere in the tool input
        if check_session_id_in_tool_input(tool_input, session_id):
            # Session ID context is already present, allow the operation
            sys.exit(0)

        # Generate the session context
        session_context = generate_session_context(session_id)

        # Generate guidance for including session ID context
        guidance_message = (
            'GUIDANCE: Please include session ID context in your task description.\n\n'
            'For better context continuity across the agent hierarchy, the task description should include:\n\n'
            f'{session_context}\n'
            'This helps subagents maintain context awareness and enables proper context retrieval '
            'and storage operations. The session ID ensures all agents in the hierarchy share '
            'the same contextual thread.\n\n'
            'Please revise your task description to include this session ID context.'
        )

        # Provide guidance to the model (exit code 2 for model feedback)
        print(guidance_message, file=sys.stderr)
        sys.exit(2)  # Block tool call and send feedback to Claude Code for processing

    except json.JSONDecodeError:
        sys.exit(0)  # Silent failure for invalid JSON
    except Exception:
        sys.exit(0)  # Silent failure for unexpected errors


if __name__ == '__main__':
    main()
