#!/usr/bin/env python3
"""
Session ID Manager Hook for Claude Code

This hook manages session IDs by storing the current session ID and maintaining
a history of previous session IDs for SessionStart events.

Trigger: SessionStart with matcher 'startup|clear'
"""

import json
import os
import sys
from contextlib import suppress
from pathlib import Path


def main() -> None:
    """Main hook execution function."""
    try:
        # Read input from stdin
        input_data = json.load(sys.stdin)

        # Extract key fields
        source = input_data.get('source', '')
        hook_event_name = input_data.get('hook_event_name', '')
        session_id = input_data.get('session_id', '')

        # Initial validation - exit silently if conditions not met
        if hook_event_name != 'SessionStart':
            sys.exit(0)

        if source not in ['startup', 'clear']:
            sys.exit(0)

        if not session_id:
            sys.exit(0)

        # Get Claude project directory
        claude_project_dir = os.environ.get('CLAUDE_PROJECT_DIR')
        if not claude_project_dir:
            sys.exit(0)

        # Ensure .claude directory exists
        claude_dir = os.path.join(claude_project_dir, '.claude')
        os.makedirs(claude_dir, exist_ok=True)

        # File paths
        session_id_file = os.path.join(claude_dir, '.session_id')
        previous_sessions_file = os.path.join(claude_dir, '.previous_session_ids')

        # Check if .session_id file exists
        session_id_path = Path(session_id_file)
        if session_id_path.exists():
            # Read current session ID
            with suppress(OSError):
                # If we can't read the file, just continue
                current_session_id = session_id_path.read_text(encoding='utf-8').strip()

                if current_session_id:
                    # Append current session ID to previous sessions
                    append_to_previous_sessions(previous_sessions_file, current_session_id)

        # Write new session ID to .session_id file
        with suppress(OSError):
            # If we can't write, exit silently
            session_id_path.write_text(session_id, encoding='utf-8')

        sys.exit(0)

    except Exception:
        # Handle all errors silently
        sys.exit(0)


def append_to_previous_sessions(previous_sessions_file: str, session_id: str) -> None:
    """
    Append session ID to previous sessions file and maintain max 100 entries.

    Args:
        previous_sessions_file (str): Path to the previous sessions file
        session_id (str): Session ID to append
    """
    with suppress(OSError):
        # If we can't manage the previous sessions file, just continue
        # Read existing previous session IDs
        previous_sessions = []
        if os.path.exists(previous_sessions_file):
            with open(previous_sessions_file, encoding='utf-8') as f:
                previous_sessions = [line.strip() for line in f if line.strip()]

        # Add current session ID
        previous_sessions.append(session_id)

        # Keep only the last 100 session IDs
        if len(previous_sessions) > 100:
            previous_sessions = previous_sessions[-100:]

        # Write back to file
        with open(previous_sessions_file, 'w', encoding='utf-8') as f:
            f.writelines(f'{sid}\n' for sid in previous_sessions)


if __name__ == '__main__':
    main()
