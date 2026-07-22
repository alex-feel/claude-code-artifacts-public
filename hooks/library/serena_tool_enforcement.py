#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["pyyaml"]
# ///
"""
Claude Code Hook: Serena Tool Enforcement (Command Hook, advisory).

This hook is the fast, deterministic first tier of Serena tool steering, and it
is NON-BLOCKING: it never denies a search. For Search/Grep calls it:
- stays silent when the search is scoped, by path or glob, to non-code file
  types only (every extension the scope determines is outside code_extensions);
- for code files whose pattern contains a symbol-definition keyword (def, class,
  function, etc.), ALLOWS the search and injects a one-time additionalContext
  nudge toward the semantic Serena tools;
- stays silent (no nudge) for every other pattern, which preserves the
  bare-symbol cross-validation grep that reference-completeness checks rely on.

It never blocks, because a hard deny would also block that legitimate
cross-validation grep and would strand the agent when Serena is unavailable or
cannot resolve a symbol. Steering is advisory and the text tool is always an
allowed fallback. This command tier is the cheap, deterministic fast path: it
only ever nudges and never blocks.

Event: PreToolUse
Matcher: Search|Grep
Target: Search and Grep tool operations
Action: Inject an advisory Serena nudge for symbol-keyword searches in code
        files; otherwise allow silently. Never blocks.

Exit Codes:
- 0: In all cases (advisory injection is non-blocking).

main() relies on its helpers being correct under the platform contract; only
one external-condition handler exists (json.JSONDecodeError for malformed stdin
from the Claude Code wrapper). There is no catch-all except Exception block:
an unexpected exception escapes to Python's default handler, surfacing the
traceback to the operator's TUI so the underlying code-quality defect can be
fixed.
"""

import importlib.util
import json
import re
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


def _load_json_output() -> ModuleType:
    """Dynamically load hook_json_output from the same directory."""
    loader_path = Path(__file__).parent / 'hook_json_output.py'
    spec = importlib.util.spec_from_file_location('hook_json_output', loader_path)
    if spec is None or spec.loader is None:
        raise ImportError(f'Cannot load hook_json_output from {loader_path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DEFAULT_CONFIG: dict[str, Any] = {
    'enabled': True,
    # ONLY code extensions - finite, manageable list
    # If extension is NOT in this list, the file is treated as non-code and APPROVED
    'code_extensions': [
        # Python
        '.py', '.pyw', '.pyi',
        # JavaScript/TypeScript
        '.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs',
        # JVM languages
        '.java', '.kt', '.kts', '.scala', '.clj', '.cljs',
        # Systems programming
        '.go', '.rs', '.c', '.cc', '.cpp', '.cxx', '.h', '.hpp', '.hxx', '.zig', '.nim', '.d',
        # C#/F#
        '.cs', '.fs', '.fsx',
        # Ruby
        '.rb',
        # PHP
        '.php',
        # Scripting
        '.lua', '.pl', '.pm',
        # Data science
        '.r', '.jl',
        # Functional
        '.ex', '.exs', '.erl', '.hrl', '.hs', '.elm', '.ml', '.mli',
        # Swift/Objective-C
        '.swift', '.m', '.mm',
        # Dart
        '.dart',
        # Hardware description
        '.v', '.sv', '.vhd', '.vhdl',
    ],
    'blocked_patterns': [
        # Python
        'def ', 'async def ', 'class ',
        # JavaScript/TypeScript
        'function ', 'export function', 'export class', 'export const', 'interface ',
        # Go
        'func ', 'struct ',
        # Rust
        'fn ', 'trait ', 'impl ',
    ],
    'nudge_message': {
        'header': 'SERENA SUGGESTION:',
        'explanation': "This pattern contains '{keyword}', which usually indicates a code-symbol or definition lookup.",
        'suggestion': (
            'For code symbols, the Serena tools resolve definitions and usages '
            'semantically -- following aliases and renamed imports that a text '
            'search misses:'
        ),
        'tools': [
            'find_symbol(name, include_body=True) - locate a definition',
            'find_referencing_symbols(name, path) - locate usages',
            'get_symbols_overview(path) - outline a file structure',
        ],
        'footer': (
            'Prefer the Serena tool when it is available. If Serena is '
            'unavailable or cannot resolve the symbol, or you are grepping a bare '
            'name to cross-validate reference completeness, this text search is '
            'the right choice.'
        ),
        'pattern_label': 'Pattern: {pattern}',
    },
}


