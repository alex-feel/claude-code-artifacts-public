#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["pyyaml"]
# ///
"""
Context compact advisor hook for Claude Code.

Advises the main agent to recommend /compact in two tiers that follow the
status line's context severity: warn (its yellow, where the status line says
"consider /compact") and crit (its red, where it says "run /compact now").
Each tier's advisory keeps the model working at full quality and full scope
and asks that, when a reply ends at a natural milestone (a unit of work or a
phase finished, a change landed, a pause while waiting on background work),
the model first save the full work state durably, re-saving whatever changed
since the previous save, and only then end the reply with the tier's one-line
recommendation, set apart as a Markdown blockquote. The warn line suggests
compacting when convenient in a calm, advisory tone; the crit line strongly
recommends compacting now and the crit texts say why. Work in progress is
never interrupted for either, and no text carries usage figures, which can
prompt a model to cut its work short. Saving first lets the work resume
without loss after the compaction.

Hook events carry no context-usage figures, so this hook reads the per-session
snapshot the status line writes when its context_snapshot feature is enabled:
<snapshot dir>/<session_id>.json, whose 'severity' field (ok, warn, or crit) is
resolved by the status line's own context thresholds. The advisor therefore
escalates exactly when the status line does and carries no thresholds of its
own that could drift from it. The snapshot directory defaults to
<config dir>/state/context-usage, where the config dir is $CLAUDE_CONFIG_DIR
when set and ~/.claude otherwise -- the same default the status line uses.

Tiers: inject_at names the lowest tier advised. The default, warn, advises at
both tiers; crit advises only at crit, and warn readings then neither advise,
remind, nor re-arm.

Delivery: each tier's full advisory is injected at most once per escalation.
The file <session_id>.advised-<tier>.json in the snapshot directory marks the
tier as advised; the call that creates it, with an exclusive create, injects
that tier's advisory, so concurrent hook processes (parallel tool calls)
inject it at most once. Claiming crit also marks warn as advised when warn is
advised at all, so usage that goes straight to crit and later dips into the
warn band brings the warn reminder, never the warn advisory. Every
UserPromptSubmit whose reading is at an advised tier injects that tier's
reminder, so each turn the model answers carries the advice that applies to
it, including turns opened by task notifications; tool events never repeat
anything. The texts scope the recommendation line to such turns: it may end
only a reply to a turn that carries an advisory or a reminder, so no duty the
model would have to track by itself outlives the turns that carry it.

Re-arming: a snapshot reading deletes both markers only when its severity is
ok (below the status line's warn band) or null, which the status line records
while the session has no usage reading (before its first response, and right
after /compact until the next response). A warn reading never re-arms, so
usage that falls from crit back into the warn band and climbs again continues
the same escalation with reminders instead of new advisories.

Compaction: a compaction keeps the session id, and the status line refreshes
its snapshot only after a short delay once the compacted conversation is in
place, so a prompt processed right after a compaction (one queued while it ran,
or a task notification) can still find the snapshot recorded before it.
SessionStart with source compact fires while the compaction completes; it
records the compaction time in <session_id>.compacted.json and deletes both
markers, and snapshots written at or before that time are ignored from then
on. When a marker existed, an escalation was in force, and the call returns a
notice that the advice has ended. A compaction summary can restate a pending
recommendation line as a step still to take, and SessionStart additionalContext
reaches the model after the summary, so the notice is what the first turn
after the compaction sees; every advisory and reminder also asks the
summarizer not to carry the advice into the summary. A compaction outside an
escalation returns nothing. /clear starts a new session id, so a snapshot
recorded before it is never read and needs no such record.

Triggers: UserPromptSubmit and PostToolUse for every tool deliver the
advisories, UserPromptSubmit alone the reminders; SessionStart with source
compact records the compaction and ends the escalation. Any other event or
source is ignored.

The hook stays silent when the call comes from a subagent (the input carries an
agent_id; a subagent's context is its own and it cannot run /compact), when no
snapshot exists (the status line is not running, as in headless sessions, or
its snapshot feature is off), when the snapshot is unreadable, malformed, or
older than the latest compaction (these cases also leave the markers
untouched), and whenever the recorded severity is below the lowest advised
tier. It never blocks: it emits no decision, only additionalContext, and exits
0 on every handled path.
"""

