#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["pyyaml"]
# ///
"""
Status line hook for Claude Code.

Displays: [model] | project | branch | session | [+N/-M] | [ctx:N%] | [eff:level] | [rate_limits] | [profile] | [suffix]

This script receives JSON via stdin and outputs a colored status line.
Claude Code renders each line of stdout as its own status row: the first
line carries the block-based status line, and an optional second row
carries notifications, printed only when at least one notification is
active so it takes no space otherwise.

The first line is composed of named blocks: model, project, branch, session,
lines, context, effort, rate_limits, profile, and suffix.

Features:
- Configurable block order: the 'order' config list controls the segment
  sequence; blocks missing from the list are appended in the default order
- Per-block customization: every block has an 'enabled' flag, color settings
  (including 'none' for uncolored output and bright_ color variants), and a
  'bold' flag; the separator between blocks is configurable as well
- Optional model display: shows the current model name (disabled by default)
- Protected branch warning: protected branches (default main/master) render
  in a warning color and bold
- Claude session line stats: lines added and removed, individually colored
- Context usage display: percent of the model context window used,
  threshold-colored (ok/warn/crit), with optional token counts; the
  thresholds are tiered by context-window size, and the context block's
  thresholds and colors are the single source shared with the /compact
  reminder and the context snapshot, so every surface escalates together
- Reasoning effort display: the current effort level (low/medium/high/xhigh/max)
  with per-level colors; hidden for models without effort support
- Claude rate-limit display: compact 5h/7d usage percentages, threshold-colored
- Profile display (disabled by default): the name of the Claude Code
  configuration directory the session runs under ($CLAUDE_CONFIG_DIR), or a
  configurable label when that is the default directory (~/.claude)
- Configurable suffix: optional custom text at end of status line
- Notifications row (disabled by default): an optional second output row for
  notification segments; currently carries the /compact reminder, which
  appears when context-window usage reaches the context block's warn
  threshold and escalates its styling at the crit threshold, while staying
  independently disableable via its own 'enabled' flag
- Context snapshot (disabled by default): records the session's context usage
  and resolved severity in a per-session JSON file on every run, so tools that
  never see the status-line payload (hook events carry no usage figures) can
  act on exactly what the status line shows

The 'order' list controls sequence only and applies to the first row. Block
visibility is controlled exclusively by each block's 'enabled' flag and by
payload presence (the suffix block shows only when its text is non-empty).

Configuration is loaded from external YAML file when provided.
"""

import contextlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
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


# ANSI color codes
class Colors:
    """ANSI escape codes for terminal colors."""

    RESET = '\033[0m'
    BOLD = '\033[1m'
    BLACK = '\033[30m'
    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    WHITE = '\033[37m'
    BRIGHT_BLACK = '\033[90m'
    BRIGHT_RED = '\033[91m'
    BRIGHT_GREEN = '\033[92m'
    BRIGHT_YELLOW = '\033[93m'
    BRIGHT_BLUE = '\033[94m'
    BRIGHT_MAGENTA = '\033[95m'
    BRIGHT_CYAN = '\033[96m'
    BRIGHT_WHITE = '\033[97m'


# Canonical block names in their default display sequence. The 'order' config
# list controls sequence only; visibility is governed per block (see the
# module docstring).
_DEFAULT_BLOCK_ORDER: tuple[str, ...] = (
    'model',
    'project',
    'branch',
    'session',
    'lines',
    'context',
    'effort',
    'rate_limits',
    'profile',
    'suffix',
)


