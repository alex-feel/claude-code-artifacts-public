#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["pyyaml"]
# ///
"""
Status line hook for Claude Code.

Displays: [model] | project | branch | session | [+N/-M] | [ctx:N%] | [eff:level] | [rate_limits] | [update] | [suffix]

This script receives JSON via stdin and outputs a colored status line.
The first line of stdout becomes the status line text.

The line is composed of named blocks: model, project, branch, session, lines,
context, effort, rate_limits, update, and suffix.

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
  threshold-colored (ok/warn/crit) as the auto-compaction point approaches,
  with optional token counts
- Reasoning effort display: the current effort level (low/medium/high/xhigh/max)
  with per-level colors; hidden for models without effort support
- Claude rate-limit display: compact 5h/7d usage percentages, threshold-colored
- Update availability indicator: shows "UPD v{version}" when a marker file is present
- Configurable suffix: optional custom text at end of status line

The 'order' list controls sequence only. Visibility is controlled exclusively
by each block's 'enabled' flag and by payload presence (the suffix block shows
only when its text is non-empty; the update block shows only when a command
name is configured, the marker file exists, and the block is enabled).

Configuration is loaded from external YAML file when provided.
"""

import importlib.util
import json
import subprocess
import sys
from collections.abc import Callable
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
    'update',
    'suffix',
)


# Default configuration - used when no config file provided
DEFAULT_CONFIG: dict[str, Any] = {
    'enabled': True,
    'command_name': '',
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
        # Percent-used thresholds. The percentage is measured against the
        # full model context window; auto-compaction triggers before the
        # window is exhausted, so crit_threshold approximates "compaction
        # imminent" rather than "window full".
        'warn_threshold': 70,
        'crit_threshold': 90,
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
    'update': {
        'enabled': True,
        'color': 'yellow',
        'bold': False,
    },
    'suffix': {
        'text': '',
        'color': 'cyan',
        'bold': False,
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


def get_context_display(data: dict[str, Any], config: dict[str, Any]) -> str | None:
    """
    Format the context-window usage as a compact colored statusline segment.

    Reads `data['context_window']` and renders "{label}{percent}%" where the
    percentage of the model context window in use comes from
    `used_percentage` when it is numeric, or is computed from
    `total_input_tokens` / `context_window_size` otherwise. The percentage is
    clamped to 0-100 and colored by the configured thresholds (ok below
    warn_threshold, warn at warn_threshold or above, crit at crit_threshold
    or above). The percentage is measured against the full model context
    window; auto-compaction triggers before the window is exhausted, so the
    crit threshold approximates "compaction imminent".

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
            `enabled` (bool), `label` (str), `warn_threshold` (int),
            `crit_threshold` (int), `ok_color`, `warn_color`, `crit_color`,
            `show_tokens` (bool), and `bold`.

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

    pct = max(0.0, min(100.0, pct))

    warn = context_config.get('warn_threshold', 70)
    crit = context_config.get('crit_threshold', 90)
    if not isinstance(warn, (int, float)):
        warn = 70
    if not isinstance(crit, (int, float)):
        crit = 90

    if pct >= crit:
        color_value, default_name = context_config.get('crit_color'), 'red'
    elif pct >= warn:
        color_value, default_name = context_config.get('warn_color'), 'yellow'
    else:
        color_value, default_name = context_config.get('ok_color'), 'green'

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


def get_update_indicator(config: dict[str, Any]) -> str | None:
    """Check for configuration update availability and return a status indicator.

    Reads the existence-based marker file to determine if a newer version
    of the environment configuration is available. Returns a formatted
    indicator string (YELLOW by default) or None if no update is available.

    Args:
        config: Configuration dictionary with an optional 'command_name' key
            and an `update` sub-dict with `enabled` (bool), `color`, and
            `bold`.

    Returns:
        ANSI-colored update indicator string, or None if no update available,
        command_name is not configured, or the block is disabled.
    """
    update_config = _as_dict(config.get('update'), DEFAULT_CONFIG['update'])
    if not update_config.get('enabled', True):
        return None

    command_name = config.get('command_name', '')
    if not command_name:
        return None

    try:
        marker_path = Path.home() / '.claude' / f'{command_name}-update-available.json'
        if not marker_path.exists():
            return None

        marker_data: dict[str, Any] = json.loads(marker_path.read_text(encoding='utf-8'))
        available_version = marker_data.get('available_version', '')
        if not available_version:
            return None

        return _paint(
            f'UPD v{available_version}',
            update_config.get('color'),
            'yellow',
            update_config.get('bold') is True,
        )
    except Exception:
        return None


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
        'update': lambda: get_update_indicator(config),
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


if __name__ == '__main__':
    main()
