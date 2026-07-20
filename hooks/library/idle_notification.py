#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["pyyaml", "desktop-notifier>=6.0.0"]
# ///
"""
Desktop Notification Hook for Claude Code.

Sends a desktop notification for configured Notification event types. By
default only idle_prompt (Claude Code is waiting for user input after 60+
seconds of inactivity) triggers a notification; the notification_types config
key selects additional types such as permission_prompt, elicitation_dialog,
agent_needs_input, or agent_completed, with optional per-type messages via
the notification.messages config key.

Trigger: Notification with a matcher covering the configured types
(matcher: idle_prompt by default)

main() relies on its helpers being correct under the platform contract; only
one external-condition handler exists (json.JSONDecodeError for malformed stdin
from the Claude Code wrapper). There is no catch-all except Exception block in
main(): an unexpected exception escapes to Python's default handler, surfacing
the traceback to the operator's TUI so the underlying code-quality defect can
be fixed.

The helper functions _send_notification_async, _run_command, and
send_notification each contain a local except Exception block that converts a
real-world external failure (notification daemon unreachable, subprocess
timeout, OS API missing) into a domain-meaningful control-flow signal: either
a False sentinel that the caller checks before chaining to the next fallback,
or a pass-through that lets control flow to the CLI fallback. These are not
hook-internal defect masks; they implement the notification fallback chain and
are intentionally preserved.
"""

import asyncio
import importlib.util
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any


