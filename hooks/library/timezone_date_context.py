#!/usr/bin/env python3
"""
Timezone and Date Context Hook for Claude Code

This hook provides timezone and date context to the model at session start,
helping the model understand the user's current timezone and date for better
context when handling date-related queries.

Trigger: SessionStart with any source (no source restrictions)
"""

import json
import sys
from datetime import UTC
from datetime import datetime


def main() -> None:
    """Main hook execution function."""
    try:
        # Read input from stdin
        input_data = json.load(sys.stdin)

        # Extract key fields
        hook_event_name = input_data.get('hook_event_name', '')

        # Initial validation - only run on SessionStart events
        if hook_event_name != 'SessionStart':
            sys.exit(0)

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
            # Try to get timezone from astimezone()
            try:
                timezone_name = current_time.astimezone().strftime('%Z')
            except Exception:
                timezone_name = 'Local'

        # Combine timezone name with UTC offset
        timezone = f'{timezone_name}{offset_str}'

        # Output timezone and date context message for the model
        context_message = (
            f"TIMEZONE CONTEXT: The user's timezone is {timezone}. "
            f"The current date is {current_date}.\n"
            "Any dates before this are in the past, and any dates after this are in the future. "
            "When the user asks for the 'latest', 'most recent', 'today's', etc. "
            "don't assume your knowledge is up to date.\n\n"
            "📌 NOTE: When spawning subagents via the Task tool, include this timezone and date information "
            "in the task prompt to ensure temporal context consistency across the agent hierarchy."
        )

        print(context_message)

        # Always exit successfully
        sys.exit(0)

    except Exception:
        # Handle all errors silently and exit successfully
        sys.exit(0)


if __name__ == '__main__':
    main()