import contextlib
import importlib.util
import json
import os
import re
import sys
from collections.abc import Iterable
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
# deliver an advisory promptly.
ADVISING_EVENTS: frozenset[str] = frozenset({'UserPromptSubmit', 'PostToolUse'})

# The one advising event that also delivers the reminders: it opens every turn
# the model answers, while tool events fire many times within a single turn.
REMINDER_EVENT = 'UserPromptSubmit'

# The SessionStart source that marks a completed compaction.
COMPACTION_SOURCE = 'compact'

# Severity order shared with the status line's context thresholds.
SEVERITY_RANK: dict[str, int] = {'ok': 0, 'warn': 1, 'crit': 2}

# The advised tiers, lowest first: the status line's warn (yellow) and crit
# (red) severities.
TIERS: tuple[str, ...] = ('warn', 'crit')

# A session id is used verbatim as a filename, so only ids made of
# filename-safe characters (no separators, no dots) are handled; this matches
# the ids the status line records snapshots for.
_SESSION_ID_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}')

# The line the model ends a milestone reply with, per tier: a Markdown
# blockquote, which Claude Code renders as italic text behind a dim bar,
# noticeable without drawing attention away from the work.
RECOMMENDATION_LINES: dict[str, str] = {
    'warn': '> Context is large and everything is saved - run /compact when convenient.',
    'crit': '> Context is very large and everything is saved - I strongly recommend running /compact now.',
}

# What to save before recommending compaction, woven into every text after
# 'first'. It names no particular memory store, so it suits any environment.
DEFAULT_SAVE_INSTRUCTION = (
    'save everything to the durable memory available to you -- the work state, the active plan and its progress, '
    'reports, decisions made, open questions, files being modified, and the identifiers of anything already stored '
    '-- re-saving whatever changed since the previous save, so the work can resume without loss after compaction'
)

_KEEP_WORKING = (
    'continue the current task at full quality and full scope, and do not stop, rush, shorten, or summarize your '
    'work on account of context'
)

_CRIT_REASONS = (
    'Earlier details become harder to recall precisely as the context keeps growing, and compacting now, after '
    'saving, keeps the rest of the session sharp and avoids an automatic compaction at an arbitrary point later.'
)

_CRIT_KEEP_WORKING = f'The urgency concerns only when to recommend compaction, never how you work: {_KEEP_WORKING}.'

# The opening of each text, by kind and tier: why the advice is given and how
# pressing it is. The rest of every text is the shared _BODY.
_OPENINGS: dict[str, dict[str, str]] = {
    'advisory': {
        'warn': (
            'CONTEXT ADVISORY: This session has accumulated a large amount of context. '
            f'This is advisory and needs no immediate action: you have room to keep working, so {_KEEP_WORKING}. '
            'Very long contexts can make earlier details harder to recall precisely, and a fresh, compacted context '
            'keeps the rest of the session sharp, so recommend compaction to the user at a natural milestone.'
        ),
        'crit': (
            'CONTEXT ADVISORY (URGENT): The context of this session is now very large, and compaction is strongly '
            'recommended at the next natural milestone. This replaces the milder recommendation of any earlier '
            f'context advisory. {_CRIT_REASONS} {_CRIT_KEEP_WORKING}'
        ),
    },
    'reminder': {
        'warn': (
            'CONTEXT REMINDER: The context is still large and has not been compacted. '
            f'This is advisory and needs no immediate action: {_KEEP_WORKING}.'
        ),
        'crit': (
            'CONTEXT REMINDER (URGENT): The context is still very large and has not been compacted, so compaction '
            f'remains strongly recommended at the next natural milestone. {_CRIT_REASONS} {_CRIT_KEEP_WORKING}'
        ),
    },
}