# Default configuration - used when no config file provided
DEFAULT_CONFIG: dict[str, Any] = {
    'enabled': True,
    'protected_branches': ['main', 'master'],
    # Separator string printed between rendered blocks. An empty string is
    # allowed and joins the blocks without any spacing.
    'separator': ' | ',
    # Block display sequence. Unknown names are ignored; recognized blocks
    # missing from the list are appended in the default sequence.
    'order': list(_DEFAULT_BLOCK_ORDER),
    'model': {
        # Off by default: the shipped hook does not show the model segment.
        'enabled': False,
        # Which field of the statusline `model` object to show:
        # 'display_name' (for example "Opus") or 'id' (for example
        # "claude-opus-4-8"). Falls back to the other field when absent.
        'source': 'display_name',
        'color': 'magenta',
        'bold': False,
    },
    'project': {
        'enabled': True,
        'color': 'yellow',
        'bold': False,
    },
    'branch': {
        'enabled': True,
        'color': 'green',
        'bold': False,
        # Branches listed in the top-level 'protected_branches' list render
        # with the warning styling below instead of the normal color.
        'protected_color': 'red',
        'protected_bold': True,
    },
    'session': {
        'enabled': True,
        'color': 'cyan',
        'bold': False,
    },
    'lines': {
        'enabled': True,
        'added_color': 'green',
        'removed_color': 'red',
        'bold': False,
    },
    'context': {
        'enabled': True,
        'label': 'ctx:',
        # Percent-used thresholds, measured against the full model context
        # window. They mark where a manual /compact becomes advisable (warn)
        # and urgent (crit), well before auto-compaction exhausts the window.
        # Long-context evaluations show recall declining as the number of
        # tokens in context grows, and the same percentage of a large window
        # holds far more tokens than of a small one, so the thresholds are
        # tiered by window size. Crit is sized to leave a typical turn and a
        # state save room to finish before Claude Code's own auto-compaction
        # trigger, which reserves the window's output allowance plus a fixed
        # buffer near its end; warn is an earlier heads-up and, unlike crit,
        # is a judgment call rather than derived from that trigger. The
        # packaged tier values are grounded in how Claude Code times its own
        # auto-compaction, not a measured optimum for any particular model.
        #
        # Threshold resolution (explicit configuration always wins over the
        # packaged defaults):
        #   1. The tier list: thresholds_by_window as configured; when the
        #      config block has no list under that key, no tiers if the block
        #      sets its own numeric warn_threshold or crit_threshold (a
        #      uniform pair for every window), and the packaged tiers below
        #      otherwise. An empty list disables tiering.
        #   2. Among the listed entries whose min_window is at or below the
        #      payload's context_window_size, the one with the largest
        #      min_window applies, wherever it sits in the list. An entry
        #      missing a numeric min_window, warn_threshold, or
        #      crit_threshold is ignored.
        #   3. When no tier applies (no tiers, no window size in the payload,
        #      or no entry's min_window low enough), the flat warn_threshold /
        #      crit_threshold pair applies, each value falling back to its
        #      packaged default below when not numeric.
        # These thresholds and the three colors below are the single source
        # for every context-usage surface: the ctx segment here, the /compact
        # reminder under 'notifications', and the severity recorded by
        # 'context_snapshot' all resolve through them, so they escalate in
        # lockstep. The 'enabled' flag above governs only this segment, never
        # the reminder or the snapshot.
        'thresholds_by_window': [
            {'min_window': 500000, 'warn_threshold': 57, 'crit_threshold': 75},
            {'min_window': 0, 'warn_threshold': 60, 'crit_threshold': 75},
        ],
        'warn_threshold': 60,
        'crit_threshold': 75,
        'ok_color': 'green',
        'warn_color': 'yellow',
        'crit_color': 'red',
        # When true, appends " (Nk/Mk)" with used and total tokens rounded
        # to thousands (a 1M-token window renders as 1000k).
        'show_tokens': False,
        'bold': False,
    },
    'effort': {
        'enabled': True,
        'label': 'eff:',
        # Fallback color for levels missing from level_colors (including
        # unknown future level names, which still render).
        'color': 'cyan',
        'level_colors': {
            'low': 'green',
            'medium': 'cyan',
            'high': 'blue',
            'xhigh': 'magenta',
            'max': 'red',
        },
        'bold': False,
    },
    'rate_limits': {
        'enabled': True,
        'warn_threshold': 70,
        'crit_threshold': 90,
        'ok_color': 'green',
        'warn_color': 'yellow',
        'crit_color': 'red',
        'bold': False,
        'window_keys': {
            # Verified key names from Claude Code's documented statusline JSON
            # schema (https://code.claude.com/docs/en/statusline). The top-level
            # child keys under `data['rate_limits']` are `five_hour` and
            # `seven_day`, each carrying `used_percentage` (0-100 float) and
            # `resets_at` (Unix epoch seconds).
            'five_hour': 'five_hour',
            'seven_day': 'seven_day',
        },
    },
    'profile': {
        # Off by default. When enabled, names the Claude Code profile the
        # session runs under. A profile is a configuration directory: the
        # default one, ~/.claude, is shown as base_label whenever
        # CLAUDE_CONFIG_DIR is unset, empty, or names that directory in any
        # spelling; any other directory is shown by its own name, so
        # CLAUDE_CONFIG_DIR=~/.claude/work shows "work". The label is worked
        # out on every run, so one config file installed into several
        # profiles shows each of them its own name.
        'enabled': False,
        # Label for the default configuration directory; "default" is the
        # term Claude Code's own documentation uses for ~/.claude.
        'base_label': 'default',
        'color': 'bright_blue',
        'bold': False,
    },
    'suffix': {
        'text': '',
        'color': 'cyan',
        'bold': False,
    },
    'notifications': {
        # Off by default: the shipped hook prints a single status row. When
        # enabled, a second row is printed below the status line whenever at
        # least one notification segment is active.
        'enabled': False,
        # Separator between notification segments when several are active.
        'separator': ' | ',
        'compact_reminder': {
            # This flag disables the reminder alone; thresholds and colors
            # are NOT configured here -- the reminder appears at the warn
            # threshold the 'context' block resolves for the session's window
            # (warn_color styling) and escalates at its crit threshold
            # (crit_color styling), so the reminder and the ctx segment always
            # agree.
            'enabled': True,
            # {percent} in either template is replaced with the integer
            # usage percent.
            'message': 'ctx {percent}% - consider /compact',
            'crit_message': 'ctx {percent}% - run /compact now',
            'bold': False,
        },
    },
    'context_snapshot': {
        # Off by default. When enabled, every run records the session's
        # context usage in <dir>/<session_id>.json, so tools that never see
        # the status-line payload (hook events carry no usage figures) can act
        # on exactly what the status line shows. The record holds the used
        # percentage, the window size, the model id, the severity (ok, warn,
        # or crit) resolved through the 'context' block's thresholds, those
        # effective thresholds, and a UTC timestamp. Before the first response
        # and right after /compact the payload carries no usage, and the
        # record then stores null for both the percentage and the severity,
        # so a pre-compaction reading never lingers. Each write replaces the
        # file atomically, so a reader never sees a partial record.
        'enabled': False,
        # Directory for the snapshot files; '~' and environment variables are
        # expanded. Empty or omitted selects <config dir>/state/context-usage,
        # where the config dir is $CLAUDE_CONFIG_DIR when set and ~/.claude
        # otherwise. Point it at a directory dedicated to these files.
        'dir': '',
        # When a session writes its first snapshot, files in the directory
        # left unmodified for this many days are deleted. Only files whose
        # names start with a UUID session id and end in .json or .tmp are
        # ever touched. Omitting the key keeps this default; a value that is
        # not a positive number disables pruning.
        'retention_days': 7,
    },
}


# Mapping of color names to ANSI codes. The 'none' entry maps to an empty
# code, which disables coloring for that block entirely.
COLOR_MAP: dict[str, str] = {
    'none': '',
    'black': Colors.BLACK,
    'red': Colors.RED,
    'green': Colors.GREEN,
    'yellow': Colors.YELLOW,
    'blue': Colors.BLUE,
    'magenta': Colors.MAGENTA,
    'cyan': Colors.CYAN,
    'white': Colors.WHITE,
    'bright_black': Colors.BRIGHT_BLACK,
    'bright_red': Colors.BRIGHT_RED,
    'bright_green': Colors.BRIGHT_GREEN,
    'bright_yellow': Colors.BRIGHT_YELLOW,
    'bright_blue': Colors.BRIGHT_BLUE,
    'bright_magenta': Colors.BRIGHT_MAGENTA,
    'bright_cyan': Colors.BRIGHT_CYAN,
    'bright_white': Colors.BRIGHT_WHITE,
}

# A session id is used verbatim as a snapshot filename, so only ids made of
# filename-safe characters (no separators, no dots) are recorded.
_SESSION_ID_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}')

# Files the snapshot pruner may delete: names starting with a UUID session id
# and ending in .json or .tmp, such as '<id>.json' or '<id>.json.<pid>.tmp'.
# Anything else in the directory is left alone.
_PRUNABLE_NAME_RE = re.compile(
    r'[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}(?:\.[A-Za-z0-9_-]+)*\.(?:json|tmp)',
)