def _load_config_loader() -> ModuleType:
    """Dynamically load hook_config_loader from the same directory."""
    loader_path = Path(__file__).parent / 'hook_config_loader.py'
    spec = importlib.util.spec_from_file_location('hook_config_loader', loader_path)
    if spec is None or spec.loader is None:
        raise ImportError(f'Cannot load hook_config_loader from {loader_path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Default configuration - used when no config file provided
DEFAULT_CONFIG: dict[str, Any] = {
    'enabled': True,
    # Notification types that trigger a desktop notification; any other type
    # exits silently, even when the hook registration matcher is broader. A
    # null or non-list value falls back to this default; an explicit empty
    # list disables all notifications.
    # Claude Code defines: permission_prompt (Claude needs approval),
    # idle_prompt (Claude is waiting for the next prompt), auth_success,
    # elicitation_dialog (an MCP server awaits form input),
    # elicitation_complete, elicitation_response, agent_needs_input (a local
    # background session is blocked on input), agent_completed (a local
    # background session finished or failed)
    'notification_types': ['idle_prompt'],
    'notification': {
        'title': 'Claude Code',
        'message': 'Claude is waiting for your input',
        # Per-type message overrides keyed by notification type; a type
        # without an entry falls back to 'message'
        'messages': {},
        'app_name': 'Claude Code',
        # Use default system sound for notifications
        'sound': True,
        # Timeout in milliseconds (0 = system default)
        # Note: Only works on Linux; Windows and macOS ignore this (system-controlled)
        'timeout_ms': 7000,
        # Path to custom icon file (optional)
        # Supported on Linux and Windows; ignored on macOS
        # Use absolute path or path relative to hooks directory
        'icon_path': None,
        # Use original message from Claude Code instead of custom message
        'include_original_message': False,
    },
    'fallback': {
        # Enable CLI fallback if desktop-notifier fails
        'enabled': True,
        # Timeout for CLI commands in seconds
        'timeout_seconds': 3.0,
    },
}


def _resolve_icon_path(icon_path_str: str | None) -> Path | None:
    """
    Resolve icon path from configuration.

    Handles both absolute paths and paths relative to the hooks directory.
    Returns None if path is not specified or file does not exist.

    Args:
        icon_path_str: Icon path string from configuration

    Returns:
        Resolved Path object if icon exists, None otherwise
    """
    if not icon_path_str:
        return None

    icon_path = Path(icon_path_str).expanduser()
    if not icon_path.is_absolute():
        # Resolve relative to hooks directory
        icon_path = Path(__file__).parent / icon_path

    if icon_path.exists():
        return icon_path

    return None


async def _send_notification_async(title: str, message: str, config: dict[str, Any]) -> bool:
    """
    Send notification using desktop-notifier library.

    Supports custom icons (Linux, Windows) and timeout (Linux only).
    On macOS, icons are determined by the calling application and cannot be changed.
    On Windows and macOS, timeout is controlled by system settings.

    Args:
        title: Notification title
        message: Notification message
        config: Configuration dictionary

    Returns:
        True if notification was sent successfully, False otherwise
    """
    try:
        from desktop_notifier import DEFAULT_SOUND
        from desktop_notifier import DesktopNotifier
        from desktop_notifier import Icon
    except ImportError:
        return False

    notification_config = config.get('notification', DEFAULT_CONFIG['notification'])
    app_name = notification_config.get('app_name', DEFAULT_CONFIG['notification']['app_name'])
    use_sound = notification_config.get('sound', DEFAULT_CONFIG['notification']['sound'])
    timeout_ms = notification_config.get('timeout_ms', DEFAULT_CONFIG['notification']['timeout_ms'])
    icon_path_str = notification_config.get('icon_path', DEFAULT_CONFIG['notification']['icon_path'])

    # Resolve icon path if specified
    app_icon = None
    icon_path = _resolve_icon_path(icon_path_str)
    if icon_path is not None:
        app_icon = Icon(path=icon_path)

    notifier = DesktopNotifier(app_name=app_name, app_icon=app_icon)

    try:
        sound = DEFAULT_SOUND if use_sound else None
        # Timeout parameter only works on Linux; ignored on Windows/macOS
        # -1 means use system default
        timeout = timeout_ms if timeout_ms > 0 else -1
        await notifier.send(title=title, message=message, sound=sound, timeout=timeout)
        return True
    except Exception:
        return False


def _notify_fallback_cli(title: str, message: str, config: dict[str, Any]) -> bool:
    """
    Send notification using platform-specific CLI fallback with icon/timeout support.

    Platform support for icons and timeout:
    - Linux: icon via notify-send -i, timeout via notify-send -t
    - Windows: icon via BurntToast -AppLogo or SnoreToast -p
    - macOS: No icon or timeout support via AppleScript/terminal-notifier

    Args:
        title: Notification title
        message: Notification message
        config: Configuration dictionary

    Returns:
        True if notification was sent successfully, False otherwise
    """
    fallback_config = config.get('fallback', DEFAULT_CONFIG['fallback'])
    if not fallback_config.get('enabled', DEFAULT_CONFIG['fallback']['enabled']):
        return False

    notification_config = config.get('notification', DEFAULT_CONFIG['notification'])
    timeout_s = fallback_config.get('timeout_seconds', DEFAULT_CONFIG['fallback']['timeout_seconds'])
    timeout_ms = notification_config.get('timeout_ms', 0)
    icon_path_str = notification_config.get('icon_path')
    icon_path = _resolve_icon_path(icon_path_str)

    system = platform.system().lower()

    if system == 'darwin':
        # macOS: Use AppleScript via osascript
        # Note: Custom icons and timeout are NOT supported on macOS
        if shutil.which('osascript'):
            script = f'display notification {shlex.quote(message)} with title {shlex.quote(title)}'
            return _run_command(['osascript', '-e', script], timeout_s)

        # Fallback: terminal-notifier if installed
        if shutil.which('terminal-notifier'):
            return _run_command(['terminal-notifier', '-title', title, '-message', message], timeout_s)

        return False

    if system == 'linux':
        # Linux: Use notify-send (libnotify) with icon and timeout support
        if shutil.which('notify-send'):
            cmd = ['notify-send', title, message]
            # Add timeout if specified (notify-send uses milliseconds)
            if timeout_ms > 0:
                cmd.extend(['-t', str(timeout_ms)])
            # Add icon if specified
            if icon_path is not None:
                cmd.extend(['-i', str(icon_path)])
            return _run_command(cmd, timeout_s)
        return False

    if system == 'windows':
        # Windows: Use PowerShell with BurntToast module
        # Note: Timeout is NOT supported on Windows (system-controlled)
        shell = 'pwsh' if shutil.which('pwsh') else 'powershell'
        if shutil.which(shell):
            # Escape single quotes for PowerShell
            escaped_title = title.replace("'", "''")
            escaped_message = message.replace("'", "''")

            # Build BurntToast command with optional icon
            if icon_path is not None:
                escaped_icon = str(icon_path).replace("'", "''")
                ps_cmd = f"New-BurntToastNotification -Text '{escaped_title}','{escaped_message}' -AppLogo '{escaped_icon}'"
            else:
                ps_cmd = f"New-BurntToastNotification -Text '{escaped_title}','{escaped_message}'"

            if _run_command([shell, '-NoProfile', '-Command', ps_cmd], timeout_s):
                return True

        # Fallback: SnoreToast if installed
        if shutil.which('snoretoast'):
            snore_cmd = ['snoretoast', '-t', title, '-m', message]
            # Add icon if specified (SnoreToast uses -p for image)
            if icon_path is not None:
                snore_cmd.extend(['-p', str(icon_path)])
            return _run_command(snore_cmd, timeout_s)

        return False

    return False


def _run_command(argv: list[str], timeout_s: float) -> bool:
    """
    Execute a command with timeout.

    Args:
        argv: Command and arguments
        timeout_s: Timeout in seconds

    Returns:
        True if command succeeded, False otherwise
    """
    try:
        subprocess.run(
            argv,
            check=True,
            timeout=timeout_s,
            capture_output=True,
        )
        return True
    except Exception:
        return False


def send_notification(title: str, message: str, config: dict[str, Any]) -> bool:
    """
    Send a desktop notification with fallback support.

    Tries desktop-notifier first, then falls back to CLI methods.

    Args:
        title: Notification title
        message: Notification message
        config: Configuration dictionary

    Returns:
        True if notification was sent successfully, False otherwise
    """
    # Try desktop-notifier first (async)
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_send_notification_async(title, message, config))
            if result:
                return True
        finally:
            loop.close()
    except Exception:
        pass

    # Fall back to CLI methods
    return _notify_fallback_cli(title, message, config)