# The part every text shares: what a milestone is, save first, the tier's line
# on its own, the turns the line belongs to, and the end of the advice at a
# compaction. {save_instruction} and {line} are filled in per text.
_BODY = (
    ' A natural milestone is the end of a reply that finishes a unit of work or a phase, lands a change, or pauses '
    'while waiting on background work such as a workflow, subagents, or a long-running command. '
    'Never interrupt work in progress for this, and never recommend compaction in the middle of a step. '
    'At such a milestone, first {save_instruction}. '
    'Then end the reply with the recommendation as its last line, on its own line after a blank line, written '
    'exactly as this Markdown blockquote:\n'
    '{line}\n'
    'Add the line only to a reply to a turn that carries a CONTEXT ADVISORY or a CONTEXT REMINDER, such as this one, '
    'and only when that reply ends at a natural milestone. Every later user turn carries a CONTEXT REMINDER for as '
    'long as this advice applies, so a turn that carries neither needs no line, even if an earlier reply ended with '
    'one. If the conversation is compacted, this advice ends with the compaction: do not carry it or the '
    'recommendation line into the summary or its next steps.'
)

# Returned by the SessionStart compact call that ends an escalation. It lands
# after the compaction summary, which may still ask for a recommendation line.
COMPACTION_NOTICE = (
    'CONTEXT ADVISORY ENDED: The context has just been compacted, so the earlier context advisory and its reminders '
    'no longer apply. Do not end replies with a /compact recommendation line, even where the compaction summary says '
    'a reply should end with one; add such a line again only in a turn that carries a new CONTEXT ADVISORY or '
    'CONTEXT REMINDER.'
)

# Default configuration - used when no config file provided
DEFAULT_CONFIG: dict[str, Any] = {
    'enabled': True,
    # The lowest tier advised: 'warn' (the status line's yellow) advises at
    # both tiers, 'crit' (its red) only at crit, leaving warn readings silent.
    # Any other value falls back to 'warn'.
    'inject_at': 'warn',
    # Directory holding the status line's per-session snapshots; '~' and
    # environment variables are expanded. Empty selects the status line's
    # default, <config dir>/state/context-usage, where the config dir is
    # $CLAUDE_CONFIG_DIR when set and ~/.claude otherwise. Set it only
    # together with the status line's context_snapshot dir.
    'snapshot_dir': '',
    # What to save at a milestone before recommending compaction: a clause
    # that completes 'At such a milestone, first ...', without a final
    # period, used in every advisory and reminder. A blank or non-string value
    # falls back to this default. Keep it free of usage figures: explicit
    # context-budget numbers can prompt a model to cut its work short.
    'save_instruction': DEFAULT_SAVE_INSTRUCTION,
}


def advisory_text(tier: str, save_instruction: str) -> str:
    """Compose a tier's full advisory, injected once per escalation.

    Args:
        tier: 'warn' or 'crit'.
        save_instruction: The clause saying what to save before recommending
            compaction.

    Returns:
        The advisory text.
    """
    return _compose('advisory', tier, save_instruction)


def reminder_text(tier: str, save_instruction: str) -> str:
    """Compose a tier's reminder, injected on each user turn after the tier's advisory.

    Args:
        tier: 'warn' or 'crit'.
        save_instruction: The clause saying what to save before recommending
            compaction.

    Returns:
        The reminder text.
    """
    return _compose('reminder', tier, save_instruction)


def _compose(kind: str, tier: str, save_instruction: str) -> str:
    """Join a text's opening with the shared body, filled in for the tier."""
    return _OPENINGS[kind][tier] + _BODY.format(save_instruction=save_instruction, line=RECOMMENDATION_LINES[tier])


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


def read_compaction_time(compacted_path: Path) -> datetime | None:
    """Read when the session was last compacted.

    Args:
        compacted_path: Path of the session's <session_id>.compacted.json file.

    Returns:
        The recorded compaction time, or None when the session has no valid
        compaction record.
    """
    record = _read_json_object(compacted_path)
    return None if record is None else _parse_timestamp(record.get('compacted_at'))


def _lowest_tier(config: dict[str, Any]) -> str:
    """Return the lowest tier advised.

    Args:
        config: Configuration dictionary with an optional `inject_at` key.

    Returns:
        `inject_at` when it is 'warn' or 'crit', otherwise 'warn'.
    """
    inject_at = config.get('inject_at')
    return inject_at if isinstance(inject_at, str) and inject_at in TIERS else 'warn'


def _save_instruction(config: dict[str, Any]) -> str:
    """Return the configured save instruction, falling back to the default when it is blank.

    Args:
        config: Configuration dictionary with an optional `save_instruction`
            key.

    Returns:
        The configured clause without surrounding whitespace, or
        DEFAULT_SAVE_INSTRUCTION when the value is missing, blank, or not a
        string.
    """
    value = config.get('save_instruction')
    return value.strip() if isinstance(value, str) and value.strip() else DEFAULT_SAVE_INSTRUCTION