_SECONDS_PER_DAY = 86400


def _as_dict(value: object, fallback: dict[str, Any]) -> dict[str, Any]:
    """Return value when it is a dict, otherwise the fallback.

    A config block written with an empty body (for example a bare ``model:``)
    parses to None and, under the shallow config merge, replaces the packaged
    default. Coercing any non-dict to the fallback keeps a single malformed
    config block from crashing the whole status line.

    Args:
        value: The candidate config sub-block, of unknown type.
        fallback: Dict to use when value is not a dict.

    Returns:
        value when it is a dict, else fallback.
    """
    return cast('dict[str, Any]', value) if isinstance(value, dict) else fallback


def _resolve_color(value: object, default_name: str) -> str:
    """Resolve a configured color name to an ANSI code, tolerating bad input.

    Falls back to default_name when value is not a recognized color-name
    string, so a null or mistyped ``color:`` config value never raises.

    Args:
        value: The configured color, expected to be a color-name string.
        default_name: Color name used when value is unusable; must be a key
            of COLOR_MAP.

    Returns:
        The ANSI escape code for the resolved color ('' for 'none').
    """
    name = value.lower() if isinstance(value, str) else default_name
    return COLOR_MAP.get(name, COLOR_MAP[default_name])


def _paint(text: str, color_value: object, default_name: str, bold: bool = False) -> str:
    """Wrap text in ANSI styling resolved from a configured color value.

    Resolves color_value via _resolve_color. When the resolved code is empty
    (color 'none') and bold is off, the text is returned unchanged so that
    uncolored blocks carry no escape codes at all.

    Args:
        text: The text to style.
        color_value: The configured color, expected to be a color-name string.
        default_name: Color name used when color_value is unusable; must be a
            key of COLOR_MAP.
        bold: Whether to prefix the segment with the ANSI bold code.

    Returns:
        The styled text, or the unmodified text when no styling applies.
    """
    code = _resolve_color(color_value, default_name)
    if not code and not bold:
        return text
    prefix = Colors.BOLD if bold else ''
    return f'{prefix}{code}{text}{Colors.RESET}'


def _resolve_block_order(config: dict[str, Any]) -> list[str]:
    """Resolve the block display sequence from the 'order' config list.

    Starts from ``config['order']`` when it is a list, keeps only recognized
    block names, and dedupes them preserving the first occurrence. Every
    recognized block missing from the configured list is then appended in
    default order, so the 'order' list controls sequence only and can never
    hide a block (visibility is governed by each block's 'enabled' flag).

    Args:
        config: Configuration dictionary with an optional 'order' list.

    Returns:
        The full list of recognized block names in display sequence.
    """
    configured = config.get('order')
    if not isinstance(configured, list):
        return list(_DEFAULT_BLOCK_ORDER)

    configured_names = cast('list[object]', configured)
    seen = dict.fromkeys(
        name
        for name in configured_names
        if isinstance(name, str) and name in _DEFAULT_BLOCK_ORDER
    )
    resolved = list(seen)
    resolved.extend(name for name in _DEFAULT_BLOCK_ORDER if name not in seen)
    return resolved


def get_branch_display(branch: str, config: dict[str, Any]) -> str:
    """
    Get the formatted branch display with appropriate color.

    Branches listed in the top-level 'protected_branches' config list render
    with the branch block's protected styling (RED + BOLD by default) as a
    warning. Other branches use the block's normal styling (GREEN by default).

    Args:
        branch: Git branch name
        config: Configuration dictionary with a protected_branches list and a
            'branch' sub-dict carrying color/bold and protected_color/
            protected_bold settings.

    Returns:
        ANSI-colored branch string
    """
    branch_config = _as_dict(config.get('branch'), DEFAULT_CONFIG['branch'])
    protected = config.get('protected_branches', DEFAULT_CONFIG['protected_branches'])
    if not isinstance(protected, (list, tuple, set)):
        protected = DEFAULT_CONFIG['protected_branches']
    if branch in protected:
        # Warning styling for protected branches
        return _paint(
            branch,
            branch_config.get('protected_color'),
            'red',
            branch_config.get('protected_bold', True) is True,
        )
    # Normal styling for other branches
    return _paint(branch, branch_config.get('color'), 'green', branch_config.get('bold') is True)


def get_project_display(data: dict[str, Any], config: dict[str, Any]) -> str | None:
    """
    Get the formatted project-name segment if enabled.

    Shows the basename of `workspace.project_dir`, falling back to
    `workspace.current_dir`, and 'unknown' when neither is present.

    Args:
        data: Statusline input JSON (as a dict), expected to carry a
            `workspace` object with `project_dir` and/or `current_dir`.
        config: Configuration dictionary; expects a `project` sub-dict with
            `enabled` (bool), `color`, and `bold`.

    Returns:
        ANSI-colored project string, or None when the block is disabled.
    """
    project_config = _as_dict(config.get('project'), DEFAULT_CONFIG['project'])
    if not project_config.get('enabled', True):
        return None

    workspace = _as_dict(data.get('workspace'), {})
    project_dir = workspace.get('project_dir', workspace.get('current_dir', ''))
    if not isinstance(project_dir, str):
        project_dir = ''
    project_name = Path(project_dir).name if project_dir else 'unknown'

    return _paint(project_name, project_config.get('color'), 'yellow', project_config.get('bold') is True)


def get_session_display(data: dict[str, Any], config: dict[str, Any]) -> str | None:
    """
    Get the formatted session-id segment if enabled.

    Shows the full session id for traceability, or 'unknown' when the payload
    carries no usable `session_id` string.

    Args:
        data: Statusline input JSON (as a dict), expected to carry a
            `session_id` string.
        config: Configuration dictionary; expects a `session` sub-dict with
            `enabled` (bool), `color`, and `bold`.

    Returns:
        ANSI-colored session-id string, or None when the block is disabled.
    """
    session_config = _as_dict(config.get('session'), DEFAULT_CONFIG['session'])
    if not session_config.get('enabled', True):
        return None

    session_id = data.get('session_id')
    if not isinstance(session_id, str) or not session_id:
        session_id = 'unknown'

    return _paint(session_id, session_config.get('color'), 'cyan', session_config.get('bold') is True)