def main() -> None:
    """Main hook execution function."""
    try:
        # Load configuration (defaults merged with config file if provided)
        config_loader = _load_config_loader()
        config = config_loader.get_config_from_argv(DEFAULT_CONFIG)

        # Check if hook is enabled
        if not config.get('enabled', True):
            sys.exit(0)

        # Read input from stdin
        input_data = json.load(sys.stdin)

        # Verify this is a Notification event
        hook_event_name = input_data.get('hook_event_name', '')
        if hook_event_name != 'Notification':
            sys.exit(0)

        # Verify this notification type is configured to notify. A null or
        # non-list notification_types value is treated as unset (falling back
        # to the default) so a partially edited config file cannot crash the
        # hook or degrade the membership check to substring matching; an
        # explicit empty list disables all notifications.
        notification_type = input_data.get('notification_type', '')
        allowed_types = config.get('notification_types')
        if not isinstance(allowed_types, list):
            allowed_types = DEFAULT_CONFIG['notification_types']
        if notification_type not in allowed_types:
            sys.exit(0)

        # Get notification configuration; a null title, message, or per-type
        # message entry is treated as unset so a drafted config value cannot
        # send None into the notification backends
        notification_config = config.get('notification', DEFAULT_CONFIG['notification'])
        title: str = notification_config.get('title') or DEFAULT_CONFIG['notification']['title']
        type_messages: dict[str, str] = notification_config.get('messages') or {}
        default_message: str = notification_config.get('message') or DEFAULT_CONFIG['notification']['message']
        message = type_messages.get(notification_type) or default_message

        # Optionally include the original message from Claude Code
        original_message = input_data.get('message', '')
        if original_message and notification_config.get('include_original_message', False):
            message = original_message

        # Send notification
        send_notification(title, message, config)

        # Terminate without interpreter finalization: after a dispatch, native
        # notification backends (WinRT COM on Windows) can abort the process
        # during teardown, turning a delivered notification into a nonzero
        # exit that Claude Code reports as a hook failure. os._exit skips that
        # teardown so the exit code always reflects the dispatch outcome, and
        # notification failure never blocks Claude Code either.
        os._exit(0)

    except json.JSONDecodeError:
        # Malformed stdin from the Claude Code wrapper: external contract
        # violation, not a hook-internal defect. Exit 0 because the hook contract
        # requires non-blocking on stdin corruption (the model has no actionable
        # feedback to give).
        sys.exit(0)


if __name__ == '__main__':
    main()
