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
import ctypes
import io
import json
import os
import re
import sys
import time
import traceback
from collections.abc import Coroutine
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import Any
from typing import cast

try:
    from fastmcp import Client
except ImportError:
    # FastMCP not installed, silent failure
    sys.exit(0)


def setup_windows_utf8() -> None:
    """
    Configure Windows console for UTF-8 encoding.

    This ensures that subprocess communication uses UTF-8 instead of
    Windows codepage (CP1252, Windows-1251) which corrupts non-ASCII text.

    CRITICAL for handling Cyrillic, Chinese, Arabic, and other non-ASCII text.
    Without this, non-ASCII characters stored via the hook appear as
    garbled text (mojibake) due to Windows default codepage encoding.

    This function:
    1. Sets PYTHONUTF8=1 environment variable (Python 3.7+)
    2. Configures Windows console codepage to UTF-8 (65001)

    It is applied before any subprocess operations to ensure proper
    encoding for FastMCP StdioTransport stdin/stdout communication.
    """
    if sys.platform != 'win32':
        return

    try:
        # Set Python to UTF-8 mode (Python 3.7+)
        # This ensures all text I/O uses UTF-8 by default
        os.environ['PYTHONUTF8'] = '1'

        # Set Windows console codepage to UTF-8 (65001)
        # This affects stdin/stdout/stderr of spawned subprocesses
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleCP(65001)  # Input codepage
        kernel32.SetConsoleOutputCP(65001)  # Output codepage

        log_error('UTF-8 mode configured for Windows console')
    except Exception as e:
        # Non-fatal: log error but continue
        # Hook should still work even if UTF-8 setup fails
        log_error(f'Failed to set Windows UTF-8 mode: {e}')


def log_error(message: str) -> None:
    """
    Log errors to a debug file with default location for better diagnostics.

    Uses CLAUDE_HOOK_DEBUG_FILE environment variable to specify log location.
    If not set, defaults to .claude/.hook_debug.log in the project directory.

    Args:
        message: The error message to log
    """
    debug_file = os.environ.get('CLAUDE_HOOK_DEBUG_FILE')

    # Default to project-local debug log if not specified
    if not debug_file:
        project_dir = os.environ.get('CLAUDE_PROJECT_DIR')
        if project_dir:
            debug_file = str(Path(project_dir) / '.claude' / '.hook_debug.log')

    if debug_file:
        try:
            with Path(debug_file).open('a', encoding='utf-8') as f:
                timestamp = datetime.now(tz=UTC).isoformat()
                f.write(f'{timestamp}: {message}\n')
        except Exception:
            # Silent failure for logging - don't break the hook
            pass


