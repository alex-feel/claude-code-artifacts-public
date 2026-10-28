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

Claude Code sends idle_prompt 60 seconds after any turn ends, a manual
/compact included, whether or not background work the session started is
still running. Two opt-in keys read the session transcript to tell those
cases apart:
skip_idle_after_compaction sends nothing when the turn that just ended was
only a compaction, and report_idle_background_tasks says how many background
tasks are still running. Workflows and background agents are counted from
the counts Claude Code writes into its record of each turn end; background
shell commands, which that record does not count, are counted from their
launch and completion records, so a shell stopped from the task list in the
interface, which leaves no completion record, still counts until its launch
falls outside the scan. A turn that writes no turn-end record, such as an
interrupted turn or, with skip_idle_after_compaction off, a turn that was
only a compaction, keeps the configured text. A third opt-in key,
notification.original_message_types, shows Claude Code's own message (which
names the tool, the session, or the outcome) for the listed types.

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
are intentionally preserved. Likewise _read_transcript_tail turns an
unreadable transcript (OSError) and _parse_entry a line that is not JSON
(ValueError) into an empty result, so the notification keeps its configured
text.
"""

import asyncio
import importlib.util
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
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
    # Send no idle_prompt notification when the turn that just ended was only
    # a compaction (a manual /compact), as read from the session transcript
    'skip_idle_after_compaction': False,
    # While background tasks (workflows, background agents, skills forked
    # into the background, background shell commands) are still running,
    # idle_prompt shows notification.background_tasks_messages instead of its
    # usual text. Workflows and agents come from the counts Claude Code
    # writes into its record of the turn that just ended. Shell commands,
    # which that record does not count, come from their launch and
    # completion records in the transcript, so a shell stopped from the task
    # list in the interface, which leaves no completion record, still counts
    # until its launch falls outside the scan. A turn that writes no turn-end
    # record (an interrupted turn, or a turn that was only a compaction while
    # skip_idle_after_compaction is off) keeps the usual text.
    'report_idle_background_tasks': False,
    # Both transcript checks above read at most this many bytes from the end
    # of the transcript. A compaction, a turn-end record, or a shell launch
    # further back is not seen, and an unreadable transcript leaves the
    # notification text as configured.
    'transcript_scan_bytes': 16 * 1024 * 1024,
    'notification': {
        'title': 'Claude Code',
        'message': 'Claude is waiting for your input',
        # Per-type message overrides keyed by notification type; a type
        # without an entry falls back to 'message'
        'messages': {},
        # Notification types whose text is Claude Code's own message from the
        # hook input, for example the tool a permission prompt asks about;
        # the configured title is kept, and an empty message falls back to
        # the configured text
        'original_message_types': [],
        # idle_prompt text while background tasks are running (see
        # report_idle_background_tasks): 'one' for a single task and 'other'
        # for more, with {count} replaced by the number of tasks
        'background_tasks_messages': {
            'one': 'Claude is idle with 1 background task still running',
            'other': 'Claude is idle with {count} background tasks still running',
        },
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


_TASK_ID_PATTERN = re.compile(r'<task-id>([^<]+)</task-id>')
_TASK_NOTIFICATION_OPENING = '<task-notification>'
# Only lines holding one of these can launch or finish a background shell command
_TASK_LINE_MARKERS = (b'toolUseResult', _TASK_NOTIFICATION_OPENING.encode())
# The counts of still-running workflows and background agents (skills forked
# into the background included) that Claude Code writes into its record of a
# turn end, each left out when zero
_TURN_END_PENDING_FIELDS = ('pendingWorkflowCount', 'pendingBackgroundAgentCount')
# System entries that show a turn which writes no turn-end record of its own
# came after the last one: a compaction and a local command
_TURN_WITHOUT_RECORD_SUBTYPES = ('compact_boundary', 'local_command')
# Openings of the command entries a manual /compact writes after its
# compact_boundary that do not end the compaction turn: the /compact command
# line itself and the output of a local command
_COMPACTION_BOOKKEEPING = ('<command-name>/compact</command-name>', '<local-command-stdout>', '<local-command-stderr>')


def _read_transcript_tail(transcript_path: str, max_bytes: int) -> list[bytes]:
    """
    Read the JSONL lines among the last max_bytes bytes of a transcript.

    The window can open inside a line; what is left of that line is not a
    JSON object and parses as nothing.

    Args:
        transcript_path: Path to the session transcript Claude Code writes
        max_bytes: Upper bound on the bytes read from the end of the file

    Returns:
        The lines in file order, or an empty list when the file cannot be read
    """
    try:
        with open(transcript_path, 'rb') as transcript:
            size = transcript.seek(0, os.SEEK_END)
            transcript.seek(max(0, size - max_bytes))
            return transcript.read().splitlines()
    except OSError:
        return []


def _as_dict(value: object) -> dict[str, Any]:
    """Return a JSON value as an object, or an empty object when it is anything else."""
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _parse_entry(line: bytes) -> dict[str, Any] | None:
    """
    Parse one transcript line into its JSON object.

    Args:
        line: One JSONL line

    Returns:
        The entry, or None for a blank, partial, or non-object line
    """
    try:
        entry: object = json.loads(line)
    except ValueError:
        return None
    return cast(dict[str, Any], entry) if isinstance(entry, dict) else None


def _content_text(content: object) -> str:
    """
    Extract the text of a message content field.

    Args:
        content: A message content value, either a string or a list of blocks

    Returns:
        The string itself, or the text blocks of a list joined together
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        blocks = [_as_dict(block) for block in cast(list[object], content)]
        return ''.join(block.get('text', '') for block in blocks if block.get('type') == 'text')
    return ''


