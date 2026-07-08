#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["pyyaml"]
# ///
"""
Status line hook for Claude Code.

Displays: [model] | project_dir | git_branch | session_id | +N/-M | [rate_limits] | [update] | [suffix]

This script receives JSON via stdin and outputs a colored status line.
The first line of stdout becomes the status line text.

Features:
- Optional model display: shows the current model name at the start of the line
- Protected branch warning: main/master displayed in RED + BOLD
- Claude session line stats: shows lines added (GREEN) and removed (RED)
- Claude rate-limit display: compact 5h/7d usage percentages, threshold-colored
- Update availability indicator: shows "UPD v{version}" when a marker file is present
- Configurable suffix: optional custom text at end of status line

Segments in brackets are optional and appear only when enabled and present.

Configuration is loaded from external YAML file when provided.
"""

import importlib.util
import json
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


# ANSI color codes
class Colors:
    """ANSI escape codes for terminal colors."""

    RESET = '\033[0m'
    CYAN = '\033[36m'
    BLUE = '\033[34m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    RED = '\033[31m'
    MAGENTA = '\033[35m'
    BOLD = '\033[1m'


# Default configuration - used when no config file provided
DEFAULT_CONFIG: dict[str, Any] = {
    'enabled': True,
    'command_name': '',
    'model': {
        # Off by default: the shipped hook does not show the model segment.
        'enabled': False,
        # Which field of the statusline `model` object to show:
        # 'display_name' (for example "Opus") or 'id' (for example
        # "claude-opus-4-8"). Falls back to the other field when absent.
        'source': 'display_name',
        'color': 'magenta',
    },
    'protected_branches': ['main', 'master'],
    'suffix': {
        'text': '',
        'color': 'cyan',
    },
    'rate_limits': {
        'enabled': True,
        'warn_threshold': 70,
        'crit_threshold': 90,
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
}


# Mapping of color names to ANSI codes
COLOR_MAP: dict[str, str] = {
    'cyan': Colors.CYAN,
    'blue': Colors.BLUE,
    'green': Colors.GREEN,
    'yellow': Colors.YELLOW,
    'red': Colors.RED,
    'magenta': Colors.MAGENTA,
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
        The ANSI escape code for the resolved color.
    """
    name = value.lower() if isinstance(value, str) else default_name
    return COLOR_MAP.get(name, COLOR_MAP[default_name])


def get_branch_display(branch: str, config: dict[str, Any]) -> str:
    """
    Get the formatted branch display with appropriate color.

    Protected branches (main/master) are displayed in RED + BOLD as a warning.
    Other branches use the default GREEN color.

    Args:
        branch: Git branch name
        config: Configuration dictionary with protected_branches list

    Returns:
        ANSI-colored branch string
    """
    protected = config.get('protected_branches', DEFAULT_CONFIG['protected_branches'])
    if not isinstance(protected, (list, tuple, set)):
        protected = DEFAULT_CONFIG['protected_branches']
    if branch in protected:
        # Warning: RED + BOLD for protected branches
        return f'{Colors.BOLD}{Colors.RED}{branch}{Colors.RESET}'
    # Normal: GREEN for other branches
    return f'{Colors.GREEN}{branch}{Colors.RESET}'


def get_claude_lines_display(data: dict[str, Any]) -> str:
    """
    Get Claude's session line change statistics.

    Extracts total_lines_added and total_lines_removed from the cost data
    and formats them as colored statistics (GREEN for additions, RED for deletions).

    Args:
        data: Input JSON data containing cost statistics.

    Returns:
        Formatted string like "+N/-M" with ANSI colors, or empty string if both are 0.
    """
    cost = data.get('cost', {})
    added = cost.get('total_lines_added', 0)
    removed = cost.get('total_lines_removed', 0)

    if added == 0 and removed == 0:
        return ''

    return f'{Colors.GREEN}+{added}{Colors.RESET}/{Colors.RED}-{removed}{Colors.RESET}'


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
            `enabled` (bool), `source` ('display_name' or 'id'), and `color`.

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

    color_code = _resolve_color(model_config.get('color'), 'magenta')
    return f'{color_code}{text}{Colors.RESET}'


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

    color_code = _resolve_color(suffix_config.get('color'), 'cyan')
    return f'{color_code}{text}{Colors.RESET}'


def get_update_indicator(config: dict[str, Any]) -> str | None:
    """Check for configuration update availability and return a status indicator.

    Reads the existence-based marker file to determine if a newer version
    of the environment configuration is available. Returns a formatted
    YELLOW indicator string or None if no update is available.

    Args:
        config: Configuration dictionary with optional 'command_name' key.

    Returns:
        ANSI-colored update indicator string, or None if no update available
        or command_name is not configured.
    """
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

        return f'{Colors.YELLOW}UPD v{available_version}{Colors.RESET}'
    except Exception:
        return None


def get_rate_limits_display(data: dict[str, Any], config: dict[str, Any]) -> str | None:
    """
    Format the Claude rate-limits status as a compact colored statusline segment.

    Reads `data['rate_limits']` and returns a compact string of the form
    `5h:N%  7d:M%` colored by threshold (GREEN below warn_threshold,
    YELLOW at warn_threshold or above, RED at crit_threshold or above).

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
                and `window_keys` (dict mapping 'five_hour' and 'seven_day' to
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
            color = Colors.RED
        elif pct >= warn:
            color = Colors.YELLOW
        else:
            color = Colors.GREEN
        segments.append(f'{color}{label}:{int(pct)}%{Colors.RESET}')

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

    # Extract session_id (full ID for traceability)
    session_id = data.get('session_id', 'unknown')

    # Extract project directory (basename only)
    workspace = data.get('workspace', {})
    project_dir = workspace.get('project_dir', workspace.get('current_dir', ''))
    project_name = Path(project_dir).name if project_dir else 'unknown'

    # Get git branch
    cwd = data.get('cwd', project_dir)
    git_branch = get_git_branch(cwd)

    # Get line change statistics
    line_stats = get_claude_lines_display(data)

    # Build branch display
    branch_display = get_branch_display(git_branch, config)

    # Build status line parts. The model segment, when enabled, leads the line.
    parts: list[str] = []

    model_display = get_model_display(data, config)
    if model_display:
        parts.append(model_display)

    parts.extend([
        f'{Colors.YELLOW}{project_name}{Colors.RESET}',
        branch_display,
        f'{Colors.CYAN}{session_id}{Colors.RESET}',
    ])

    # Add line stats if present (separate block after session ID)
    if line_stats:
        parts.append(line_stats)

    # Add rate-limits display if available (between line stats and update indicator)
    rate_limits_display = get_rate_limits_display(data, config)
    if rate_limits_display:
        parts.append(rate_limits_display)

    # Add update indicator if available
    update_indicator = get_update_indicator(config)
    if update_indicator:
        parts.append(update_indicator)

    # Add suffix if configured
    suffix = get_suffix_display(config)
    if suffix:
        parts.append(suffix)

    print(' | '.join(parts))


if __name__ == '__main__':
    main()
