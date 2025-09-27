#!/usr/bin/env python3
"""
User Prompt Context Saver Hook for Claude Code.

This hook captures user prompts from UserPromptSubmit events and stores them
in the mcp-context-server for enhanced conversation context management.

Note: Currently, the UserPromptSubmit event does not provide images from user
requests, so this hook cannot save image content to the context server. Only
text prompts are captured and stored.

Trigger: UserPromptSubmit
"""

import asyncio
import json
import os
import re
import sys
from collections.abc import Coroutine
from contextlib import suppress
from pathlib import Path
from typing import Any
from typing import cast

try:
    from fastmcp import Client  # type: ignore[import-not-found]
except ImportError:
    # FastMCP not installed, silent failure
    sys.exit(0)


class SyncMCPClient:
    """
    Synchronous wrapper for the async FastMCP client.

    This wrapper allows us to use the async FastMCP client in a synchronous
    context, which is required for Claude Code hooks.
    """

    def __init__(self, server_command: list[str] | str, timeout: float = 30.0) -> None:
        """
        Initialize the synchronous MCP client wrapper.

        Args:
            server_command: Command to start the MCP server (list or string)
            timeout: Timeout in seconds for MCP operations
        """
        self.server_command = server_command
        self.timeout = timeout

    def _run_async(self, coro: Coroutine[Any, Any, dict[str, Any]]) -> dict[str, Any]:
        """
        Run an async coroutine in a sync context.

        Args:
            coro: The async coroutine to run

        Returns:
            The result of the coroutine

        Raises:
            RuntimeError: If called from an existing async context
        """
        try:
            asyncio.get_running_loop()
            # If we get here, we're already in an async context
            raise RuntimeError('Cannot run from async context')
        except RuntimeError as e:
            if 'no running event loop' in str(e).lower():
                # No event loop, safe to create one
                return asyncio.run(coro)
            # Re-raise if it's the "already in async" error
            raise

    async def _store_context_async(
        self, thread_id: str, source: str, text: str,
    ) -> dict[str, Any]:
        """
        Store context asynchronously using the MCP server.

        Args:
            thread_id: The thread/session identifier
            source: The source of the context (always "user" for this hook)
            text: The prompt text to store

        Returns:
            The server response as a dictionary
        """
        # Create transport manually for complex commands
        from fastmcp.client.transports import StdioTransport  # type: ignore[import-not-found]

        # StdioTransport expects the command and args separately
        if isinstance(self.server_command, list):
            cmd = self.server_command[0]
            args = self.server_command[1:] if len(self.server_command) > 1 else []
        else:
            # If it's a string, try to split it
            parts = self.server_command.split()
            cmd = parts[0]
            args = parts[1:] if len(parts) > 1 else []

        # Explicitly cast to Any to avoid type checking issues with fastmcp
        transport = cast(Any, StdioTransport(cmd, args))

        # Use the client with explicit cast
        async with cast(Any, Client(transport)) as client:
            # Call the store_context tool on the MCP server with proper typing
            return cast(
                dict[str, Any],
                await client.call_tool(
                    'store_context',
                    {'thread_id': thread_id, 'source': source, 'text': text},
                ),
            )

    def store_context(self, thread_id: str, source: str, text: str) -> dict[str, Any]:
        """
        Store context synchronously.

        Args:
            thread_id: The thread/session identifier
            source: The source of the context (always "user" for this hook)
            text: The prompt text to store

        Returns:
            The server response as a dictionary
        """
        return self._run_async(self._store_context_async(thread_id, source, text))


def is_prebuilt_slash_command(prompt: str) -> bool:
    """
    Check if a prompt is a pre-built slash command that should be skipped.

    Pre-built slash commands are built-in Claude Code commands that don't need
    context saving as they are system-level operations.

    Args:
        prompt: The user prompt to check

    Returns:
        True if the prompt is a pre-built slash command, False otherwise
    """
    # Set of pre-built Claude Code slash commands to skip
    prebuilt_commands = {
        'add-dir', 'agents', 'bug', 'clear', 'compact', 'config', 'cost',
        'doctor', 'help', 'init', 'login', 'logout', 'mcp', 'memory',
        'model', 'permissions', 'pr_comments', 'review', 'status',
        'terminal-setup', 'vim',
    }

    # Pattern to match slash commands at the start of a prompt
    # Matches: /command or /command with args
    # Uses \S+ to match any non-whitespace characters (handles underscores, hyphens, numbers, etc.)
    slash_command_pattern = re.compile(r'^/(\S+)(?:\s|$)')

    match = slash_command_pattern.match(prompt.strip())
    if not match:
        return False

    command_name = match.group(1).lower()
    return command_name in prebuilt_commands


def read_session_id(project_dir: str) -> str | None:
    """
    Read the current session ID from the .claude/.session_id file.

    Args:
        project_dir: The Claude project directory path

    Returns:
        The session ID string if found, None otherwise
    """
    session_id_file = Path(project_dir) / '.claude' / '.session_id'

    if not session_id_file.exists():
        return None

    with suppress(OSError):
        session_id = session_id_file.read_text(encoding='utf-8').strip()
        return session_id or None

    return None


def main() -> None:
    """Main hook execution function."""
    try:
        # Read input from stdin
        input_data = json.load(sys.stdin)

        # Extract key fields
        hook_event_name = input_data.get('hook_event_name', '')

        # Validate this is a UserPromptSubmit event
        if hook_event_name != 'UserPromptSubmit':
            sys.exit(0)

        # Extract prompt from input data (UserPromptSubmit has prompt directly)
        prompt = input_data.get('prompt', '')
        if not prompt:
            # No prompt to save
            sys.exit(0)

        # Check if this is a pre-built slash command that should be skipped
        if is_prebuilt_slash_command(prompt):
            # Skip pre-built slash commands
            sys.exit(0)

        # Get Claude project directory
        claude_project_dir = os.environ.get('CLAUDE_PROJECT_DIR')
        if not claude_project_dir:
            # No project directory, can't proceed
            sys.exit(0)

        # Read session ID
        session_id = read_session_id(claude_project_dir)
        if not session_id:
            # No session ID available, can't save context
            sys.exit(0)

        # Create MCP client and store context
        with suppress(Exception):
            # Any failure in MCP communication should be silent
            # Pass command as a list for FastMCP to properly parse
            mcp_server_command = [
                'uvx',
                '--from',
                'git+https://github.com/alex-feel/mcp-context-server',
                'mcp-context-server',
            ]
            client = SyncMCPClient(mcp_server_command)

            # Store the user prompt in the context server
            # Using session_id as thread_id to group prompts by session
            client.store_context(
                thread_id=session_id,
                source='user',
                text=prompt,
            )

        # Always exit successfully
        sys.exit(0)

    except Exception:
        # Handle all errors silently
        sys.exit(0)


if __name__ == '__main__':
    main()
