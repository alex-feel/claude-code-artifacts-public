#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["pyyaml"]
# ///
"""
Context compact advisor hook for Claude Code.

Once the session's context-window usage reaches a configured severity, injects
an advisory into the main agent's context whose duty lasts until the context is
compacted: keep working at full quality and full scope, and at every natural
milestone (a unit of work or a phase finished, a change landed, a pause while
waiting on background work) first save the full work state durably, re-saving
whatever changed since the previous save, and only then end the reply with a
one-line recommendation to run /compact, set apart as a Markdown blockquote.
Work in progress is never interrupted for it. The recommendation repeats at
every milestone because the user may miss any single one, and saving first lets
the work resume without loss after the compaction.

Hook events carry no context-usage figures, so this hook reads the per-session
snapshot the status line writes when its context_snapshot feature is enabled:
<snapshot dir>/<session_id>.json, whose 'severity' field (ok, warn, or crit) is
resolved by the status line's own context thresholds. The advisor therefore
fires exactly when the status line reaches the chosen severity and carries no
thresholds of its own that could drift from it. The snapshot directory defaults
to <config dir>/state/context-usage, where the config dir is $CLAUDE_CONFIG_DIR
when set and ~/.claude otherwise -- the same default the status line uses.

Delivery: the full advisory is injected once per escalation. The file
<session_id>.state.json in the snapshot directory exists from the advisory
until the advisor re-arms; it is created with an exclusive create, so
concurrent hook processes (parallel tool calls) inject the full advisory at
most once. While that file exists and the recorded severity is at or above the
configured level, every UserPromptSubmit injects a short reminder instead, so
the duty is fresh at the start of every turn the model answers, including turns
opened by task notifications. Tool events never repeat anything. Setting
remind_each_turn to false restores a single advisory per escalation.

Re-arming: the state file is deleted only when the recorded severity is ok
(below the status line's warn band) or null, which the status line records
while the session has no usage reading (before its first response, and right
after /compact until the next response). A warn reading never re-arms, whatever
the configured level, so usage that falls from crit back into the warn band and
climbs again without a compaction continues the same escalation instead of
starting a new one; under the default crit level, the whole warn band separates
advising from re-arming.

Compaction: a compaction keeps the session id, and the status line refreshes
its snapshot only after a short delay once the compacted conversation is in
place, so a prompt processed right after a compaction (one queued while it ran,
or a task notification) can still find the snapshot recorded before it.
SessionStart with source compact fires while the compaction completes; it
deletes the state file and records the compaction time in
<session_id>.compacted.json, and snapshots written at or before that time are
ignored from then on. /clear starts a new session id, so a snapshot recorded
before it is never read and needs no such record.

Triggers: UserPromptSubmit and PostToolUse for every tool deliver the advisory,
UserPromptSubmit alone the reminder; SessionStart with source compact records
the compaction. Any other event or source is ignored.

The hook stays silent when the call comes from a subagent (the input carries an
agent_id; a subagent's context is its own and it cannot run /compact), when no
snapshot exists (the status line is not running, as in headless sessions, or
its snapshot feature is off), when the snapshot is unreadable, malformed, or
older than the latest compaction (these cases also leave the state file
untouched), and whenever the recorded severity is below the configured level.
It never blocks: it emits no decision, only additionalContext, and exits 0 on
every handled path.
"""

import contextlib
import importlib.util
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
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


def _load_json_output() -> ModuleType:
    """Dynamically load hook_json_output from the same directory."""
    loader_path = Path(__file__).parent / 'hook_json_output.py'
    spec = importlib.util.spec_from_file_location('hook_json_output', loader_path)
    if spec is None or spec.loader is None:
        raise ImportError(f'Cannot load hook_json_output from {loader_path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Events whose additionalContext reaches the model and that fire often enough to
# deliver the advisory promptly.
ADVISING_EVENTS: frozenset[str] = frozenset({'UserPromptSubmit', 'PostToolUse'})

# The one advising event that also repeats the reminder: it opens every turn the
# model answers, while tool events fire many times within a single turn.
REMINDER_EVENT = 'UserPromptSubmit'

# The SessionStart source that marks a completed compaction.
COMPACTION_SOURCE = 'compact'

# Severity order shared with the status line's context thresholds.
SEVERITY_RANK: dict[str, int] = {'ok': 0, 'warn': 1, 'crit': 2}

# A session id is used verbatim as a filename, so only ids made of
# filename-safe characters (no separators, no dots) are handled; this matches
# the ids the status line records snapshots for.
_SESSION_ID_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}')