def _is_compaction_bookkeeping(text: str) -> bool:
    """Tell whether a command-entry text is the /compact command line or local command output."""
    return text.startswith(_COMPACTION_BOOKKEEPING)


def _compaction_verdict(entry: dict[str, Any]) -> bool | None:
    """
    Classify one transcript entry while reading backward from the end.

    Args:
        entry: A parsed transcript entry

    Returns:
        True for the compact_boundary that opens a compaction, False for an
        entry that shows another turn ended (an assistant message, a typed
        prompt, a task notification, another command), and None for
        bookkeeping to read past (attachments, metadata, sidechain entries,
        the compact summary, meta caveats, the /compact command and its
        output)
    """
    if entry.get('isSidechain'):
        return None
    entry_type = entry.get('type')
    if entry_type == 'assistant':
        return False
    if entry_type == 'system':
        if entry.get('subtype') == 'compact_boundary':
            return True
        if entry.get('subtype') == 'local_command':
            return None if _is_compaction_bookkeeping(_content_text(entry.get('content'))) else False
        return None
    if entry_type == 'user':
        if entry.get('isMeta') or entry.get('isCompactSummary'):
            return None
        text = _content_text(_as_dict(entry.get('message')).get('content'))
        return None if _is_compaction_bookkeeping(text) else False
    return None


def _ended_turn_was_compaction(lines: list[bytes]) -> bool:
    """
    Tell whether the last turn in the transcript was only a compaction.

    Args:
        lines: Transcript lines in file order

    Returns:
        True when reading backward reaches a compact_boundary before any
        entry that belongs to another turn
    """
    for line in reversed(lines):
        entry = _parse_entry(line)
        if entry is None:
            continue
        verdict = _compaction_verdict(entry)
        if verdict is not None:
            return verdict
    return False


