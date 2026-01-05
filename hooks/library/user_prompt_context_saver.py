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

# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#   "fastmcp>=2.10.5",
#   "pyyaml",
# ]
# ///

import asyncio
import ctypes
import importlib.util
import io
import json
import os
import re
import sys
import tempfile
import time
import traceback
from collections.abc import Coroutine
from datetime import UTC
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING
from typing import Any
from typing import cast


def _load_config_loader() -> ModuleType:
    """Dynamically load hook_config_loader from the same directory."""
    loader_path = Path(__file__).parent / 'hook_config_loader.py'
    spec = importlib.util.spec_from_file_location('hook_config_loader', loader_path)
    if spec is None or spec.loader is None:
        raise ImportError(f'Cannot load hook_config_loader from {loader_path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Try to import FastMCP - track availability
_fastmcp_import_error: Exception | None = None
try:
    from fastmcp import Client
except ImportError as e:
    _fastmcp_import_error = e
    if TYPE_CHECKING:
        from fastmcp import Client
    else:

        class _DummyClient:
            """Dummy Client class for when FastMCP is unavailable."""

        Client = _DummyClient


# Check if logging is enabled (module-level check, executed once)
_LOGGING_ENABLED = os.environ.get('CLAUDE_HOOK_DEBUG_ENABLED', '').lower() in ('1', 'true', 'yes')

# Message size limits for Windows subprocess pipe buffers
# Windows pipes typically have 64KB buffer, use conservative limits
_MAX_MESSAGE_SIZE = int(os.environ.get('CLAUDE_HOOK_MAX_MESSAGE_SIZE', '32768'))  # 32KB default
_CHUNK_SIZE = int(os.environ.get('CLAUDE_HOOK_CHUNK_SIZE', '30000'))  # 30KB default for chunks
_JSON_OVERHEAD = 500  # Estimated bytes for JSON structure (thread_id, source, etc.)

# Default configuration - used when no config file provided
# Maintains backward compatibility with original behavior
DEFAULT_CONFIG: dict[str, Any] = {
    'enabled': True,
    'prebuilt_commands': [
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
    ],
    'message_limits': {
        'max_message_size': 32768,
        'chunk_size': 30000,
        'json_overhead': 500,
    },
    'session_id': {
        'max_retries': 3,
        'fallback_value': 'current-session',
    },
    'mcp_client': {
        'max_retries': 3,
        'timeout_first_run': 60.0,
        'timeout_normal': 60.0,
    },
    'mcp_server': {
        'command': 'uvx',
        'python_version': '3.12',
        'package': 'mcp-context-server[semantic-search]',
        'entry_point': 'mcp-context-server',
    },
}


def _get_log_file() -> Path:
    """
    Get log file location with multiple fallbacks for reliability.

    Fallback chain:
    1. CLAUDE_HOOK_DEBUG_FILE environment variable
    2. {CLAUDE_PROJECT_DIR}/.claude/.hook_debug.log
    3. {HOME}/.claude/hook_logs/user_prompt_context_saver.log
    4. {TEMP}/claude_hook_user_prompt_context_saver.log

    Returns:
        Path to the log file (guaranteed to return a valid path)
    """
    # Fallback 1: Explicit debug file location
    if os.environ.get('CLAUDE_HOOK_DEBUG_FILE'):
        return Path(os.environ['CLAUDE_HOOK_DEBUG_FILE'])

    # Fallback 2: Project directory
    if os.environ.get('CLAUDE_PROJECT_DIR'):
        project_dir = Path(os.environ['CLAUDE_PROJECT_DIR'])
        claude_dir = project_dir / '.claude'
        try:
            claude_dir.mkdir(parents=True, exist_ok=True)
            return claude_dir / '.hook_debug.log'
        except Exception:
            pass  # Fall through to next fallback

    # Fallback 3: User home directory
    try:
        home = Path.home()
        log_dir = home / '.claude' / 'hook_logs'
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir / 'user_prompt_context_saver.log'
    except Exception:
        pass  # Fall through to final fallback

    # Fallback 4: System temp directory (always works)
    temp_dir = Path(tempfile.gettempdir())
    return temp_dir / 'claude_hook_user_prompt_context_saver.log'


# Initialize log file IMMEDIATELY
_LOG_FILE = _get_log_file()


def log_always(message: str, level: str = 'INFO') -> None:
    """
    Log message with guaranteed write when logging is enabled (never raises exceptions).

    Logging is CONDITIONAL based on CLAUDE_HOOK_DEBUG_ENABLED environment variable.
    If not set or set to values other than "1", "true", "yes" → NO logs written.

    This function provides conditional logging that:
    - Only writes logs when CLAUDE_HOOK_DEBUG_ENABLED is set to "1", "true", or "yes"
    - Never depends on CLAUDE_PROJECT_DIR environment variable
    - Never breaks the hook (all exceptions caught silently)
    - Uses multiple fallback locations for reliability when enabled
    - Provides timestamp and log level for each message

    Args:
        message: The message to log
        level: Log level (INFO, ERROR, DEBUG, etc.)
    """
    # Early exit if logging not enabled
    if not _LOGGING_ENABLED:
        return

    try:
        with _LOG_FILE.open('a', encoding='utf-8') as f:
            timestamp = datetime.now(tz=UTC).isoformat()
            f.write(f'{timestamp} [{level}] {message}\n')
    except Exception:
        # Even logging failures are silent - never break the hook
        pass


# Log script start IMMEDIATELY
log_always('=' * 80)
log_always('SCRIPT START')
log_always(f'sys.argv: {sys.argv}')
log_always(f'cwd: {os.getcwd()}')
log_always(f'Python version: {sys.version}')
log_always(f'Python executable: {sys.executable}')
log_always(f"CLAUDE_PROJECT_DIR: {os.environ.get('CLAUDE_PROJECT_DIR', 'NOT SET')}")
log_always(f"CLAUDE_HOOK_DEBUG_FILE: {os.environ.get('CLAUDE_HOOK_DEBUG_FILE', 'NOT SET')}")
log_always(f'Log file location: {_LOG_FILE}')
log_always(f'stdin isatty: {sys.stdin.isatty()}')

# Check FastMCP availability
if _fastmcp_import_error is not None:
    log_always(f'FastMCP not available: {_fastmcp_import_error}', level='ERROR')
    log_always('Exiting: FastMCP import failed')
    sys.exit(0)

log_always('FastMCP available')


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
    log_always('Configuring Windows UTF-8 encoding')
    if sys.platform != 'win32':
        log_always('Not Windows platform, skipping UTF-8 setup')
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

        log_always('UTF-8 mode configured for Windows console')
    except Exception as e:
        # Non-fatal: log error but continue
        # Hook should still work even if UTF-8 setup fails
        error_msg = f'Failed to set Windows UTF-8 mode: {e}'
        log_always(error_msg, level='ERROR')


def log_error(message: str) -> None:
    """
    Log errors to a debug file with default location for better diagnostics.

    Uses CLAUDE_HOOK_DEBUG_FILE environment variable to specify log location.
    If not set, defaults to .claude/.hook_debug.log in the project directory.

    This function is kept for backward compatibility with existing code that
    uses it, but internally delegates to log_always for guaranteed logging.

    Logging is CONDITIONAL based on CLAUDE_HOOK_DEBUG_ENABLED environment variable.

    Args:
        message: The error message to log
    """
    # Use log_always for guaranteed logging
    log_always(message, level='INFO')

    # Early exit if logging not enabled
    if not _LOGGING_ENABLED:
        return

    # Also try old logging path for compatibility
    debug_file = os.environ.get('CLAUDE_HOOK_DEBUG_FILE')

    # Default to project-local debug log if not specified
    if not debug_file:
        project_dir = os.environ.get('CLAUDE_PROJECT_DIR')
        if project_dir:
            debug_file = str(Path(project_dir) / '.claude' / '.hook_debug.log')

    if debug_file and debug_file != str(_LOG_FILE):
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

    Logging is CONDITIONAL based on CLAUDE_HOOK_DEBUG_ENABLED environment variable.

    Args:
        error_type: Category of error (e.g., 'UVX_FAILURE', 'SESSION_ID_READ')
        error_msg: Detailed error message
    """
    full_msg = f'{error_type}: {error_msg}'
    log_always(full_msg, level='ERROR')

    # Early exit if logging not enabled
    if not _LOGGING_ENABLED:
        return

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

    def __init__(self, server_command: list[str] | str, timeout: float = 60.0) -> None:
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

    def _calculate_message_size(self, thread_id: str, source: str, text: str) -> int:
        """
        Calculate the JSON message size in bytes.

        Args:
            thread_id: The thread/session identifier
            source: The source of the context
            text: The text content to store

        Returns:
            Size of the JSON message in bytes
        """
        test_json = json.dumps({'thread_id': thread_id, 'source': source, 'text': text})
        return len(test_json.encode('utf-8'))

    async def _store_single_context_async(
        self,
        thread_id: str,
        source: str,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Store a single context message asynchronously using the MCP server.

        Args:
            thread_id: The thread/session identifier
            source: The source of the context (always "user" for this hook)
            text: The prompt text to store
            metadata: Optional metadata to include with the context

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

            # Build call parameters
            params: dict[str, Any] = {
                'thread_id': thread_id,
                'source': source,
                'text': normalized_text,
            }
            if metadata:
                params['metadata'] = metadata

            # Call the store_context tool on the MCP server with proper typing
            return cast(
                dict[str, Any],
                await client.call_tool('store_context', params),
            )

    async def _store_context_async(
        self,
        thread_id: str,
        source: str,
        text: str,
    ) -> dict[str, Any]:
        """
        Store context asynchronously using the MCP server with automatic chunking.

        This method handles large messages by splitting them into chunks when they
        exceed the Windows subprocess pipe buffer limit (~64KB). Messages are split
        at safe boundaries to avoid breaking UTF-8 encoding.

        Args:
            thread_id: The thread/session identifier
            source: The source of the context (always "user" for this hook)
            text: The prompt text to store

        Returns:
            The server response as a dictionary
        """
        # Calculate message size to check if chunking is needed
        message_size = self._calculate_message_size(thread_id, source, text)
        log_always(f'Message size: {len(text)} chars, {message_size} bytes (limit: {_MAX_MESSAGE_SIZE} bytes)')

        # If message is small enough, send directly
        if message_size <= _MAX_MESSAGE_SIZE:
            log_always('Message size within limits, sending directly')
            return await self._store_single_context_async(thread_id, source, text)

        # Message is too large, need to chunk it
        log_always(
            f'Message too large ({message_size} bytes > {_MAX_MESSAGE_SIZE} bytes), chunking required',
            level='WARN',
        )

        # Calculate safe chunk size (account for JSON overhead and metadata)
        safe_chunk_size = _CHUNK_SIZE
        chunks: list[str] = []

        # Split text into chunks
        for i in range(0, len(text), safe_chunk_size):
            chunk = text[i : i + safe_chunk_size]
            chunks.append(chunk)

        log_always(f'Split message into {len(chunks)} chunks of ~{safe_chunk_size} bytes each')

        # Store each chunk with metadata indicating chunk info
        results: list[dict[str, Any]] = []
        for idx, chunk in enumerate(chunks):
            chunk_num = idx + 1
            log_always(f'Storing chunk {chunk_num}/{len(chunks)} ({len(chunk)} chars)')

            # Add metadata to track chunks
            metadata = {
                'chunk': chunk_num,
                'total_chunks': len(chunks),
                'chunk_size': len(chunk),
                'is_chunked': True,
            }

            try:
                result = await self._store_single_context_async(thread_id, source, chunk, metadata=metadata)
                results.append(result)
                log_always(f'Chunk {chunk_num}/{len(chunks)} stored successfully')
            except Exception as e:
                log_always(f'Failed to store chunk {chunk_num}/{len(chunks)}: {e}', level='ERROR')
                # Continue with other chunks even if one fails
                error_result: dict[str, Any] = {'error': str(e), 'chunk': chunk_num}
                results.append(error_result)

        # Return summary of chunked storage
        successful_chunks = [r for r in results if 'error' not in r]
        failed_chunks = [r for r in results if 'error' in r]

        return {
            'success': True,
            'chunked': True,
            'total_chunks': len(chunks),
            'chunks_stored': len(successful_chunks),
            'chunks_failed': len(failed_chunks),
            'results': results,
        }

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


def is_prebuilt_slash_command(prompt: str, config: dict[str, Any]) -> bool:
    """
    Check if a prompt is a pre-built slash command that should be skipped.

    Pre-built slash commands are built-in Claude Code commands that don't need
    context saving as they are system-level operations.

    Args:
        prompt: The user prompt to check
        config: Configuration dictionary with prebuilt_commands list

    Returns:
        True if the prompt is a pre-built slash command, False otherwise
    """
    # Get prebuilt commands from config
    prebuilt_commands = set(config.get('prebuilt_commands', DEFAULT_CONFIG['prebuilt_commands']))

    # Pattern to match slash commands at the start of a prompt
    # Matches: /command or /command with args
    # Uses \S+ to match any non-whitespace characters (handles underscores, hyphens, numbers, etc.)
    slash_command_pattern = re.compile(r'^/(\S+)(?:\s|$)')

    match = slash_command_pattern.match(prompt.strip())
    if not match:
        return False

    command_name = match.group(1).lower()
    return command_name in prebuilt_commands


def read_session_id(project_dir: str, config: dict[str, Any]) -> str:
    """
    Read the current session ID from the .claude/.session_id file with retry logic.

    Implements exponential backoff retry to handle file locking and race conditions
    on Windows where Claude Code might still be writing the session ID file.

    If the session ID file is unavailable, empty, or unreadable after all retry
    attempts, returns fallback value from config to ensure context storage continues.

    Args:
        project_dir: The Claude project directory path
        config: Configuration dictionary with session_id settings

    Returns:
        The session ID string if found, or fallback value from config
    """
    session_config = config.get('session_id', DEFAULT_CONFIG['session_id'])
    max_retries: int = session_config.get('max_retries', 3)
    fallback_value: str = session_config.get('fallback_value', 'current-session')

    session_id_file = Path(project_dir) / '.claude' / '.session_id'
    log_always(f'Reading session ID from: {session_id_file}')

    if not session_id_file.exists():
        log_always(f'Session ID file does not exist, using fallback: {fallback_value}')
        return fallback_value

    for attempt in range(max_retries):
        try:
            session_id = session_id_file.read_text(encoding='utf-8').strip()
            if session_id:
                if attempt > 0:
                    log_always(f'Session ID read succeeded on attempt {attempt + 1}/{max_retries}')
                log_always(f'Session ID: {session_id}')
                return session_id
            report_error(
                'SESSION_ID_READ',
                f'Session ID file empty (attempt {attempt + 1}/{max_retries}), will use fallback if all attempts fail',
            )
        except OSError as e:
            error_msg = f'Failed to read session ID (attempt {attempt + 1}/{max_retries}): {e}'
            if attempt < max_retries - 1:
                log_always(error_msg, level='ERROR')
                time.sleep(0.1 * (2**attempt))  # Exponential backoff: 100ms, 200ms, 400ms
            else:
                report_error('SESSION_ID_READ', error_msg)

    log_always(f'All session ID read attempts failed, using fallback: {fallback_value}')
    return fallback_value


def create_mcp_client_with_retry(config: dict[str, Any]) -> SyncMCPClient:
    """
    Create MCP client with retry logic and offline fallback for uvx reliability.

    Implements exponential backoff retry to handle uvx package installation timing,
    network failures, and cache invalidation issues. Falls back to offline mode
    if network is unavailable.

    Args:
        config: Configuration dictionary with mcp_client and mcp_server settings

    Returns:
        Configured SyncMCPClient instance

    Raises:
        RuntimeError: If all retry attempts fail
    """
    mcp_config = config.get('mcp_client', DEFAULT_CONFIG['mcp_client'])
    server_config = config.get('mcp_server', DEFAULT_CONFIG['mcp_server'])

    max_retries: int = mcp_config.get('max_retries', 3)
    timeout_first_run: float = mcp_config.get('timeout_first_run', 60.0)
    timeout_normal: float = mcp_config.get('timeout_normal', 60.0)

    # Build MCP server command from config
    server_command: str = server_config.get('command', 'uvx')
    python_version: str = server_config.get('python_version', '3.12')
    package: str = server_config.get('package', 'mcp-context-server[semantic-search]')
    entry_point: str = server_config.get('entry_point', 'mcp-context-server')

    log_always('Creating MCP client with retry logic')
    last_error: Exception | None = None
    attempts = 0

    while attempts < max_retries:
        try:
            # Use uvx with semantic-search extra for embedding support
            # The [semantic-search] extra includes required dependencies:
            # - ollama client for embedding generation
            # - numpy for vector operations
            # - sqlite-vec for vector similarity search
            mcp_server_command = [
                server_command,
                '--python',
                python_version,
                '--with',
                package,
                entry_point,
            ]
            # Longer timeout for first run (package download), standard timeout for retries
            timeout = timeout_first_run if attempts == 0 else timeout_normal
            log_always(f'Attempt {attempts + 1}/{max_retries}: Creating MCP client (timeout={timeout}s)')
            client = SyncMCPClient(mcp_server_command, timeout=timeout)

            # Test connectivity with a simple operation (will raise if connection fails)
            # Note: We don't actually test here to avoid extra overhead
            # The connection will be tested when store_context is called

            if attempts > 0:
                log_always(f'MCP client created successfully on attempt {attempts + 1}/{max_retries}')
            else:
                log_always('MCP client created successfully')

            return client

        except Exception as e:
            last_error = e
            attempts += 1
            error_msg = f'Failed to create MCP client (attempt {attempts}/{max_retries}): {type(e).__name__}: {e}'

            if attempts < max_retries:
                # Try offline fallback on subsequent attempts
                if attempts > 1:
                    try:
                        log_always(f'{error_msg}, trying offline mode')
                        # Use offline mode with semantic-search extra (requires prior uvx cache)
                        mcp_server_command = [
                            server_command,
                            '--python',
                            python_version,
                            '--with',
                            package,
                            '--offline',
                            entry_point,
                        ]
                        client = SyncMCPClient(mcp_server_command, timeout=timeout_normal)
                        log_always('MCP client created successfully in offline mode')
                        return client
                    except Exception as offline_error:
                        log_always(
                            f'Offline mode failed: {type(offline_error).__name__}: {offline_error}',
                            level='ERROR',
                        )

                # Exponential backoff
                log_always(error_msg, level='ERROR')
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
    log_always('Entering main() function')
    start_time = datetime.now(tz=UTC)

    try:
        # Load configuration (defaults merged with config file if provided)
        try:
            config_loader = _load_config_loader()
            config: dict[str, Any] = config_loader.get_config_from_argv(DEFAULT_CONFIG)
        except Exception:
            # If config loading fails, use defaults
            config = DEFAULT_CONFIG.copy()

        # Check if hook is enabled
        if not config.get('enabled', True):
            log_always('Hook disabled via config, exiting')
            sys.exit(0)

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
        log_always('Reconfiguring stdin for UTF-8')
        reconfigure_method = getattr(sys.stdin, 'reconfigure', None)
        if reconfigure_method is not None:
            # Python 3.7+ has reconfigure() method on TextIOWrapper
            try:
                reconfigure_method(encoding='utf-8')
                log_always('stdin reconfigured to UTF-8 via reconfigure()')
                log_error('Git Bash compatibility: stdin reconfigured to UTF-8')
            except OSError as e:
                error_msg = f'stdin reconfigure failed: {e}'
                log_always(error_msg, level='ERROR')
                log_error(f'Git Bash compatibility: {error_msg}')
        else:
            # Fallback for Python < 3.7 or if reconfigure() not available
            try:
                sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8')
                log_always('stdin wrapped with UTF-8 TextIOWrapper')
                log_error('Git Bash compatibility: stdin wrapped with UTF-8 TextIOWrapper')
            except Exception as e:
                error_msg = f'stdin UTF-8 fix failed: {e}'
                log_always(error_msg, level='ERROR')
                log_error(f'Git Bash compatibility: {error_msg}')

        # Read input from stdin
        log_always('Reading stdin data')
        try:
            input_data = json.load(sys.stdin)
            log_always(f'stdin data keys: {list(input_data.keys())}')
        except json.JSONDecodeError as e:
            log_always(f'JSON decode error: {e}', level='ERROR')
            log_always('Exiting: Invalid JSON from stdin')
            sys.exit(0)
        except Exception as e:
            log_always(f'Error reading stdin: {type(e).__name__}: {e}', level='ERROR')
            log_always('Exiting: Failed to read stdin')
            sys.exit(0)

        # Extract key fields
        hook_event_name = input_data.get('hook_event_name', '')
        log_always(f'hook_event_name: {hook_event_name}')

        # Validate this is a UserPromptSubmit event
        if hook_event_name != 'UserPromptSubmit':
            log_always(f'Skipping: Event type is {hook_event_name}, not UserPromptSubmit')
            sys.exit(0)

        # Extract prompt from input data (UserPromptSubmit has prompt directly)
        prompt = input_data.get('prompt', '')
        log_always(f'Prompt length: {len(prompt)} characters')
        if not prompt:
            # No prompt to save
            log_always('Skipping: Empty prompt')
            sys.exit(0)

        # Check if this is a pre-built slash command that should be skipped
        if is_prebuilt_slash_command(prompt, config):
            # Skip pre-built slash commands
            log_always('Skipping: Pre-built slash command detected')
            sys.exit(0)

        # Get Claude project directory
        claude_project_dir = os.environ.get('CLAUDE_PROJECT_DIR')
        log_always(f'CLAUDE_PROJECT_DIR for context save: {claude_project_dir}')
        if not claude_project_dir:
            # No project directory, can't proceed
            log_always('Exiting: CLAUDE_PROJECT_DIR not set', level='ERROR')
            sys.exit(0)

        # Read session ID (always returns a valid string, using fallback from config)
        session_id = read_session_id(claude_project_dir, config)

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
            client = create_mcp_client_with_retry(config)

            # Store the user prompt in the context server
            # Using session_id as thread_id to group prompts by session
            log_always('Storing context in MCP server')
            client.store_context(
                thread_id=session_id,
                source='user',
                text=prompt,
            )
            log_always('SUCCESS: Context stored successfully')

        except Exception as e:
            # Log the error for debugging with full traceback, then suppress as designed
            error_msg = f'{type(e).__name__}: {e}'
            full_traceback = traceback.format_exc()

            # Check for specific error patterns related to pipe buffer issues
            error_str = str(e).lower()
            error_context = ''

            if 'broken pipe' in error_str:
                error_context = ' (Message likely too large for subprocess pipe buffer)'
            elif 'timeout' in error_str:
                error_context = ' (Consider increasing timeout for large messages via CLAUDE_HOOK_MCP_TIMEOUT)'
            elif '[errno 32]' in error_str or 'epipe' in error_str:
                error_context = ' (Subprocess pipe broken - message size may exceed buffer capacity)'
            elif 'buffer' in error_str:
                error_context = ' (Buffer-related error - message may be too large)'

            log_always(f'MCP store failure: {error_msg}{error_context}', level='ERROR')
            log_always(f'Traceback:\n{full_traceback}', level='ERROR')
            report_error('MCP_STORE_FAILURE', f'{error_msg}{error_context}\n{full_traceback}')
            # Silent failure - don't break Claude Code workflow

        # Always exit successfully
        end_time = datetime.now(tz=UTC)
        duration = (end_time - start_time).total_seconds()
        log_always(f'Execution completed in {duration:.3f} seconds')
        sys.exit(0)

    except Exception as e:
        # Handle all errors silently but log them
        error_msg = f'Unexpected error in main(): {type(e).__name__}: {e}'
        full_traceback = traceback.format_exc()
        log_always(error_msg, level='ERROR')
        log_always(f'Traceback:\n{full_traceback}', level='ERROR')
        sys.exit(0)


if __name__ == '__main__':
    main()