def report_error(error_type: str, error_msg: str) -> None:
    """
    Report error to both debug log and stats file for better diagnostics.

    Creates an error tracking file at .claude/.hook_errors with structured
    error information for troubleshooting intermittent failures.

    Args:
        error_type: Category of error (e.g., 'UVX_FAILURE', 'SESSION_ID_READ')
        error_msg: Detailed error message
    """
    log_error(f'{error_type}: {error_msg}')

    # Track error statistics
    project_dir = os.environ.get('CLAUDE_PROJECT_DIR')
    if project_dir:
        stats_file = Path(project_dir) / '.claude' / '.hook_errors'
        try:
            stats = {
                'timestamp': datetime.now(tz=UTC).isoformat(),
                'error': error_type,
                'message': error_msg,
            }
            with stats_file.open('a', encoding='utf-8') as f:
                f.write(json.dumps(stats) + '\n')
        except Exception:
            # Silent failure for stats tracking
            pass


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
        self,
        thread_id: str,
        source: str,
        text: str,
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
        from fastmcp.client.transports import StdioTransport

        # StdioTransport expects the command and args separately
        if isinstance(self.server_command, list):
            cmd = self.server_command[0]
            args = self.server_command[1:] if len(self.server_command) > 1 else []
        else:
            # If it's a string, try to split it
            parts = self.server_command.split()
            cmd = parts[0]
            args = parts[1:] if len(parts) > 1 else []

        # Pass PYTHONUTF8=1 to subprocess via environment
        # This ensures subprocess starts with UTF-8 mode enabled from the beginning.
        # Setting os.environ after Python starts doesn't affect subprocess initialization.
        env = os.environ.copy()
        env['PYTHONUTF8'] = '1'

        # Create transport with environment variables for UTF-8 encoding
        transport = cast(Any, StdioTransport(cmd, args, env=env))

        # Use the client with explicit cast
        async with cast(Any, Client(transport)) as client:
            # Normalize Windows line endings for NDJSON format
            # Windows CRLF (\r\n) can break NDJSON message parsing on stdin/stdout.
            # Convert all line endings to Unix format (LF) for consistent handling.
            normalized_text = text.replace('\r\n', '\n').replace('\r', '\n')

            # Call the store_context tool on the MCP server with proper typing
            return cast(
                dict[str, Any],
                await client.call_tool(
                    'store_context',
                    {'thread_id': thread_id, 'source': source, 'text': normalized_text},
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
        'add-dir',
        'agents',
        'bug',
        'clear',
        'compact',
        'config',
        'cost',
        'doctor',
        'help',
        'init',
        'login',
        'logout',
        'mcp',
        'memory',
        'model',
        'permissions',
        'pr_comments',
        'review',
        'status',
        'terminal-setup',
        'vim',
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


def read_session_id(project_dir: str, max_retries: int = 3) -> str | None:
    """
    Read the current session ID from the .claude/.session_id file with retry logic.

    Implements exponential backoff retry to handle file locking and race conditions
    on Windows where Claude Code might still be writing the session ID file.

    Args:
        project_dir: The Claude project directory path
        max_retries: Maximum number of retry attempts (default: 3)

    Returns:
        The session ID string if found, None otherwise
    """
    session_id_file = Path(project_dir) / '.claude' / '.session_id'

    if not session_id_file.exists():
        report_error('SESSION_ID_READ', 'Session ID file does not exist')
        return None

    for attempt in range(max_retries):
        try:
            session_id = session_id_file.read_text(encoding='utf-8').strip()
            if session_id:
                if attempt > 0:
                    log_error(f'Session ID read succeeded on attempt {attempt + 1}/{max_retries}')
                return session_id
            report_error('SESSION_ID_READ', f'Session ID file empty (attempt {attempt + 1}/{max_retries})')
        except OSError as e:
            error_msg = f'Failed to read session ID (attempt {attempt + 1}/{max_retries}): {e}'
            if attempt < max_retries - 1:
                log_error(error_msg)
                time.sleep(0.1 * (2 ** attempt))  # Exponential backoff: 100ms, 200ms, 400ms
            else:
                report_error('SESSION_ID_READ', error_msg)

    return None


def create_mcp_client_with_retry(max_retries: int = 3, timeout_first_run: float = 60.0) -> SyncMCPClient:
    """
    Create MCP client with retry logic and offline fallback for uvx reliability.

    Implements exponential backoff retry to handle uvx package installation timing,
    network failures, and cache invalidation issues. Falls back to offline mode
    if network is unavailable.

    Args:
        max_retries: Maximum number of retry attempts (default: 3)
        timeout_first_run: Timeout for first run that may need package download (default: 60s)

    Returns:
        Configured SyncMCPClient instance

    Raises:
        RuntimeError: If all retry attempts fail
    """
    last_error: Exception | None = None
    attempts = 0

    while attempts < max_retries:
        try:
            # Use standard uvx command
            mcp_server_command = ['uvx', 'mcp-context-server']
            # Longer timeout for first run (package download), standard timeout for retries
            timeout = timeout_first_run if attempts == 0 else 30.0
            client = SyncMCPClient(mcp_server_command, timeout=timeout)

            # Test connectivity with a simple operation (will raise if connection fails)
            # Note: We don't actually test here to avoid extra overhead
            # The connection will be tested when store_context is called

            if attempts > 0:
                log_error(f'MCP client created successfully on attempt {attempts + 1}/{max_retries}')

            return client

        except Exception as e:
            last_error = e
            attempts += 1
            error_msg = f'Failed to create MCP client (attempt {attempts}/{max_retries}): {type(e).__name__}: {e}'

            if attempts < max_retries:
                # Try offline fallback on subsequent attempts
                if attempts > 1:
                    try:
                        log_error(f'{error_msg}, trying offline mode')
                        mcp_server_command = ['uvx', '--offline', 'mcp-context-server']
                        client = SyncMCPClient(mcp_server_command, timeout=30.0)
                        log_error('MCP client created successfully in offline mode')
                        return client
                    except Exception as offline_error:
                        log_error(f'Offline mode failed: {type(offline_error).__name__}: {offline_error}')

                # Exponential backoff
                log_error(error_msg)
                sleep_time = 0.5 * (2 ** (attempts - 1))  # 0.5s, 1s, 2s
                time.sleep(sleep_time)
            else:
                # Final attempt failed
                report_error('UVX_FAILURE', error_msg)

    # All retries exhausted
    if last_error:
        raise last_error
    raise RuntimeError('Failed to create MCP client after all retries')


def main() -> None:
    """Main hook execution function."""
    try:
        # CRITICAL: Configure UTF-8 for Windows BEFORE any subprocess operations
        # This prevents non-ASCII text corruption (mojibake) in MCP communication
        setup_windows_utf8()

        # Reconfigure stdin to UTF-8 for Git Bash compatibility
        # Git Bash on Windows uses MinGW64/MSYS2 runtime with Unix-style locale system.
        # Without LANG/LC_ALL exports, it defaults to Windows codepage (CP1252/Windows-1251),
        # causing stdin pipes to corrupt UTF-8 data BEFORE Python reads it.
        # This reconfigures the already-open stdin stream to UTF-8 encoding.
        #
        # Use getattr() for type-safe access to reconfigure() method (Python 3.7+)
        # sys.stdin is typed as TextIO in stubs but is TextIOWrapper at runtime
        reconfigure_method = getattr(sys.stdin, 'reconfigure', None)
        if reconfigure_method is not None:
            # Python 3.7+ has reconfigure() method on TextIOWrapper
            try:
                reconfigure_method(encoding='utf-8')
                log_error('Git Bash compatibility: stdin reconfigured to UTF-8')
            except OSError as e:
                log_error(f'Git Bash compatibility: stdin reconfigure failed: {e}')
        else:
            # Fallback for Python < 3.7 or if reconfigure() not available
            try:
                sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8')
                log_error('Git Bash compatibility: stdin wrapped with UTF-8 TextIOWrapper')
            except Exception as e:
                log_error(f'Git Bash compatibility: stdin UTF-8 fix failed: {e}')

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
        try:
            # Any failure in MCP communication should be silent
            # Pass command as a list for FastMCP to properly parse
            # Use PyPI package (simpler and faster than GitHub URL)
            #
            # CRITICAL UTF-8 REQUIREMENT:
            # The setup_windows_utf8() function MUST be called before this point
            # to ensure subprocess stdin/stdout use UTF-8 encoding.
            # Without this, non-ASCII text (Cyrillic, Chinese, Arabic, etc.) gets
            # corrupted on Windows due to codepage defaults (CP1252/Windows-1251).
            #
            # FastMCP's StdioTransport does not explicitly set encoding='utf-8'
            # on subprocess pipes, so we configure it via environment variable
            # (PYTHONUTF8=1) and console codepage (65001) instead.

            # Create client with retry logic and offline fallback
            # Longer timeout on first run to allow uvx to download package if needed
            client = create_mcp_client_with_retry(max_retries=3, timeout_first_run=60.0)

            # Store the user prompt in the context server
            # Using session_id as thread_id to group prompts by session
            client.store_context(
                thread_id=session_id,
                source='user',
                text=prompt,
            )
            log_error('SUCCESS: Context stored successfully')

        except Exception as e:
            # Log the error for debugging with full traceback, then suppress as designed
            error_msg = f'{type(e).__name__}: {e}'
            full_traceback = traceback.format_exc()
            report_error('MCP_STORE_FAILURE', f'{error_msg}\n{full_traceback}')
            # Silent failure - don't break Claude Code workflow

        # Always exit successfully
        sys.exit(0)

    except Exception:
        # Handle all errors silently
        sys.exit(0)


if __name__ == '__main__':
    main()