def _turn_end_record(lines: list[bytes]) -> dict[str, Any] | None:
    """
    Find Claude Code's record of the turn that just ended.

    Reading backward from the end, bookkeeping (attachments, metadata, meta
    entries, sidechain entries, system entries such as the Stop hook summary
    or a recap) is read past. Any other assistant or user entry, a
    compaction, or a local command means a later turn wrote no record of its
    own, so an older turn's record is never used for it.

    Args:
        lines: Transcript lines in file order

    Returns:
        The main-session turn_duration entry of the last turn, or None
    """
    for line in reversed(lines):
        entry = _parse_entry(line)
        if entry is None or entry.get('isSidechain'):
            continue
        entry_type = entry.get('type')
        if entry_type == 'system':
            subtype = entry.get('subtype')
            if subtype == 'turn_duration':
                return entry
            if subtype in _TURN_WITHOUT_RECORD_SUBTYPES:
                return None
        elif entry_type == 'assistant' or (entry_type == 'user' and not entry.get('isMeta')):
            return None
    return None


def _pending_task_count(record: dict[str, Any]) -> int | None:
    """
    Add up the pending workflow and background agent counts of a turn-end record.

    Args:
        record: A turn_duration entry

    Returns:
        The sum, with an absent count read as zero, or None when a count is
        not a non-negative integer
    """
    total = 0
    for field in _TURN_END_PENDING_FIELDS:
        value: object = record.get(field, 0)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            return None
        total += value
    return total


def _launched_shell_id(entry: dict[str, Any]) -> str | None:
    """
    Return the task id of a shell command a main-session tool result started in the background.

    Args:
        entry: A parsed transcript entry

    Returns:
        The backgroundTaskId, or None when the entry started no background shell
    """
    if entry.get('type') != 'user' or entry.get('isSidechain'):
        return None
    task_id = _as_dict(entry.get('toolUseResult')).get('backgroundTaskId')
    return str(task_id) if task_id else None


def _finished_task_ids(entry: dict[str, Any]) -> list[str]:
    """
    Return the task ids an entry records as no longer running.

    Claude Code queues a task notification the moment a background task
    ends, however it is later delivered, and records a delivery as a user
    turn of its own, which is all a copied history carries; a TaskStop result
    object names the task it stopped.

    Args:
        entry: A parsed transcript entry

    Returns:
        The finished task ids, possibly none
    """
    entry_type = entry.get('type')
    if entry_type == 'queue-operation':
        notification = entry.get('content')
    elif entry_type == 'user' and _as_dict(entry.get('origin')).get('kind') == 'task-notification':
        notification = _as_dict(entry.get('message')).get('content')
    else:
        stopped_id = _as_dict(entry.get('toolUseResult')).get('task_id')
        return [str(stopped_id)] if stopped_id else []
    if isinstance(notification, str) and notification.startswith(_TASK_NOTIFICATION_OPENING):
        return _TASK_ID_PATTERN.findall(notification)
    return []


def _count_running_background_shells(lines: list[bytes]) -> int:
    """
    Count the background shell commands started in the transcript lines that have not finished.

    Args:
        lines: Transcript lines in file order

    Returns:
        The number of shell launches with no completion record after them
    """
    launched: set[str] = set()
    finished: set[str] = set()
    for line in lines:
        if not any(marker in line for marker in _TASK_LINE_MARKERS):
            continue
        entry = _parse_entry(line)
        if entry is None:
            continue
        task_id = _launched_shell_id(entry)
        if task_id:
            launched.add(task_id)
        else:
            finished.update(_finished_task_ids(entry))
    return len(launched - finished)


def _count_running_background_tasks(lines: list[bytes]) -> int | None:
    """
    Count the background tasks still running when the last turn ended.

    Workflows and background agents come from the counts Claude Code wrote
    into its record of that turn end; background shell commands, which that
    record does not count, come from their launch and completion records.

    Args:
        lines: Transcript lines in file order

    Returns:
        The number of running tasks, or None when the last turn left no
        usable turn-end record
    """
    record = _turn_end_record(lines)
    if record is None:
        return None
    pending = _pending_task_count(record)
    if pending is None:
        return None
    return pending + _count_running_background_shells(lines)


