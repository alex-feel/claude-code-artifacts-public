#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["pyyaml"]
# ///
"""
Context compact advisor hook for Claude Code.

Injects a one-time advisory into the main agent's context once the session's
context-window usage reaches a configured severity. The advisory asks the agent
to finish its current step, save its full work state durably, and then suggest a
manual /compact to the user at a natural milestone, never interrupting work in
progress. A fresh, compacted context keeps long-session work sharp, and saving
the state first lets the work resume without loss after the compaction.

Hook events carry no context-usage figures, so this hook reads the per-session
snapshot the status line writes when its context_snapshot feature is enabled:
<snapshot dir>/<session_id>.json, whose 'severity' field (ok, warn, or crit) is
resolved by the status line's own context thresholds. The advisor therefore
fires exactly when the status line reaches the chosen severity and carries no
thresholds of its own that could drift from it. The snapshot directory defaults
to <config dir>/state/context-usage, where the config dir is $CLAUDE_CONFIG_DIR
when set and ~/.claude otherwise -- the same default the status line uses.

Once-only delivery: the file <session_id>.state.json in the snapshot directory
exists from the advisory until the advisor re-arms. It is created with an
exclusive create, so concurrent hook processes (parallel tool calls) inject the
advisory at most once. It is deleted, re-arming the advisor, only when the
recorded severity is ok (below the status line's warn band) or null, which the
status line records while the session has no usage reading (before its first
response, and right after /compact or /clear). A warn reading never re-arms,
whatever the configured level, so usage that falls from crit back into the warn
band and climbs again without a compaction cannot repeat the advisory into a
context that already holds it; under the default crit level, the whole warn
band separates advising from re-arming.

Triggers: UserPromptSubmit, and PostToolUse for every tool. Any other event is
ignored.

The hook stays silent when the call comes from a subagent (the input carries an
agent_id; a subagent's context is its own and it cannot run /compact), when no
snapshot exists (the status line is not running, as in headless sessions, or
its snapshot feature is off), when the snapshot is unreadable or malformed
(these cases also leave the state file untouched), and whenever the recorded
severity is below the configured level. It never blocks: it emits no decision,
only additionalContext, and exits 0 on every handled path.
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
SUPPORTED_EVENTS: frozenset[str] = frozenset({'UserPromptSubmit', 'PostToolUse'})

# Severity order shared with the status line's context thresholds.
SEVERITY_RANK: dict[str, int] = {'ok': 0, 'warn': 1, 'crit': 2}

# A session id is used verbatim as a filename, so only ids made of
# filename-safe characters (no separators, no dots) are handled; this matches
# the ids the status line records snapshots for.
_SESSION_ID_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}')

DEFAULT_MESSAGE = (
    'CONTEXT ADVISORY: This session has accumulated a large amount of context. '
    'This is advisory and needs no immediate action: you have room to keep working, so continue '
    'the current task at full quality and full scope, and do not stop, rush, shorten, or summarize '
    'your work on account of context. '
    'Very long contexts can make earlier details harder to recall precisely, and a fresh, compacted '
    'context keeps the rest of the session sharp, so plan one compaction at a convenient point. '
    'Finish the step you are on. At the next natural milestone -- right after completing a unit of '
    'work, or while waiting on background work such as a workflow, subagents, or a long-running '
    'command -- first save the full state of your work to the durable memory available to you: the '
    'active plan and its progress, decisions made, open questions, files being modified, and the '
    'identifiers of anything already stored, so the work can resume without loss after compaction. '
    'Then suggest to the user, in one short sentence, that they run /compact when convenient. '
    'Never interrupt work in progress for this, and make the suggestion only once.'
)

# Default configuration - used when no config file provided
DEFAULT_CONFIG: dict[str, Any] = {
    'enabled': True,
    # Severity at which the one-time advisory is injected: 'crit' (the status
    # line's red) or 'warn' (its yellow). Any other value falls back to 'crit'.
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
    # The advisory injected into the model's context. Keep it free of usage
    # figures: explicit context-budget numbers can prompt a model to cut its
    # work short, which is the opposite of the intent.
    'message': DEFAULT_MESSAGE,
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


@dataclass(frozen=True)
class SnapshotReading:
    """The part of a session's context snapshot the advisor acts on.

    Attributes:
        severity: 'ok', 'warn', or 'crit' as resolved by the status line, or
            None when the record holds no usage reading (before the session's
            first response, and right after /compact or /clear).
    """

    severity: str | None


def read_snapshot(snapshot_path: Path) -> SnapshotReading | None:
    """Read a session's context snapshot.

    Args:
        snapshot_path: Path of the session's <session_id>.json snapshot.

    Returns:
        The reading, or None when the snapshot is missing, unreadable, not a
        JSON object, or lacks a severity that is null or one of 'ok', 'warn',
        and 'crit'.
    """
    try:
        loaded: object = json.loads(snapshot_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(loaded, dict):
        return None
    record = cast('dict[str, Any]', loaded)
    if 'severity' not in record:
        return None
    severity = record['severity']
    if severity is None:
        return SnapshotReading(None)
    if isinstance(severity, str) and severity in SEVERITY_RANK:
        return SnapshotReading(severity)
    return None


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


def advise(input_data: dict[str, Any], config: dict[str, Any]) -> str | None:
    """Decide whether this hook call injects the advisory, updating the state.

    Args:
        input_data: The hook event input (JSON from stdin).
        config: Configuration dictionary with `inject_at`, `snapshot_dir`,
            and `message`.

    Returns:
        The advisory text to inject, or None when this call stays silent.
    """
    if input_data.get('hook_event_name') not in SUPPORTED_EVENTS:
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
    reading = read_snapshot(directory / f'{session_id}.json')
    if reading is None:
        return None

    state_path = directory / f'{session_id}.state.json'
    severity = reading.severity
    if severity is None or severity == 'ok':
        # Below the warn band: the usage dropped, or /compact or /clear reset
        # it, so the next escalation is a new one. A warn reading never gets
        # here, so under the default crit level usage that dips from crit into
        # the warn band and climbs back does not repeat the advisory.
        rearm_advisory(state_path)
        return None
    if SEVERITY_RANK[severity] < _inject_rank(config):
        return None

    if not claim_advisory(state_path, severity):
        return None

    message = config.get('message')
    if not isinstance(message, str) or not message.strip():
        message = DEFAULT_MESSAGE
    return message


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