# The line the model ends a milestone reply with: a Markdown blockquote, which
# Claude Code renders as italic text behind a dim bar, noticeable without
# drawing attention away from the work.
RECOMMENDATION_LINE = '> Context is large and everything is saved - run /compact when convenient.'

DEFAULT_MESSAGE = (
    'CONTEXT ADVISORY: This session has accumulated a large amount of context. '
    'This is advisory and needs no immediate action: you have room to keep working, so continue '
    'the current task at full quality and full scope, and do not stop, rush, shorten, or summarize '
    'your work on account of context. '
    'Very long contexts can make earlier details harder to recall precisely, and a fresh, compacted '
    'context keeps the rest of the session sharp. '
    'From now until the context is compacted, recommend compaction at every natural milestone, not '
    'just once, because the user may have missed an earlier recommendation. A natural milestone is the '
    'end of a reply that finishes a unit of work or a phase, lands a change, or pauses while waiting on '
    'background work such as a workflow, subagents, or a long-running command. '
    'Never interrupt work in progress for this, and never recommend compaction in the middle of a step. '
    'At each milestone, first save everything to the durable memory available to you -- the work '
    'state, the active plan and its progress, reports, decisions made, open questions, files being '
    'modified, and the identifiers of anything already stored -- re-saving whatever changed since the '
    'previous save, so the work can resume without loss after compaction. '
    'Then end the reply with the recommendation as its last line, on its own line after a blank line, '
    'written exactly as this Markdown blockquote:\n'
    f'{RECOMMENDATION_LINE}\n'
    'Leave the line out of replies that do not end at a milestone.'
)

DEFAULT_REMINDER = (
    'CONTEXT REMINDER: The context is still large and has not been compacted. '
    'Keep working at full quality and full scope, and never interrupt work in progress or stop in '
    'the middle of a step for this. '
    'If this reply ends at a natural milestone -- a unit of work or a phase finished, a change landed, '
    'or a pause while waiting on background work such as a workflow or subagents -- first save '
    'everything to the durable memory available to you, re-saving whatever changed since the previous '
    'save, and then end the reply with this last line, on its own line after a blank line:\n'
    f'{RECOMMENDATION_LINE}\n'
    'Otherwise leave the line out.'
)

# Default configuration - used when no config file provided
DEFAULT_CONFIG: dict[str, Any] = {
    'enabled': True,
    # Severity at which the advisory is injected: 'crit' (the status line's
    # red) or 'warn' (its yellow). Any other value falls back to 'crit'.
    # Re-arming always needs an ok or null reading, so 'crit' keeps the whole
    # warn band between advising and re-arming; with 'warn', a dip back to ok
    # re-arms, and the next warn reading advises again.
    'inject_at': 'crit',
    # Directory holding the status line's per-session snapshots; '~' and
    # environment variables are expanded. Empty selects the status line's
    # default, <config dir>/state/context-usage, where the config dir is
    # $CLAUDE_CONFIG_DIR when set and ~/.claude otherwise. Set it only
    # together with the status line's context_snapshot dir.
    'snapshot_dir': '',
    # Whether every user turn after the advisory carries the short reminder
    # until the advisor re-arms. False injects only the advisory, once per
    # escalation.
    'remind_each_turn': True,
    # The advisory injected once per escalation, and the reminder repeated on
    # every user turn after it. Keep both free of usage figures: explicit
    # context-budget numbers can prompt a model to cut its work short, which
    # is the opposite of the intent.
    'message': DEFAULT_MESSAGE,
    'reminder_message': DEFAULT_REMINDER,
}