def _background_tasks_message(count: int, notification_config: dict[str, Any]) -> str:
    """
    Render the idle_prompt text for a number of running background tasks.

    Args:
        count: Number of running background tasks, at least 1
        notification_config: The notification section of the configuration

    Returns:
        The 'one' or 'other' text with {count} replaced by the number
    """
    default_texts: dict[str, str] = DEFAULT_CONFIG['notification']['background_tasks_messages']
    texts = _as_dict(notification_config.get('background_tasks_messages'))
    form = 'one' if count == 1 else 'other'
    template: str = texts.get(form) or default_texts[form]
    return template.replace('{count}', str(count))


def _configured_message(notification_type: str, original_message: str, notification_config: dict[str, Any]) -> str:
    """
    Choose the configured text for a notification type.

    A null title, message, or per-type message entry is treated as unset so a
    drafted config value cannot send None into the notification backends; a
    non-list original_message_types value lists nothing, so a scalar cannot
    degrade the membership check to substring matching.

    Args:
        notification_type: The incoming notification type
        original_message: Claude Code's own message from the hook input
        notification_config: The notification section of the configuration

    Returns:
        Claude Code's message when include_original_message is set or the
        type is listed in original_message_types and the message is not
        empty; otherwise the per-type message or the default message
    """
    type_messages: dict[str, str] = notification_config.get('messages') or {}
    default_message: str = notification_config.get('message') or DEFAULT_CONFIG['notification']['message']
    original_types = notification_config.get('original_message_types')
    if not isinstance(original_types, list):
        original_types = []
    use_original = notification_config.get('include_original_message', False) or notification_type in original_types
    if original_message and use_original:
        return original_message
    return type_messages.get(notification_type) or default_message


def _idle_prompt_message(transcript_path: object, config: dict[str, Any], message: str) -> str | None:
    """
    Apply the opt-in transcript checks to an idle_prompt notification.

    Args:
        transcript_path: The transcript_path field of the hook input
        config: The merged configuration
        message: The text chosen so far

    Returns:
        None when no notification is due because the turn that just ended was
        only a compaction, the background-task text while background tasks
        are still running, and message otherwise
    """
    skip_after_compaction = config.get('skip_idle_after_compaction', False)
    report_background_tasks = config.get('report_idle_background_tasks', False)
    if not (skip_after_compaction or report_background_tasks) or not isinstance(transcript_path, str) or not transcript_path:
        return message
    scan_bytes = config.get('transcript_scan_bytes')
    if not isinstance(scan_bytes, int) or scan_bytes <= 0:
        scan_bytes = DEFAULT_CONFIG['transcript_scan_bytes']
    lines = _read_transcript_tail(transcript_path, scan_bytes)
    if skip_after_compaction and _ended_turn_was_compaction(lines):
        return None
    if report_background_tasks:
        running = _count_running_background_tasks(lines)
        if running:
            notification_config = config.get('notification') or DEFAULT_CONFIG['notification']
            return _background_tasks_message(running, notification_config)
    return message


def main() -> None:
    """Main hook execution function."""
    try:
        # Load configuration (defaults merged with config file if provided)
        config_loader = _load_config_loader()
        config = config_loader.get_config_from_argv(DEFAULT_CONFIG)

        # Check if hook is enabled
        if not config.get('enabled', True):
            sys.exit(0)

        # Claude Code writes the payload as UTF-8, so it is parsed from the raw
        # bytes: the stdin text layer decodes with the locale's encoding, which on
        # Windows is the ANSI code page.
        input_data = json.load(sys.stdin.buffer)

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

        notification_config = config.get('notification', DEFAULT_CONFIG['notification'])
        title: str = notification_config.get('title') or DEFAULT_CONFIG['notification']['title']
        message = _configured_message(notification_type, input_data.get('message', ''), notification_config)
        if notification_type == 'idle_prompt':
            idle_message = _idle_prompt_message(input_data.get('transcript_path'), config, message)
            if idle_message is None:
                sys.exit(0)
            message = idle_message

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
