#!/usr/bin/env python3
"""
Claude Code Hook: Task Timezone Context Integration

This hook ensures timezone and date context is included in task descriptions
when spawning subagents using the Task tool. It provides guidance to the model to
include proper timezone and date context for better temporal awareness.

Triggers on: PreToolUse (Task)
Target: Task tool operations
Action: Guide model to include timezone and date context in task descriptions

Exit Codes:
- 0: Success (timezone context present or not a Task tool)
- 2: Guidance provided to include timezone context (non-blocking)
"""

import json
import re
import sys
from datetime import UTC
from datetime import datetime
from typing import Any


def contains_timezone_context(text: str | None) -> bool:
    """
    Check if text contains timezone context indicator.

    Args:
        text: Text to check for timezone context

    Returns:
        bool: True if timezone context is found, False otherwise
    """
    if not text:
        return False

    # Pattern to match "The user's timezone is" phrase
    timezone_pattern = r"The user's timezone is"

    return bool(re.search(timezone_pattern, text, re.IGNORECASE))


def get_task_prompt(tool_input: dict[str, Any]) -> str | None:
    """
    Extract the task prompt from tool input parameters.

    Args:
        tool_input: The tool input dictionary

    Returns:
        str: The task prompt or None if not found
    """
    # Check common parameter names for task description
    task_keys = ['prompt', 'task', 'instruction', 'description', 'message']

    for key in task_keys:
        if key in tool_input:
            value = tool_input[key]
            if isinstance(value, str):
                return value
            return None

    return None


def generate_timezone_context() -> str:
    """
    Generate current timezone and date context string.

    Returns:
        str: Formatted timezone and date context
    """
    # Get current timezone and date with timezone awareness
    current_time = datetime.now(tz=UTC).astimezone()
    timezone = current_time.strftime('%Z')
    current_date = current_time.strftime('%Y-%m-%d')

    # If timezone is empty (common on some systems), try to get a fallback
    if not timezone:
        try:
            timezone = current_time.astimezone().strftime('%Z')
        except Exception:
            timezone = 'Local'

    # Format the context message
    return (
        f"Very important: The user's timezone is {timezone}. "
        f"The current date is {current_date}.\n\n"
        "Any dates before this are in the past, and any dates after this are in the future. "
        "When the user asks for the 'latest', 'most recent', 'today's', etc. "
        "don't assume your knowledge is up to date."
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

        # Extract tool input
        tool_input = input_data.get('tool_input', {})

        # Get the task prompt
        task_prompt = get_task_prompt(tool_input)

        # Skip if we can't determine the task prompt
        if not task_prompt:
            sys.exit(0)

        # Check if timezone context is already present
        if contains_timezone_context(task_prompt):
            # Timezone context is already present, allow the operation
            sys.exit(0)

        # Generate the current timezone context
        timezone_context = generate_timezone_context()

        # Generate guidance for including timezone context
        guidance_message = (
            'GUIDANCE: Please include timezone and date context at the beginning of your task description.\n\n'
            'For better temporal awareness, the task description should start with:\n\n'
            f'{timezone_context}\n\n'
            'Then continue with your original task description. This helps the subagent understand '
            'the current time context and handle date-related queries more accurately.\n\n'
            'Please revise your task description to include this timezone context at the beginning.'
        )

        # Provide guidance to the model (exit code 2 for model feedback)
        print(guidance_message, file=sys.stderr)
        sys.exit(2)  # Send feedback to Claude Code for processing

    except json.JSONDecodeError:
        sys.exit(0)  # Silent failure for invalid JSON
    except Exception:
        sys.exit(0)  # Silent failure for unexpected errors


if __name__ == '__main__':
    main()