def resolve_snapshot_directory(configured: object) -> Path:
    """Resolve the directory that holds the per-session context snapshots.

    Args:
        configured: The `snapshot_dir` config value. A non-empty string is
            used as the directory after expanding environment variables and
            '~'; anything else selects the default.

    Returns:
        The configured directory, or <config dir>/state/context-usage, where
        the config dir is $CLAUDE_CONFIG_DIR when set and non-empty, and
        ~/.claude otherwise.
    """
    if isinstance(configured, str) and configured.strip():
        return Path(os.path.expandvars(configured.strip())).expanduser()
    config_dir = os.environ.get('CLAUDE_CONFIG_DIR', '').strip()
    root = Path(config_dir).expanduser() if config_dir else Path.home() / '.claude'
    return root / 'state' / 'context-usage'


def _parse_timestamp(value: object) -> datetime | None:
    """Parse an ISO 8601 timestamp that carries a UTC offset.

    Args:
        value: The recorded value.

    Returns:
        The timestamp, or None when the value is not an ISO 8601 string with
        a UTC offset.
    """
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _read_json_object(path: Path) -> dict[str, Any] | None:
    """Read a JSON object from a file.

    Args:
        path: The file to read.

    Returns:
        The object, or None when the file is missing, unreadable, or does not
        hold a JSON object.
    """
    try:
        loaded: object = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(loaded, dict):
        return None
    return cast('dict[str, Any]', loaded)


@dataclass(frozen=True)
class SnapshotReading:
    """The part of a session's context snapshot the advisor acts on.

    Attributes:
        severity: 'ok', 'warn', or 'crit' as resolved by the status line, or
            None when the record holds no usage reading (before the session's
            first response, and right after /compact or /clear).
        written_at: When the status line wrote the record, or None when the
            record carries no valid timestamp.
    """

    severity: str | None
    written_at: datetime | None


def read_snapshot(snapshot_path: Path) -> SnapshotReading | None:
    """Read a session's context snapshot.

    Args:
        snapshot_path: Path of the session's <session_id>.json snapshot.

    Returns:
        The reading, or None when the snapshot is missing, unreadable, not a
        JSON object, or lacks a severity that is null or one of 'ok', 'warn',
        and 'crit'.
    """
    record = _read_json_object(snapshot_path)
    if record is None or 'severity' not in record:
        return None
    severity = record['severity']
    if severity is not None and not (isinstance(severity, str) and severity in SEVERITY_RANK):
        return None
    return SnapshotReading(severity, _parse_timestamp(record.get('written_at')))


def read_compaction_time(marker_path: Path) -> datetime | None:
    """Read when the session was last compacted.

    Args:
        marker_path: Path of the session's <session_id>.compacted.json file.

    Returns:
        The recorded compaction time, or None when the session has no valid
        compaction record.
    """
    record = _read_json_object(marker_path)
    return None if record is None else _parse_timestamp(record.get('compacted_at'))


def _inject_rank(config: dict[str, Any]) -> int:
    """Return the severity rank at which the advisory is injected.

    Args:
        config: Configuration dictionary with an optional `inject_at` key.

    Returns:
        The rank of `inject_at` when it is 'warn' or 'crit', otherwise the
        rank of 'crit'.
    """
    inject_at = config.get('inject_at')
    if isinstance(inject_at, str) and inject_at in ('warn', 'crit'):
        return SEVERITY_RANK[inject_at]
    return SEVERITY_RANK['crit']


def _configured_text(config: dict[str, Any], key: str, default: str) -> str:
    """Return a configured text, falling back to the default when it is blank.

    Args:
        config: Configuration dictionary.
        key: The text's config key.
        default: The text used when the value is missing, blank, or not a
            string.

    Returns:
        The text to inject.
    """
    text = config.get(key)
    return text if isinstance(text, str) and text.strip() else default


def claim_advisory(state_path: Path, severity: str) -> bool:
    """Atomically mark the session as advised, succeeding for one caller only.

    The state file is created with an exclusive create, so when several hook
    processes race, exactly one of them wins and injects the advisory.

    Args:
        state_path: Path of the session's <session_id>.state.json file.
        severity: The severity being advised, recorded for diagnostics.

    Returns:
        True when this call created the state file and must inject the
        advisory; False when the session was already advised or the file
        could not be created.
    """
    record = {
        'schema': 1,
        'severity': severity,
        'advised_at': datetime.now(UTC).isoformat(timespec='seconds'),
    }
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        with state_path.open('x', encoding='utf-8') as handle:
            handle.write(json.dumps(record))
    except OSError:
        # FileExistsError (another call already advised) is an OSError too;
        # any other failure also leaves this call silent rather than risk
        # advising on every call.
        return False
    return True


