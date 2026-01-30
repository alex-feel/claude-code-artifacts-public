#!/usr/bin/env python3
"""
Session ID Manager Hook for Claude Code

This hook manages session IDs and communicates them to the model:
1. Validates that the hook event is 'SessionStart'
2. Takes session_id from the payload (authoritative for ALL sources)
3. Writes session_id to .session_id file ONLY if it differs from current value
4. Outputs unified session context message for ALL sources

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
        hook_event_name = input_data.get('hook_event_name', '')
        session_id = input_data.get('session_id', '')

        # Validate hook event and session_id
        if hook_event_name != 'SessionStart':
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

        # File path for session ID
        session_id_file = Path(os.path.join(claude_dir, '.session_id'))

        # Read current session ID (if file exists)
        current_session_id = ''
        if session_id_file.exists():
            with suppress(OSError):
                current_session_id = session_id_file.read_text(encoding='utf-8').strip()

        # Write new session ID only if it differs (efficiency optimization)
        if session_id != current_session_id:
            with suppress(OSError):
                session_id_file.write_text(session_id, encoding='utf-8')

        # Output unified session context message to the model
        context_message = (
            f'SESSION CONTEXT: Session ID is {session_id}.\n'
            'This session ID is used to maintain context and continuity across your interactions. '
            'Remember this session ID as it may be referenced in context retrieval operations '
            'an used as thread_id when working with the context-server.\n\n'
            f'CRITICAL: When spawning or resuming subagents via the Task tool, include this session ID ({session_id}) '
            'in the task prompt to maintain context continuity across the agent hierarchy.'
        )
        print(context_message)

        sys.exit(0)

    except Exception:
        # Handle all errors silently
        sys.exit(0)


if __name__ == '__main__':
    main()