def claim_tier(marker_path: Path, tier: str) -> bool:
    """Atomically mark a tier as advised, succeeding for one caller only.

    The marker is created with an exclusive create, so when several hook
    processes race, exactly one of them wins and injects the tier's advisory.

    Args:
        marker_path: Path of the session's <session_id>.advised-<tier>.json
            file.
        tier: The tier being advised, recorded for diagnostics.

    Returns:
        True when this call created the marker and must inject the advisory;
        False when the tier was already advised or the marker could not be
        created.
    """
    record = {
        'schema': 1,
        'tier': tier,
        'advised_at': datetime.now(UTC).isoformat(timespec='seconds'),
    }
    try:
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        with marker_path.open('x', encoding='utf-8') as handle:
            handle.write(json.dumps(record))
    except OSError:
        # FileExistsError (another call already advised) is an OSError too;
        # any other failure also leaves this call silent rather than risk
        # advising on every call.
        return False
    return True


def clear_markers(marker_paths: Iterable[Path]) -> bool:
    """Delete the tier markers so the next escalation advises again.

    Args:
        marker_paths: Paths of the session's tier markers.

    Returns:
        True when at least one marker existed and was deleted, meaning an
        escalation was in force.
    """
    cleared = False
    for marker_path in marker_paths:
        try:
            marker_path.unlink()
        except OSError:
            # FileNotFoundError: the tier was not advised. Any other failure
            # leaves the marker in place for the next re-arm to retry.
            continue
        cleared = True
    return cleared


def record_compaction(compacted_path: Path) -> None:
    """Record when a compaction completed.

    Snapshots written at or before the recorded time describe the context the
    compaction replaced and are ignored.

    Args:
        compacted_path: Path of the session's <session_id>.compacted.json file.
    """
    record = {'schema': 1, 'compacted_at': datetime.now(UTC).isoformat(timespec='seconds')}
    with contextlib.suppress(OSError):
        compacted_path.parent.mkdir(parents=True, exist_ok=True)
        compacted_path.write_text(json.dumps(record), encoding='utf-8')


def advise(input_data: dict[str, Any], config: dict[str, Any]) -> str | None:
    """Decide which text, if any, this hook call injects, updating the markers.

    Args:
        input_data: The hook event input (JSON from stdin).
        config: Configuration dictionary with `inject_at`, `snapshot_dir`, and
            `save_instruction`.

    Returns:
        A tier's advisory or reminder, the compaction notice when a compaction
        ends an escalation, or None when this call stays silent.
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
    markers = {tier: directory / f'{session_id}.advised-{tier}.json' for tier in TIERS}
    compacted_path = directory / f'{session_id}.compacted.json'
    if compaction:
        record_compaction(compacted_path)
        return COMPACTION_NOTICE if clear_markers(markers.values()) else None

    reading = read_snapshot(directory / f'{session_id}.json')
    if reading is None:
        return None
    compacted_at = read_compaction_time(compacted_path)
    if compacted_at is not None and (reading.written_at is None or reading.written_at <= compacted_at):
        # Recorded before the latest compaction: the reading describes the
        # context that compaction replaced.
        return None

    severity = reading.severity
    if severity is None or severity == 'ok':
        # Below the warn band: the usage dropped, or /compact or /clear reset
        # it, so the next escalation is a new one. A warn reading never gets
        # here, so usage that dips from crit into the warn band and climbs back
        # continues the same escalation.
        clear_markers(markers.values())
        return None
    lowest = _lowest_tier(config)
    if SEVERITY_RANK[severity] < SEVERITY_RANK[lowest]:
        return None

    save_instruction = _save_instruction(config)
    if claim_tier(markers[severity], severity):
        if severity != lowest:
            # Reaching crit covers the advice of the warn tier below it, so a
            # later dip into the warn band brings the warn reminder only.
            claim_tier(markers[lowest], lowest)
        return advisory_text(severity, save_instruction)
    if event == REMINDER_EVENT and markers[severity].is_file():
        return reminder_text(severity, save_instruction)
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