def rearm_advisory(state_path: Path) -> None:
    """Delete the session's state file so the next escalation advises again.

    Args:
        state_path: Path of the session's <session_id>.state.json file.
    """
    with contextlib.suppress(OSError):
        state_path.unlink(missing_ok=True)


def record_compaction(state_path: Path, marker_path: Path) -> None:
    """Record a completed compaction and end the current escalation.

    Snapshots written at or before the recorded time describe the context the
    compaction replaced and are ignored; deleting the state file lets a later
    escalation of the compacted context advise afresh.

    Args:
        state_path: Path of the session's <session_id>.state.json file.
        marker_path: Path of the session's <session_id>.compacted.json file.
    """
    record = {'schema': 1, 'compacted_at': datetime.now(UTC).isoformat(timespec='seconds')}
    with contextlib.suppress(OSError):
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        marker_path.write_text(json.dumps(record), encoding='utf-8')
    rearm_advisory(state_path)


def advise(input_data: dict[str, Any], config: dict[str, Any]) -> str | None:
    """Decide whether this hook call injects the advisory or the reminder, updating the state.

    Args:
        input_data: The hook event input (JSON from stdin).
        config: Configuration dictionary with `inject_at`, `snapshot_dir`,
            `remind_each_turn`, `message`, and `reminder_message`.

    Returns:
        The advisory or reminder text to inject, or None when this call stays
        silent.
    """
    event = input_data.get('hook_event_name')
    compaction = event == 'SessionStart' and input_data.get('source') == COMPACTION_SOURCE
    if event not in ADVISING_EVENTS and not compaction:
        return None
    if input_data.get('agent_id'):
        return None

    session_id = input_data.get('session_id')
    if not isinstance(session_id, str) or not _SESSION_ID_RE.fullmatch(session_id):
        return None

    try:
        directory = resolve_snapshot_directory(config.get('snapshot_dir'))
    except RuntimeError:
        # The default directory needs the home directory, which cannot always
        # be determined; without it there is no snapshot to read.
        return None
    state_path = directory / f'{session_id}.state.json'
    marker_path = directory / f'{session_id}.compacted.json'
    if compaction:
        record_compaction(state_path, marker_path)
        return None

    reading = read_snapshot(directory / f'{session_id}.json')
    if reading is None:
        return None
    compacted_at = read_compaction_time(marker_path)
    if compacted_at is not None and (reading.written_at is None or reading.written_at <= compacted_at):
        # Recorded before the latest compaction: the reading describes the
        # context that compaction replaced.
        return None

    severity = reading.severity
    if severity is None or severity == 'ok':
        # Below the warn band: the usage dropped, or /compact or /clear reset
        # it, so the next escalation is a new one. A warn reading never gets
        # here, so under the default crit level usage that dips from crit into
        # the warn band and climbs back continues the same escalation.
        rearm_advisory(state_path)
        return None
    if SEVERITY_RANK[severity] < _inject_rank(config):
        return None

    if claim_advisory(state_path, severity):
        return _configured_text(config, 'message', DEFAULT_MESSAGE)
    if event == REMINDER_EVENT and config.get('remind_each_turn') is not False and state_path.is_file():
        return _configured_text(config, 'reminder_message', DEFAULT_REMINDER)
    return None


def main() -> None:
    """Main hook execution function."""
    config_loader = _load_config_loader()
    config = config_loader.get_config_from_argv(DEFAULT_CONFIG)
    if not config.get('enabled', True):
        sys.exit(0)

    try:
        input_data: object = json.load(sys.stdin)
    except json.JSONDecodeError:
        # Malformed stdin from the Claude Code wrapper is an external contract
        # violation with nothing actionable for the model; stay silent.
        sys.exit(0)
    if not isinstance(input_data, dict):
        sys.exit(0)
    payload = cast('dict[str, Any]', input_data)

    message = advise(payload, config)
    if message is not None:
        _load_json_output().emit_additional_context(payload['hook_event_name'], message)
    sys.exit(0)


if __name__ == '__main__':
    main()
