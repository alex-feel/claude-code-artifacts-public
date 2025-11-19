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
- 2: Guidance provided to include timezone context (blocking)
"""

import io
import json
import re
import sys
from datetime import UTC
from datetime import datetime
from typing import Any

# Type alias for JSON-like values that can be recursively processed
JSONValue = str | int | float | bool | None | dict[str, Any] | list[Any]


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


def check_timezone_in_tool_input(tool_input: dict[str, Any]) -> bool:
    """
    Check if timezone context exists anywhere in the tool input.

    Recursively searches through all string values in the tool_input
    to find the timezone context phrase.

    Args:
        tool_input: The tool input dictionary

    Returns:
        bool: True if timezone context is found, False otherwise
    """
    def search_for_timezone(obj: JSONValue) -> bool:
        """Recursively search for timezone context in any string value."""
        if isinstance(obj, str):
            return contains_timezone_context(obj)
        if isinstance(obj, dict):
            for value in obj.values():
                if search_for_timezone(value):
                    return True
        elif isinstance(obj, list):
            for item in obj:
                if search_for_timezone(item):
                    return True
        return False

    return search_for_timezone(tool_input)


def generate_timezone_context() -> str:
    """
    Generate current timezone and date context string.

    Returns:
        str: Formatted timezone and date context
    """
    # Get current timezone and date with timezone awareness
    current_time = datetime.now(tz=UTC).astimezone()
    timezone_name = current_time.strftime('%Z')
    current_date = current_time.strftime('%Y-%m-%d')

    # Calculate UTC offset
    utc_offset = current_time.utcoffset()
    if utc_offset:
        total_seconds = int(utc_offset.total_seconds())
        hours, remainder = divmod(abs(total_seconds), 3600)
        minutes = remainder // 60
        sign = '+' if total_seconds >= 0 else '-'
        offset_str = f' (UTC{sign}{hours:02d}:{minutes:02d})'
    else:
        offset_str = ''

    # If timezone name is empty (common on some systems), try to get a fallback
    if not timezone_name:
        try:
            timezone_name = current_time.astimezone().strftime('%Z')
        except Exception:
            timezone_name = 'Local'

    # Combine timezone name with UTC offset
    timezone = f'{timezone_name}{offset_str}'

    # Format the context message
    return (
        f"TIMEZONE CONTEXT: The user's timezone is {timezone}. "
        f"The current date is {current_date}.\n"
        "Any dates before this are in the past, and any dates after this are in the future. "
        "When the user asks for the 'latest', 'most recent', 'today's', etc. "
        "don't assume your knowledge is up to date."
    )


def main() -> None:
    """Main hook execution."""
    # Force UTF-8 encoding for stdout/stderr to ensure proper character display
    # This is critical on Windows systems where the default encoding (cp1251, etc.)
    # can cause garbled output when timezone names contain non-ASCII characters
    try:
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True,
        )
        sys.stderr = io.TextIOWrapper(
            sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True,
        )
    except Exception:
        pass  # Continue even if encoding reconfiguration fails

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

        # Check if timezone context is already present anywhere in the tool input
        if check_timezone_in_tool_input(tool_input):
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
        sys.exit(2)  # Block tool call and send feedback to Claude Code for processing

    except json.JSONDecodeError:
        sys.exit(0)  # Silent failure for invalid JSON
    except Exception:
        sys.exit(0)  # Silent failure for unexpected errors


if __name__ == '__main__':
    main()