def get_file_extension(file_path: str) -> str | None:
    """
    Extract file extension from path, handling glob patterns.

    Args:
        file_path: Path string, may include glob patterns like '**/*.py'

    Returns:
        Lowercase file extension with dot (e.g., '.py') or None if no extension
    """
    if not file_path:
        return None
    # Handle glob patterns like "**/*.py" or "*.yaml"
    path = Path(file_path)
    ext = path.suffix.lower()
    return ext or None


def _expand_glob_alternatives(value: str) -> list[str]:
    """
    Expand a single brace group in a glob into its alternatives.

    A glob like ``*.{ts,tsx}`` expands to ``['*.ts', '*.tsx']`` so each
    alternative can be inspected for its extension. A value with no brace group
    is returned unchanged as a single-element list.

    Args:
        value: A path or glob string, possibly containing one ``{a,b}`` group.

    Returns:
        The concrete glob/path strings the value stands for.
    """
    if not value:
        return []
    match = re.search(r'\{([^{}]+)\}', value)
    if match is None:
        return [value]
    prefix, suffix = value[: match.start()], value[match.end():]
    return [f'{prefix}{option.strip()}{suffix}' for option in match.group(1).split(',') if option.strip()]


def candidate_extensions(value: str) -> set[str]:
    """
    Collect the lowercase file extensions a path or glob determines.

    Brace groups are expanded first, then each alternative contributes its
    suffix. A value that determines no extension (a directory, a broad ``*`` or
    ``**/*`` glob, or an empty string) contributes nothing.

    Args:
        value: A path or glob string from the tool input.

    Returns:
        The extensions the value determines, each including the leading dot;
        empty when the value determines no extension.
    """
    extensions: set[str] = set()
    for alternative in _expand_glob_alternatives(value):
        ext = get_file_extension(alternative)
        if ext is not None:
            extensions.add(ext)
    return extensions


def is_non_code_target(tool_input: dict[str, Any], config: dict[str, Any]) -> bool:
    """
    Report whether the search is scoped to non-code file types only.

    The scope is read from the ``path`` and ``glob`` tool-input fields. The
    result is True only when those fields determine at least one extension AND
    every determined extension is outside ``code_extensions``. An indeterminate
    scope (a directory, a broad glob, or no path/glob at all) returns False so a
    definition-keyword search still receives the nudge; the keyword itself is the
    code-intent signal in that case.

    Args:
        tool_input: The PreToolUse ``tool_input`` mapping (reads ``path``, ``glob``).
        config: Configuration dictionary with a ``code_extensions`` list.

    Returns:
        True when the scope is determinably non-code, False otherwise.
    """
    code_extensions: list[str] = config.get('code_extensions', DEFAULT_CONFIG['code_extensions'])
    candidates = candidate_extensions(tool_input.get('path', '')) | candidate_extensions(tool_input.get('glob', ''))
    if not candidates:
        return False
    return all(ext not in code_extensions for ext in candidates)


def find_blocked_keyword(pattern: str, config: dict[str, Any]) -> str | None:
    """
    Check if pattern contains any blocked symbol keywords.

    Args:
        pattern: The search pattern to check
        config: Configuration dictionary with blocked_patterns list

    Returns:
        The matched keyword if found, None otherwise
    """
    blocked: list[str] = config.get('blocked_patterns', DEFAULT_CONFIG['blocked_patterns'])
    for keyword in blocked:
        if keyword in pattern:
            return keyword
    return None


