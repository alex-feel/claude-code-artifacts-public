#!/usr/bin/env python3
"""
Session ID Manager Hook for Claude Code

This hook manages session IDs and communicates them to the model:
1. For 'startup|clear' sources: Creates new session ID, manages history, and
   outputs the new session ID to the model.
2. For other sources: Reads existing session ID from file and outputs it to
   the model for continuity.

The session ID is always communicated to the model with guidance on how to use it
for context management and retrieval operations.

Trigger: SessionStart with any source
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

        # Handle based on source
        if source in ['startup', 'clear']:
            # New session: create/update session ID
            if not session_id:
                sys.exit(0)

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

            # Output session ID message to the model
            context_message = (
                f'SESSION CONTEXT: Session ID is {session_id}.\n'
                'This session ID is used to maintain context and continuity across your interactions. '
                'Remember this session ID as it may be referenced in context retrieval operations.\n\n'
                f'CRITICAL: When spawning subagents via the Task tool, include this session ID ({session_id}) '
                'in the task prompt to maintain context continuity across the agent hierarchy.'
            )
            print(context_message)

        else:
            # Existing session: read and output current session ID
            session_id_path = Path(session_id_file)
            if session_id_path.exists():
                with suppress(OSError):
                    existing_session_id = session_id_path.read_text(encoding='utf-8').strip()
                    if existing_session_id:
                        # Output existing session ID message to the model
                        context_message = (
                            f'SESSION CONTEXT: Session ID is {existing_session_id}.\n'
                            'This session ID maintains context across your interactions. '
                            'Use this when retrieving or storing context information.\n\n'
                            'CRITICAL: When spawning subagents via the Task tool, include this session ID '
                            f'({existing_session_id}) in the task prompt to maintain context continuity '
                            'across the agent hierarchy.'
                        )
                        print(context_message)

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