def get_claude_lines_display(data: dict[str, Any], config: dict[str, Any]) -> str:
    """
    Get Claude's session line change statistics.

    Extracts total_lines_added and total_lines_removed from the cost data and
    formats them as colored statistics (GREEN additions and RED deletions by
    default; both colors are configurable via the `lines` config block).

    Args:
        data: Input JSON data containing cost statistics.
        config: Configuration dictionary; expects a `lines` sub-dict with
            `enabled` (bool), `added_color`, `removed_color`, and `bold`.

    Returns:
        Formatted string like "+N/-M" with ANSI colors, or empty string when
        both counters are 0 or the block is disabled.
    """
    lines_config = _as_dict(config.get('lines'), DEFAULT_CONFIG['lines'])
    if not lines_config.get('enabled', True):
        return ''

    cost = _as_dict(data.get('cost'), {})
    added = cost.get('total_lines_added', 0)
    removed = cost.get('total_lines_removed', 0)
    if not isinstance(added, (int, float)):
        added = 0
    if not isinstance(removed, (int, float)):
        removed = 0

    if added == 0 and removed == 0:
        return ''

    bold = lines_config.get('bold') is True
    added_part = _paint(f'+{added}', lines_config.get('added_color'), 'green', bold)
    removed_part = _paint(f'-{removed}', lines_config.get('removed_color'), 'red', bold)
    return f'{added_part}/{removed_part}'


def get_model_display(data: dict[str, Any], config: dict[str, Any]) -> str | None:
    """
    Get the formatted current-model segment if enabled.

    Reads the model name from Claude Code's statusline `model` object and
    returns it as a colored segment. Disabled by default; enable it via the
    `model` config block. The `source` option selects which field to show --
    'display_name' (for example "Opus") or 'id' (for example
    "claude-opus-4-8") -- and falls back to the other field when the chosen
    one is absent from the payload.

    Args:
        data: Statusline input JSON (as a dict), expected to carry a `model`
            object with `display_name` and/or `id` string fields.
        config: Configuration dictionary; expects a `model` sub-dict with
            `enabled` (bool), `source` ('display_name' or 'id'), `color`,
            and `bold`.

    Returns:
        ANSI-colored model string, or None when the feature is disabled, the
        `model` object is absent or malformed, or no usable name is present.
    """
    model_config = _as_dict(config.get('model'), DEFAULT_CONFIG['model'])
    if not model_config.get('enabled', False):
        return None

    model = data.get('model')
    if not isinstance(model, dict):
        return None
    model_dict = cast('dict[str, Any]', model)

    source = model_config.get('source', 'display_name')
    if source not in ('display_name', 'id'):
        source = 'display_name'
    fallback_key = 'id' if source == 'display_name' else 'display_name'
    text = model_dict.get(source) or model_dict.get(fallback_key)
    if not isinstance(text, str) or not text:
        return None

    return _paint(text, model_config.get('color'), 'magenta', model_config.get('bold') is True)


def _context_used_percent(data: dict[str, Any]) -> float | None:
    """Extract the context-window usage percentage from the statusline payload.

    Reads `data['context_window']` and returns the percentage of the model
    context window in use, clamped to 0-100. The value comes from
    `used_percentage` when it is numeric, or is computed from
    `total_input_tokens` / `context_window_size` otherwise.

    Args:
        data: Statusline input JSON (as a dict).

    Returns:
        The clamped percentage, or None when the payload carries no usable
        percentage (for example before the first API response, when both the
        percentage and the token fields are null or zero).
    """
    context_window = data.get('context_window')
    if not isinstance(context_window, dict):
        return None
    context_dict = cast('dict[str, Any]', context_window)

    total_input = context_dict.get('total_input_tokens')
    window_size = context_dict.get('context_window_size')

    pct_value = context_dict.get('used_percentage')
    if isinstance(pct_value, (int, float)):
        pct = float(pct_value)
    elif (
        isinstance(total_input, (int, float))
        and isinstance(window_size, (int, float))
        and window_size > 0
        and total_input > 0
    ):
        pct = float(round(total_input / window_size * 100))
    else:
        return None

    return max(0.0, min(100.0, pct))