def build_nudge_message(pattern: str, keyword: str, config: dict[str, Any]) -> str:
    """
    Build the advisory nudge message from config components.

    Args:
        pattern: The search pattern that triggered the nudge
        keyword: The symbol keyword that triggered the nudge
        config: Configuration dictionary with nudge_message settings

    Returns:
        Formatted advisory nudge message string
    """
    nudge_config = config.get('nudge_message', DEFAULT_CONFIG['nudge_message'])
    tools: list[str] = nudge_config.get('tools', [])

    # Build message parts
    header = nudge_config.get('header', '')
    explanation = nudge_config.get('explanation', '').format(keyword=keyword)
    suggestion = nudge_config.get('suggestion', '')
    footer = nudge_config.get('footer', '')
    pattern_label = nudge_config.get('pattern_label', '').format(pattern=pattern)

    # Construct tool list section
    tool_section = '\n'.join(f'  - {tool}' for tool in tools)

    return f'{header}\n\n{explanation}\n\n{suggestion}\n{tool_section}\n\n{footer}\n\n{pattern_label}'


def main() -> None:
    """Main hook execution function."""
    try:
        # Load configuration
        config_loader = _load_config_loader()
        config = config_loader.get_config_from_argv(DEFAULT_CONFIG)

        # Check if hook is enabled
        if not config.get('enabled', True):
            sys.exit(0)

        # Read JSON input from stdin
        input_data = json.load(sys.stdin)

        # Validate event type
        hook_event_name = input_data.get('hook_event_name', '')
        if hook_event_name != 'PreToolUse':
            sys.exit(0)

        # Validate tool name
        tool_name = input_data.get('tool_name', '')
        if tool_name not in ('Search', 'Grep'):
            sys.exit(0)

        # Extract tool input
        tool_input = input_data.get('tool_input', {})
        pattern = tool_input.get('pattern', '')

        # DECISION 1: the search is scoped (by path or glob) to non-code file
        # types only -> ALLOW SILENTLY (no nudge needed). An indeterminate scope
        # (a directory, a broad glob, or no path/glob) falls through so a
        # definition-keyword search still receives the nudge.
        if is_non_code_target(tool_input, config):
            sys.exit(0)

        # DECISION 2: Symbol-definition keyword in a code file -> ALLOW + NUDGE.
        # The search is NOT blocked: it runs as requested, and an advisory
        # additionalContext nudge toward the semantic Serena tools is injected.
        # A hard deny would also block the legitimate bare-name cross-validation
        # grep and would strand the agent when Serena cannot help, so steering is
        # advisory only and the text tool is always an allowed fallback.
        keyword = find_blocked_keyword(pattern, config)
        if keyword:
            nudge_message = build_nudge_message(pattern, keyword, config)
            try:
                json_output = _load_json_output()
                json_output.emit_additional_context('PreToolUse', nudge_message)
            except ImportError:
                print(nudge_message, file=sys.stderr)
            sys.exit(0)

        # DECISION 3: Allow silently with no nudge.
        # Patterns without a symbol-definition keyword (for example a bare
        # function or class name) pass through here intentionally. This preserves
        # Grep cross-validation of find_referencing_symbols results, a required
        # complement because LSP-based reference search has low recall for symbols
        # reached through dynamic imports, runtime sys.path manipulation, or
        # attribute chains on runtime objects; a zero-result reply from
        # find_referencing_symbols is UNCERTAIN, not CONFIRMED-zero, so this
        # advisory tier deliberately leaves these bare-name searches alone.
        sys.exit(0)

    except json.JSONDecodeError:
        # Malformed stdin from the Claude Code wrapper: external contract
        # violation, not a hook-internal defect. Exit 0 because the hook contract
        # requires non-blocking on stdin corruption (the model has no actionable
        # feedback to give).
        sys.exit(0)


if __name__ == '__main__':
    main()
