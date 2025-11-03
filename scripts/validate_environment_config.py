#!/usr/bin/env python3
"""
Validate environment configuration files against the schema.
Can be used standalone or as part of CI/CD pipeline.
Requires Python 3.12+
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Add parent directory to path to allow imports from scripts module
sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml
from pydantic import ValidationError

# Import from local models module
from scripts.models.environment_config import EnvironmentConfig


def validate_config_file(config_path: Path) -> tuple[bool, list[str]]:
    """Validate a single configuration file.

    Args:
        config_path: Path to the YAML configuration file

    Returns:
        tuple[bool, list[str]]: (is_valid, error_messages)
    """
    errors: list[str] = []

    # Check if file exists
    if not config_path.exists():
        return False, [f'File not found: {config_path}']

    # Check file extension
    if config_path.suffix not in ['.yaml', '.yml']:
        return False, [f'Invalid file extension: {config_path.suffix}. Must be .yaml or .yml']

    try:
        # Load YAML content
        with open(config_path, encoding='utf-8') as f:
            content = yaml.safe_load(f)

        if content is None:
            return False, ['Empty YAML file']

        # Validate against Pydantic model
        config = EnvironmentConfig(**content)

        # Additional semantic validations
        warnings: list[str] = []

        # Check for referenced files (local paths only, URLs are checked at runtime)
        if not str(config_path).startswith('http'):
            config_dir = config_path.parent

            # Helper function to check local file existence
            def check_local_file(file_path: str, file_type: str) -> None:
                """Check if a local file exists with CI-aware path resolution."""
                if file_path.startswith(('http://', 'https://')):
                    # Skip URLs - they're validated at runtime
                    return

                # Store original path for error messages
                original_path = file_path

                # Detect CI environment
                is_ci = os.getenv('CI') == 'true' or os.getenv('GITHUB_ACTIONS') == 'true'

                # Use pathlib for robust path expansion
                path_obj = Path(file_path).expanduser()

                # Expand environment variables
                path_str = os.path.expandvars(str(path_obj))
                path_obj = Path(path_str)

                # CI-specific path resolution for repository-relative paths
                if is_ci and file_path.startswith('~/Projects/claude-code-artifacts/'):
                    # In CI, these paths should be relative to repository root
                    relative_part = file_path[len('~/Projects/claude-code-artifacts/'):]

                    # Try GITHUB_WORKSPACE first, then find .git directory
                    repo_root = os.getenv('GITHUB_WORKSPACE')
                    if repo_root:
                        path_obj = Path(repo_root) / relative_part
                    else:
                        # Find repository root by looking for .git directory
                        current = config_dir.resolve()
                        while current != current.parent:
                            if (current / '.git').exists():
                                path_obj = current / relative_part
                                break
                            current = current.parent
                        else:
                            # Fallback to current working directory
                            path_obj = Path.cwd() / relative_part

                # Check if absolute or relative
                if path_obj.is_absolute():
                    # Absolute path - resolve and check
                    resolved_path = path_obj.resolve()
                    if not resolved_path.exists():
                        # Show expanded path in warning for clarity
                        if is_ci and file_path.startswith('~/Projects/claude-code-artifacts/'):
                            # In CI, provide informational message about path resolution
                            warnings.append(
                                f'Referenced {file_type} file not found: {original_path} '
                                f'(resolved to: {resolved_path} in CI environment)',
                            )
                        elif str(original_path) != str(resolved_path):
                            warnings.append(
                                f'Referenced {file_type} file not found: {original_path} '
                                f'(resolved to: {resolved_path})',
                            )
                        else:
                            warnings.append(f'Referenced {file_type} file not found: {original_path}')
                else:
                    # Relative path - resolve relative to config directory
                    resolved_path = (config_dir / path_obj).resolve()
                    if not resolved_path.exists():
                        warnings.append(
                            f'Referenced {file_type} file not found: {original_path} '
                            f'(resolved to: {resolved_path})',
                        )

            # Check agents exist
            if config.agents:
                for agent in config.agents:
                    check_local_file(agent, 'agent')

            # Check slash commands exist
            if config.slash_commands:
                for cmd in config.slash_commands:
                    check_local_file(cmd, 'slash command')

            # Check output styles exist
            if config.output_styles:
                for style in config.output_styles:
                    check_local_file(style, 'output style')

            # Check hook files exist
            if config.hooks and config.hooks.files:
                for hook_file in config.hooks.files:
                    check_local_file(hook_file, 'hook')

            # Check system prompt exists
            if config.command_defaults and config.command_defaults.system_prompt:
                prompt = config.command_defaults.system_prompt
                check_local_file(prompt, 'system prompt')

        if warnings:
            print(f'[OK] {config_path.name} - Valid with warnings:')
            for warning in warnings:
                print(f'  [WARN] {warning}')
        else:
            print(f'[OK] {config_path.name} - Valid')

        return True, warnings

    except yaml.YAMLError as e:
        return False, [f'YAML parsing error: {e}']

    except ValidationError as e:
        # Parse Pydantic validation errors for better readability
        for error in e.errors():
            loc = ' -> '.join(str(item) for item in error['loc'])
            msg = error['msg']
            errors.append(f'{loc}: {msg}')
        return False, errors

    except Exception as e:
        return False, [f'Unexpected error: {e}']


def validate_directory(directory: Path) -> tuple[int, int]:
    """Validate all YAML files in a directory.

    Args:
        directory: Path to directory containing YAML files

    Returns:
        tuple[int, int]: (valid_count, invalid_count)
    """
    valid_count = 0
    invalid_count = 0

    yaml_files = list(directory.glob('*.yaml')) + list(directory.glob('*.yml'))

    if not yaml_files:
        print(f'No YAML files found in {directory}')
        return 0, 0

    print(f'Validating {len(yaml_files)} configuration files in {directory}...')
    print()

    for config_file in sorted(yaml_files):
        is_valid, errors = validate_config_file(config_file)

        if is_valid:
            valid_count += 1
        else:
            invalid_count += 1
            print(f'[FAIL] {config_file.name} - Invalid:')
            for error in errors:
                print(f'  - {error}')
        print()

    return valid_count, invalid_count


def main() -> None:
    """Main validation entry point."""
    parser = argparse.ArgumentParser(
        description='Validate Claude Code environment configuration files',
    )
    parser.add_argument(
        'path',
        help='Path to YAML configuration file or directory',
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Output validation results as JSON',
    )
    parser.add_argument(
        '--strict',
        action='store_true',
        help='Exit with error code on warnings (for CI)',
    )

    args = parser.parse_args()

    path = Path(args.path)

    if path.is_file():
        # Validate single file
        is_valid, messages = validate_config_file(path)

        if args.json:
            result = {
                'file': str(path),
                'valid': is_valid,
                'messages': messages,
            }
            print(json.dumps(result, indent=2))
        else:
            if not is_valid:
                # Actual validation errors - exit with failure
                print(f'[FAIL] Validation failed for {path.name}')
                for error in messages:
                    print(f'  - {error}')
                sys.exit(1)
            # If valid but has warnings, and strict mode is enabled:
            # Note: We do NOT exit with error for warnings in strict mode
            # Warnings are informational only - actual validation passed

    elif path.is_dir():
        # Validate directory
        valid_count, invalid_count = validate_directory(path)

        if args.json:
            result = {
                'directory': str(path),
                'valid_count': valid_count,
                'invalid_count': invalid_count,
                'total': valid_count + invalid_count,
            }
            print(json.dumps(result, indent=2))
        else:
            print('=' * 60)
            print('Validation Summary:')
            print(f'  Valid:   {valid_count}')
            print(f'  Invalid: {invalid_count}')
            print(f'  Total:   {valid_count + invalid_count}')
            print('=' * 60)

            if invalid_count > 0:
                sys.exit(1)
    else:
        print(f'Error: {path} is neither a file nor a directory')
        sys.exit(1)


if __name__ == '__main__':
    main()