def _as_number(value: object) -> float | None:
    """Return value as a float when it is an int or float, excluding bool.

    YAML parses `true` as a bool, and bool is an int subclass in Python, so a
    plain isinstance check would accept it as the number 1.

    Args:
        value: The candidate value, of unknown type.

    Returns:
        The value as a float for a non-bool int or float, otherwise None.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _context_window_size(data: dict[str, Any]) -> float | None:
    """Extract the model context-window size in tokens from the statusline payload.

    Args:
        data: Statusline input JSON (as a dict).

    Returns:
        The positive `context_window.context_window_size` value, or None when
        the payload carries no usable window size.
    """
    context_window = data.get('context_window')
    if not isinstance(context_window, dict):
        return None
    window_size = _as_number(cast('dict[str, Any]', context_window).get('context_window_size'))
    if window_size is None or window_size <= 0:
        return None
    return window_size


def _resolve_context_thresholds(window_size: float | None, config: dict[str, Any]) -> tuple[float, float]:
    """Resolve the warn and crit percentages that apply to a context window.

    Among the `context` block's `thresholds_by_window` entries whose
    `min_window` is at or below window_size, the one with the largest
    `min_window` supplies both thresholds, regardless of list order; an entry
    missing a numeric `min_window`, `warn_threshold`, or `crit_threshold` is
    ignored. A block without a list under that key gets no tiers when it sets
    its own numeric `warn_threshold` or `crit_threshold` (an explicit uniform
    pair wins over the packaged tiers) and the packaged tiers otherwise; an
    empty list disables tiering. When no tier applies (no tiers, window_size
    is None, or no entry's `min_window` is low enough), the block's flat
    `warn_threshold` and `crit_threshold` apply, each falling back to its
    packaged default when not numeric.

    Args:
        window_size: The session's context-window size in tokens, or None
            when unknown.
        config: Configuration dictionary; thresholds are read from its
            `context` sub-dict.

    Returns:
        A (warn_threshold, crit_threshold) tuple of percentages.
    """
    default_context = DEFAULT_CONFIG['context']
    context_config = _as_dict(config.get('context'), default_context)
    warn = _as_number(context_config.get('warn_threshold'))
    crit = _as_number(context_config.get('crit_threshold'))

    configured_tiers = context_config.get('thresholds_by_window')
    if isinstance(configured_tiers, list):
        tiers = cast('list[object]', configured_tiers)
    elif warn is not None or crit is not None:
        tiers = []
    else:
        tiers = cast('list[object]', default_context['thresholds_by_window'])

    if window_size is not None:
        best: tuple[float, float, float] | None = None
        for tier in tiers:
            if not isinstance(tier, dict):
                continue
            tier_dict = cast('dict[str, Any]', tier)
            min_window = _as_number(tier_dict.get('min_window'))
            tier_warn = _as_number(tier_dict.get('warn_threshold'))
            tier_crit = _as_number(tier_dict.get('crit_threshold'))
            if min_window is None or tier_warn is None or tier_crit is None:
                continue
            if min_window <= window_size and (best is None or min_window > best[0]):
                best = (min_window, tier_warn, tier_crit)
        if best is not None:
            return best[1], best[2]

    if warn is None:
        warn = float(default_context['warn_threshold'])
    if crit is None:
        crit = float(default_context['crit_threshold'])
    return warn, crit


def _classify_context_severity(pct: float, warn: float, crit: float) -> str:
    """Classify a context-usage percentage against a warn/crit threshold pair.

    Args:
        pct: Context-window usage percentage, clamped to 0-100.
        warn: Percentage from which usage counts as 'warn'.
        crit: Percentage from which usage counts as 'crit'.

    Returns:
        'crit' at or above crit, 'warn' at or above warn, 'ok' otherwise.
    """
    if pct >= crit:
        return 'crit'
    if pct >= warn:
        return 'warn'
    return 'ok'


def _resolve_context_severity(
    pct: float,
    window_size: float | None,
    config: dict[str, Any],
) -> tuple[str, object, str]:
    """Classify a context-usage percentage against the shared context thresholds.

    The `context` config block's thresholds (resolved for the session's window
    size by _resolve_context_thresholds) and its ok/warn/crit colors are the
    single source for every context-usage surface -- the ctx segment, the
    /compact reminder, and the context snapshot all resolve through them -- so
    the surfaces can never drift apart however the block is configured. Only
    thresholds and colors are read here; each surface keeps its own visibility
    switches.

    The thresholds mark where a manual /compact becomes advisable (warn) and
    urgent (crit), well before auto-compaction exhausts the window.

    Args:
        pct: Context-window usage percentage, clamped to 0-100.
        window_size: The session's context-window size in tokens, or None
            when unknown.
        config: Configuration dictionary; thresholds and colors are read from
            its `context` sub-dict.

    Returns:
        A (severity, color_value, default_color_name) tuple, where severity is
        'ok' (below the warn threshold), 'warn' (at or above it), or 'crit'
        (at or above the crit threshold), color_value is the configured color
        for that severity, and default_color_name is its fallback.
    """
    context_config = _as_dict(config.get('context'), DEFAULT_CONFIG['context'])
    warn, crit = _resolve_context_thresholds(window_size, config)
    severity = _classify_context_severity(pct, warn, crit)
    if severity == 'crit':
        return 'crit', context_config.get('crit_color'), 'red'
    if severity == 'warn':
        return 'warn', context_config.get('warn_color'), 'yellow'
    return 'ok', context_config.get('ok_color'), 'green'


def get_context_display(data: dict[str, Any], config: dict[str, Any]) -> str | None:
    """
    Format the context-window usage as a compact colored statusline segment.

    Reads `data['context_window']` and renders "{label}{percent}%" where the
    percentage of the model context window in use comes from
    `used_percentage` when it is numeric, or is computed from
    `total_input_tokens` / `context_window_size` otherwise. The percentage is
    clamped to 0-100 and colored by the shared context thresholds resolved for
    the payload's window size (ok below the warn threshold, warn at it or
    above, crit at the crit threshold or above); the same thresholds and
    colors drive the /compact reminder, so the segment and the reminder
    escalate together. The thresholds mark where a manual /compact becomes
    advisable (warn) and urgent (crit), well before auto-compaction exhausts
    the window.

    When `show_tokens` is enabled and the token fields are numeric, appends
    " (Nk/Mk)" with used and total tokens rounded to thousands (a 1M-token
    window renders as 1000k).

    Returns None when:
        - The context block is disabled.
        - `data['context_window']` is absent or not a dict.
        - No percentage is available: `used_percentage` is not numeric and the
          token fields cannot support the fallback computation (for example
          before the first API response, when both are null or zero).

    Args:
        data: Statusline input JSON (as a dict).
        config: Configuration dictionary; expects a `context` sub-dict with
            `enabled` (bool), `label` (str), `thresholds_by_window` (list),
            `warn_threshold` (int), `crit_threshold` (int), `ok_color`,
            `warn_color`, `crit_color`, `show_tokens` (bool), and `bold`.

    Returns:
        Colored compact segment string, or None when display is suppressed.
    """
    context_config = _as_dict(config.get('context'), DEFAULT_CONFIG['context'])
    if not context_config.get('enabled', True):
        return None

    context_window = data.get('context_window')
    if not isinstance(context_window, dict):
        return None
    context_dict = cast('dict[str, Any]', context_window)

    total_input = context_dict.get('total_input_tokens')
    window_size = context_dict.get('context_window_size')

    pct = _context_used_percent(data)
    if pct is None:
        return None

    _severity, color_value, default_name = _resolve_context_severity(pct, _context_window_size(data), config)

    label = context_config.get('label', 'ctx:')
    if not isinstance(label, str):
        label = 'ctx:'

    text = f'{label}{int(pct)}%'
    if (
        context_config.get('show_tokens', False)
        and isinstance(total_input, (int, float))
        and isinstance(window_size, (int, float))
        and window_size > 0
    ):
        text += f' ({round(total_input / 1000)}k/{round(window_size / 1000)}k)'

    return _paint(text, color_value, default_name, context_config.get('bold') is True)


def get_effort_display(data: dict[str, Any], config: dict[str, Any]) -> str | None:
    """
    Format the reasoning-effort level as a compact colored statusline segment.

    Reads `data['effort']` and renders "{label}{level}". The `effort` object
    is present only when the current model supports reasoning effort, so the
    segment auto-hides for models without an effort concept. The color comes
    from the `level_colors` mapping; a level missing from the mapping (for
    example an unknown future level name) still renders, using the block's
    fallback `color`.

    Returns None when:
        - The effort block is disabled.
        - `data['effort']` is absent or not a dict.
        - The `level` field is not a non-empty string.

    Args:
        data: Statusline input JSON (as a dict).
        config: Configuration dictionary; expects an `effort` sub-dict with
            `enabled` (bool), `label` (str), `color`, `level_colors` (dict
            mapping level names to color names), and `bold`.

    Returns:
        Colored compact segment string, or None when display is suppressed.
    """
    effort_config = _as_dict(config.get('effort'), DEFAULT_CONFIG['effort'])
    if not effort_config.get('enabled', True):
        return None

    effort = data.get('effort')
    if not isinstance(effort, dict):
        return None
    effort_dict = cast('dict[str, Any]', effort)

    level = effort_dict.get('level')
    if not isinstance(level, str) or not level:
        return None

    level_colors = _as_dict(effort_config.get('level_colors'), {})
    color_value: object = level_colors.get(level)
    if not isinstance(color_value, str) or color_value.lower() not in COLOR_MAP:
        color_value = effort_config.get('color')

    label = effort_config.get('label', 'eff:')
    if not isinstance(label, str):
        label = 'eff:'

    return _paint(f'{label}{level}', color_value, 'cyan', effort_config.get('bold') is True)


def _default_config_directory() -> Path:
    """Return Claude Code's default configuration directory, ~/.claude.

    Returns:
        The .claude directory in the user's home directory.
    """
    return Path.home() / '.claude'


def resolve_config_directory() -> Path:
    """Resolve the Claude Code configuration directory the session runs under.

    Both the profile label and the default snapshot directory derive from
    this one resolution, so they always name the same directory.

    Returns:
        $CLAUDE_CONFIG_DIR with surrounding blanks stripped and '~' expanded
        when it is set and non-empty, and ~/.claude otherwise.
    """
    configured = os.environ.get('CLAUDE_CONFIG_DIR', '').strip()
    return Path(configured).expanduser() if configured else _default_config_directory()


def _profile_label(base_label: str) -> str:
    """Name the profile, that is the configuration directory, the session runs under.

    The default directory is recognized however CLAUDE_CONFIG_DIR spells it:
    both paths are made absolute with symlinks and '..' resolved, then
    compared under the platform's case and separator rules.

    Args:
        base_label: The label for the default directory, ~/.claude.

    Returns:
        base_label for the default directory; otherwise the directory's name,
        or the whole path for a filesystem root, which has no name.
    """
    directory = resolve_config_directory()
    default_directory = _default_config_directory()
    if os.path.normcase(directory.resolve()) == os.path.normcase(default_directory.resolve()):
        return base_label
    return directory.name or str(directory)


def get_profile_display(config: dict[str, Any]) -> str | None:
    """
    Get the formatted profile segment if enabled.

    Shows which Claude Code profile the session runs under: the configured
    base label for the default configuration directory (~/.claude), and the
    directory's own name for any other one, such as "work" for
    CLAUDE_CONFIG_DIR=~/.claude/work.

    Args:
        config: Configuration dictionary; expects a `profile` sub-dict with
            `enabled` (bool), `base_label` (str), `color`, and `bold`.

    Returns:
        ANSI-colored profile label, or None when the block is disabled.
    """
    default_profile = DEFAULT_CONFIG['profile']
    profile_config = _as_dict(config.get('profile'), default_profile)
    if not profile_config.get('enabled', False):
        return None

    base_label = profile_config.get('base_label')
    if not isinstance(base_label, str) or not base_label:
        base_label = default_profile['base_label']

    return _paint(
        _profile_label(base_label),
        profile_config.get('color'),
        default_profile['color'],
        profile_config.get('bold') is True,
    )


def get_suffix_display(config: dict[str, Any]) -> str | None:
    """
    Get the formatted suffix display if configured.

    Args:
        config: Configuration dictionary with suffix settings

    Returns:
        ANSI-colored suffix string, or None if no suffix configured
    """
    suffix_config = _as_dict(config.get('suffix'), DEFAULT_CONFIG['suffix'])
    text = suffix_config.get('text', '')

    if not text:
        return None

    return _paint(text, suffix_config.get('color'), 'cyan', suffix_config.get('bold') is True)


def get_rate_limits_display(data: dict[str, Any], config: dict[str, Any]) -> str | None:
    """
    Format the Claude rate-limits status as a compact colored statusline segment.

    Reads `data['rate_limits']` and returns a compact string of the form
    `5h:N%  7d:M%` colored by threshold (ok_color below warn_threshold,
    warn_color at warn_threshold or above, crit_color at crit_threshold or
    above; GREEN/YELLOW/RED by default).

    The 5-hour and 7-day window key names are configurable via
    `config['rate_limits']['window_keys']` to accommodate any future change in
    Claude Code's statusline JSON schema. The keys verified at implementation
    time are documented in the YAML config.

    Returns None when:
        - The rate_limits feature is disabled.
        - `data['rate_limits']` is absent or not a dict.
        - Both configured windows are missing from the payload.
        - All window payloads are malformed (missing used_percentage or non-numeric).

    Args:
        data: Statusline input JSON (as a dict).
        config: Configuration dictionary; expects a `rate_limits` sub-dict with
                `enabled` (bool), `warn_threshold` (int), `crit_threshold` (int),
                `ok_color`, `warn_color`, `crit_color`, `bold`, and
                `window_keys` (dict mapping 'five_hour' and 'seven_day' to
                the verified JSON key names).

    Returns:
        Colored compact segment string, or None when display is suppressed.
    """
    rl_config = _as_dict(config.get('rate_limits'), {})
    if not rl_config.get('enabled', True):
        return None

    rate_limits = data.get('rate_limits')
    if not isinstance(rate_limits, dict) or not rate_limits:
        return None
    rate_limits_dict = cast('dict[str, Any]', rate_limits)

    window_keys = _as_dict(rl_config.get('window_keys'), {})
    warn = rl_config.get('warn_threshold', 70)
    crit = rl_config.get('crit_threshold', 90)
    if not isinstance(warn, (int, float)):
        warn = 70
    if not isinstance(crit, (int, float)):
        crit = 90
    bold = rl_config.get('bold') is True

    segments: list[str] = []
    for label, key in (('5h', window_keys.get('five_hour')), ('7d', window_keys.get('seven_day'))):
        if not key:
            continue
        window = rate_limits_dict.get(key)
        if not isinstance(window, dict):
            continue
        window_dict = cast('dict[str, Any]', window)
        pct = window_dict.get('used_percentage')
        if not isinstance(pct, (int, float)):
            continue
        if pct >= crit:
            color_value, default_name = rl_config.get('crit_color'), 'red'
        elif pct >= warn:
            color_value, default_name = rl_config.get('warn_color'), 'yellow'
        else:
            color_value, default_name = rl_config.get('ok_color'), 'green'
        segments.append(_paint(f'{label}:{int(pct)}%', color_value, default_name, bold))

    if not segments:
        return None
    return '  '.join(segments)


def get_compact_reminder_display(data: dict[str, Any], config: dict[str, Any]) -> str | None:
    """
    Format the /compact reminder as a notification segment when usage is high.

    Compacting well before the auto-compaction boundary preserves response
    quality, so this segment nudges toward a manual /compact early. Reads the
    context-window usage percentage from the statusline payload (via
    `used_percentage`, falling back to `total_input_tokens` /
    `context_window_size`) and renders the configured message once usage
    reaches the warn threshold the `context` block resolves for the payload's
    window size (warn_color styling), switching to the crit message at its
    crit threshold (crit_color styling). Thresholds and colors come
    exclusively from the `context` block -- the single source shared with the
    ctx segment -- while this block
    keeps its own `enabled` switch and message templates, so the reminder can
    be turned off without touching the segment (and the segment's `enabled`
    flag never suppresses the reminder). The `{percent}` placeholder in
    either message template is replaced with the integer usage percent.

    Returns None when:
        - The compact_reminder feature is disabled.
        - No usage percentage is available from the payload.
        - Usage is below the warn threshold resolved for the window.

    Args:
        data: Statusline input JSON (as a dict).
        config: Configuration dictionary; expects a `notifications` sub-dict
            with a `compact_reminder` sub-dict carrying `enabled` (bool),
            `message` (str), `crit_message` (str), and `bold`, plus the
            `context` sub-dict supplying the shared thresholds and colors.

    Returns:
        Colored notification segment string, or None when suppressed.
    """
    notifications_config = _as_dict(config.get('notifications'), DEFAULT_CONFIG['notifications'])
    reminder_config = _as_dict(
        notifications_config.get('compact_reminder'),
        DEFAULT_CONFIG['notifications']['compact_reminder'],
    )
    if not reminder_config.get('enabled', True):
        return None

    pct = _context_used_percent(data)
    if pct is None:
        return None

    severity, color_value, default_name = _resolve_context_severity(pct, _context_window_size(data), config)
    if severity == 'ok':
        return None

    if severity == 'crit':
        template = reminder_config.get('crit_message')
        fallback_template = 'ctx {percent}% - run /compact now'
    else:
        template = reminder_config.get('message')
        fallback_template = 'ctx {percent}% - consider /compact'
    if not isinstance(template, str) or not template:
        template = fallback_template

    # Plain replace instead of str.format keeps stray braces in a configured
    # message from raising.
    text = template.replace('{percent}', str(int(pct)))
    return _paint(text, color_value, default_name, reminder_config.get('bold') is True)


def get_notifications_display(data: dict[str, Any], config: dict[str, Any]) -> str | None:
    """
    Render the notifications row printed below the main status line.

    Collects the active notification segments (currently the /compact
    reminder) and joins them with the configured separator. The row is
    rendered only when the notifications feature is enabled AND at least one
    segment is active, so an empty row never reserves space.

    Args:
        data: Statusline input JSON (as a dict).
        config: Configuration dictionary; expects a `notifications` sub-dict
            with `enabled` (bool), `separator` (str), and per-notification
            sub-dicts.

    Returns:
        The joined notifications row string, or None when the feature is
        disabled or no notification is active.
    """
    notifications_config = _as_dict(config.get('notifications'), DEFAULT_CONFIG['notifications'])
    if not notifications_config.get('enabled', False):
        return None

    producers: tuple[Callable[[dict[str, Any], dict[str, Any]], str | None], ...] = (
        get_compact_reminder_display,
    )
    segments = [segment for producer in producers if (segment := producer(data, config))]
    if not segments:
        return None

    separator = notifications_config.get('separator')
    if not isinstance(separator, str):
        separator = ' | '
    return separator.join(segments)


def resolve_snapshot_directory(configured: object) -> Path:
    """Resolve the directory that holds the per-session context snapshots.

    Args:
        configured: The `context_snapshot.dir` config value. A non-empty
            string is used as the directory after expanding environment
            variables and '~'; anything else selects the default.

    Returns:
        The configured directory, or <config dir>/state/context-usage, where
        the config dir is $CLAUDE_CONFIG_DIR when set and non-empty, and
        ~/.claude otherwise.
    """
    if isinstance(configured, str) and configured.strip():
        return Path(os.path.expandvars(configured.strip())).expanduser()
    return resolve_config_directory() / 'state' / 'context-usage'


def _prune_snapshots(directory: Path, retention_days: object) -> None:
    """Delete snapshot-directory files left unmodified for retention_days days.

    Only names matching _PRUNABLE_NAME_RE are considered, so a directory
    shared with unrelated files never loses them. Every filesystem error is
    ignored: pruning is housekeeping and must never disturb the status line.

    Args:
        directory: The snapshot directory.
        retention_days: Age limit in days; a non-numeric, zero, or negative
            value disables pruning.
    """
    days = _as_number(retention_days)
    if days is None or days <= 0:
        return
    cutoff = time.time() - days * _SECONDS_PER_DAY
    try:
        entries = list(directory.iterdir())
    except OSError:
        return
    for entry in entries:
        if not _PRUNABLE_NAME_RE.fullmatch(entry.name):
            continue
        try:
            if entry.is_file() and entry.stat().st_mtime < cutoff:
                entry.unlink()
        except OSError:
            continue


def write_context_snapshot(data: dict[str, Any], config: dict[str, Any]) -> Path | None:
    """Record the session's context usage in its per-session snapshot file.

    Writes <dir>/<session_id>.json with the used percentage, window size,
    model id, severity, and effective thresholds, all resolved through the
    same functions the ctx segment uses, plus a UTC timestamp. When the
    payload carries no usage (before the first response, and right after
    /compact until the next one), the percentage and severity are recorded as
    null, so a reading from before the compaction never lingers. The file is
    replaced atomically (a temporary sibling renamed over it), so a reader
    sees either the previous record or the new one, never a partial write.
    Writing a session's first snapshot also prunes stale files.

    A filesystem error, or a home directory that cannot be determined, skips
    the write silently: the next status-line run writes a fresh snapshot, and
    the status line itself must never fail because of it.

    Args:
        data: Statusline input JSON (as a dict), expected to carry a
            `session_id`, a `context_window` object, and a `model` object.
        config: Configuration dictionary; expects a `context_snapshot`
            sub-dict with `enabled` (bool), `dir` (str), and `retention_days`
            (number; the packaged default applies when the key is omitted),
            plus the `context` sub-dict supplying the thresholds.

    Returns:
        The snapshot path when a snapshot was written, otherwise None (the
        feature is disabled, the session id is missing or not filename-safe,
        or the write failed).
    """
    snapshot_config = _as_dict(config.get('context_snapshot'), DEFAULT_CONFIG['context_snapshot'])
    if snapshot_config.get('enabled') is not True:
        return None

    session_id = data.get('session_id')
    if not isinstance(session_id, str) or not _SESSION_ID_RE.fullmatch(session_id):
        return None

    pct = _context_used_percent(data)
    window_size = _context_window_size(data)
    warn, crit = _resolve_context_thresholds(window_size, config)
    model = _as_dict(data.get('model'), {})
    model_id = model.get('id')

    record: dict[str, object] = {
        'schema': 1,
        'session_id': session_id,
        'model_id': model_id if isinstance(model_id, str) and model_id else None,
        'context_window_size': int(window_size) if window_size is not None else None,
        'used_percentage': pct,
        'severity': _classify_context_severity(pct, warn, crit) if pct is not None else None,
        'warn_threshold': warn,
        'crit_threshold': crit,
        'written_at': datetime.now(UTC).isoformat(timespec='seconds'),
    }

    temp_path: Path | None = None
    try:
        # Resolving the default directory needs the home directory, which
        # raises RuntimeError when it cannot be determined.
        directory = resolve_snapshot_directory(snapshot_config.get('dir'))
        path = directory / f'{session_id}.json'
        first_write = not path.exists()
        directory.mkdir(parents=True, exist_ok=True)
        temp_path = directory / f'{session_id}.json.{os.getpid()}.tmp'
        temp_path.write_text(json.dumps(record), encoding='utf-8')
        os.replace(temp_path, path)
    except (OSError, RuntimeError):
        if temp_path is not None:
            with contextlib.suppress(OSError):
                temp_path.unlink(missing_ok=True)
        return None

    if first_write:
        retention_days = snapshot_config.get('retention_days', DEFAULT_CONFIG['context_snapshot']['retention_days'])
        _prune_snapshots(directory, retention_days)
    return path


def get_git_branch(cwd: str) -> str:
    """Get current git branch or status.

    Args:
        cwd: Current working directory to check for git.

    Returns:
        Branch name, "HEAD@<hash>" for detached HEAD, "Not repo" if not a git repo,
        or "None" if branch cannot be determined.
    """
    try:
        # Try to get the current branch name
        result = subprocess.run(
            ['git', 'branch', '--show-current'],
            capture_output=True,
            text=True,
            timeout=2,
            cwd=cwd,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()

        # Check if we're in a git repo but in detached HEAD state
        result = subprocess.run(
            ['git', 'rev-parse', '--short', 'HEAD'],
            capture_output=True,
            text=True,
            timeout=2,
            cwd=cwd,
        )
        if result.returncode == 0 and result.stdout.strip():
            return f'HEAD@{result.stdout.strip()}'

        return 'None'
    except subprocess.TimeoutExpired:
        return 'None'
    except FileNotFoundError:
        # Git is not installed or not in PATH
        return 'Not repo'
    except OSError:
        # Directory doesn't exist or other OS error
        return 'Not repo'
    except Exception:
        return 'None'


def main() -> None:
    """Main entry point for status line hook."""
    try:
        # Load configuration (defaults merged with config file if provided)
        config_loader = _load_config_loader()
        config = config_loader.get_config_from_argv(DEFAULT_CONFIG)

        # Check if hook is enabled
        if not config.get('enabled', True):
            return

        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        print('Status: Error reading input')
        return
    except Exception:
        # If config loading fails, use defaults
        config = DEFAULT_CONFIG
        try:
            data = json.load(sys.stdin)
        except json.JSONDecodeError:
            print('Status: Error reading input')
            return

    if not isinstance(data, dict):
        print('Status: Error reading input')
        return
    payload = cast('dict[str, Any]', data)

    def render_branch() -> str | None:
        """Render the branch block, invoking git only when the block is enabled.

        Returns:
            ANSI-colored branch string, or None when the block is disabled.
        """
        branch_config = _as_dict(config.get('branch'), DEFAULT_CONFIG['branch'])
        if not branch_config.get('enabled', True):
            return None
        workspace = _as_dict(payload.get('workspace'), {})
        project_dir = workspace.get('project_dir', workspace.get('current_dir', ''))
        cwd = payload.get('cwd', project_dir)
        return get_branch_display(get_git_branch(cwd), config)

    renderers: dict[str, Callable[[], str | None]] = {
        'model': lambda: get_model_display(payload, config),
        'project': lambda: get_project_display(payload, config),
        'branch': render_branch,
        'session': lambda: get_session_display(payload, config),
        'lines': lambda: get_claude_lines_display(payload, config),
        'context': lambda: get_context_display(payload, config),
        'effort': lambda: get_effort_display(payload, config),
        'rate_limits': lambda: get_rate_limits_display(payload, config),
        'profile': lambda: get_profile_display(config),
        'suffix': lambda: get_suffix_display(config),
    }

    separator = config.get('separator')
    if not isinstance(separator, str):
        separator = ' | '

    # Render blocks in the configured sequence, skipping hidden ones (None)
    # and empty ones ('').
    parts: list[str] = []
    for name in _resolve_block_order(config):
        segment = renderers[name]()
        if segment:
            parts.append(segment)

    print(separator.join(parts))

    # Optional second row: printed only when the notifications feature is
    # enabled and at least one notification is active.
    notifications_row = get_notifications_display(payload, config)
    if notifications_row is not None:
        print(notifications_row)

    # The snapshot comes after the display, so recording it never delays or
    # disturbs what the user sees.
    sys.stdout.flush()
    write_context_snapshot(payload, config)


if __name__ == '__main__':
    main()
