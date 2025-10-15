#!/usr/bin/env python3
"""
Claude Code Hook: Restrict File Operations to Current Working Directory

This hook prevents Edit, MultiEdit, and Write operations from modifying files
outside the current working directory. The hook dynamically determines the CWD
at runtime using Path.cwd(), making it portable and reusable across any project.

This ensures Claude Code operations remain within the project boundaries and
prevents accidental modifications to files in parent directories or other locations.

Event: PreToolUse
Matcher: Edit|MultiEdit|Write
Target: File operations (Edit, MultiEdit, Write)
Action: Block operations targeting files outside the dynamically determined CWD
"""

import json
import sys
from pathlib import Path
from typing import Any


def normalize_path(path_str: str) -> Path:
    """
    Normalize a path to an absolute, resolved path.

    This function:
    - Converts relative paths to absolute paths
    - Resolves symbolic links
    - Resolves .. and . components
    - Normalizes path separators (handles both / and \\ on Windows)

    Args:
        path_str: Path string to normalize

    Returns:
        Path: Normalized absolute Path object
    """
    try:
        # Convert to Path object and resolve to absolute path
        # resolve() also resolves symbolic links and .. components
        return Path(path_str).resolve()
    except (ValueError, OSError):
        # If path resolution fails, return as-is converted to absolute
        return Path(path_str).absolute()


def is_path_within_directory(file_path: Path, base_directory: Path) -> bool:
    """
    Check if a file path is within a base directory.

    Uses path resolution and comparison to determine if the file path
    is contained within the base directory or any of its subdirectories.

    Args:
        file_path: The file path to check
        base_directory: The base directory to check against

    Returns:
        bool: True if file_path is within base_directory, False otherwise
    """
    try:
        # Check if file_path is relative to base_directory
        # This will raise ValueError if file_path is not relative to base_directory
        file_path.relative_to(base_directory)
        return True
    except ValueError:
        # file_path is not within base_directory
        return False


def get_current_working_directory() -> Path:
    """
    Dynamically determine the current working directory at runtime.

    This function uses Path.cwd() to get the actual working directory where
    Claude Code is currently running, making the hook portable and reusable
    across any project without hardcoding specific paths.

    Returns:
        Path: Normalized current working directory path
    """
    return Path.cwd().resolve()


def check_file_operation(tool_data: dict[str, Any], cwd: Path) -> tuple[bool, str]:
    """
    Check if a file operation targets a file outside the current working directory.

    Args:
        tool_data: The tool data from the hook input
        cwd: The current working directory

    Returns:
        tuple: (should_block, error_message)
    """
    tool_name = tool_data.get('tool_name', '')
    tool_input = tool_data.get('tool_input', {})

    # Only process Edit, MultiEdit, and Write tools
    if tool_name not in ['Edit', 'Write', 'MultiEdit']:
        return False, ''

    # Extract file path from tool input
    file_path_str = tool_input.get('file_path', '')

    if not file_path_str:
        # No file path provided - should not happen but allow if it does
        return False, ''

    # Normalize both paths to absolute, resolved paths
    try:
        file_path = normalize_path(file_path_str)
    except Exception:
        # If we can't normalize the path, block it for safety
        return True, (
            f'Cannot validate file path: {file_path_str}\n'
            'File operations are restricted to the current working directory.'
        )

    # Check if the file path is within the CWD
    if not is_path_within_directory(file_path, cwd):
        # Build clear error message
        error_message = (
            f'BLOCKED: File operation outside current working directory.\n\n'
            f'Tool: {tool_name}\n'
            f'Target file: {file_path}\n'
            f'Current working directory: {cwd}\n\n'
            f'This operation is prohibited to prevent accidental modifications\n'
            f'outside the project boundaries. File operations are restricted to\n'
            f'the current working directory and its subdirectories only.\n\n'
        )
        return True, error_message

    # File is within CWD - allow the operation
    return False, ''


def main() -> None:
    """Main hook execution function."""
    try:
        # Read JSON input from stdin
        input_data = json.load(sys.stdin)

        # Extract and validate event and tool
        hook_event_name = input_data.get('hook_event_name', '')
        tool_name = input_data.get('tool_name', '')

        # Initial validation - exit silently if conditions not met
        if hook_event_name != 'PreToolUse':
            sys.exit(0)

        if tool_name not in ['Edit', 'MultiEdit', 'Write']:
            sys.exit(0)

        # Get current working directory dynamically at runtime
        cwd = get_current_working_directory()

        # Check if the operation should be blocked
        should_block, error_message = check_file_operation(input_data, cwd)

        if should_block:
            # Print error message to stderr and block with exit code 2
            print(error_message, file=sys.stderr)
            sys.exit(2)  # block action and send feedback for Claude Code

        # Operation allowed - file is within CWD
        sys.exit(0)

    except json.JSONDecodeError:
        sys.exit(0)  # Silent failure for invalid JSON

    except Exception:
        sys.exit(0)  # Silent failure for unexpected errors


if __name__ == '__main__':
    main()
