#!/usr/bin/env python3
"""
Claude Code Hook: Prevent Dangerous Bash Commands

This hook prevents Claude Code from executing dangerous Bash commands that could:
- Delete files or format disks (rm, format, dd, etc.)
- Spawn new shells or execute scripts (powershell, bash, wsl, etc.)
- Modify system settings (sudo, chmod, systemctl, etc.)
- Install or manage packages (apt, brew, pip, docker, etc.)

Event: PreToolUse
Matcher: Bash
Target: Bash tool commands
Action: Block operations containing dangerous command patterns
"""

import json
import sys

# COMPREHENSIVE LIST OF DANGEROUS BASH COMMANDS
# Organized by category for maintainability
DANGEROUS_COMMANDS = {
    'file_deletion': [
        'rm', 'rmdir', 'del',
    ],
    'disk_operations': [
        'format', 'mkfs', 'fdisk', 'dd', 'shred', 'wipefs',
    ],
    'shell_execution': [
        'powershell', 'pwsh', 'cmd', 'wsl', 'bash', 'sh',
    ],
    'windows_system': [
        'start', 'runas', 'net', 'sc', 'schtasks', 'reg', 'wmic',
        'msiexec', 'certutil', 'bitsadmin', 'forfiles', 'rundll32',
        'regsvr32', 'mshta', 'cscript', 'wscript', 'installutil',
        'regasm', 'regsvcs', 'msbuild',
    ],
    'privilege_escalation': [
        'sudo', 'su', 'doas',
    ],
    'permissions': [
        'chmod', 'chown', 'chgrp',
    ],
    'filesystem_mounting': [
        'mount', 'umount', 'diskutil', 'hdiutil',
    ],
    'service_management': [
        'launchctl', 'systemctl', 'service',
    ],
    'task_scheduling': [
        'crontab', 'at',
    ],
    'process_management': [
        'kill', 'killall', 'pkill',
    ],
    'system_control': [
        'reboot', 'shutdown', 'halt', 'init', 'telinit',
    ],
    'user_management': [
        'passwd', 'usermod', 'useradd', 'userdel', 'groupadd',
        'groupdel', 'visudo',
    ],
    'firewall': [
        'iptables', 'pfctl', 'firewall-cmd', 'ufw',
    ],
    'macos_security': [
        'csrutil', 'spctl', 'xattr',
    ],
    'macos_system': [
        'defaults', 'scutil', 'nvram', 'pmset',
    ],
    'macos_installer': [
        'installer', 'pkgutil', 'softwareupdate', 'mas',
    ],
    'package_managers': [
        'brew', 'pip', 'npm', 'yarn', 'gem',
        'apt', 'apt-get', 'yum', 'dnf', 'pacman',
        'zypper', 'snap', 'flatpak',
    ],
    'container_orchestration': [
        'docker', 'podman', 'kubectl', 'helm',
    ],
    'infrastructure_tools': [
        'terraform', 'vagrant', 'ansible', 'chef', 'puppet', 'salt',
    ],
}


def get_all_dangerous_commands() -> list[str]:
    """
    Get a flat list of all dangerous commands.

    Returns:
        list: All dangerous command names
    """
    all_commands: list[str] = []
    for category_commands in DANGEROUS_COMMANDS.values():
        all_commands.extend(category_commands)
    return all_commands


def get_command_category(command: str) -> str | None:
    """
    Get the category of a dangerous command.

    Args:
        command: The command to categorize

    Returns:
        str | None: Category name or None if not found
    """
    for category, commands in DANGEROUS_COMMANDS.items():
        if command in commands:
            return category
    return None


def extract_command_name(command_string: str) -> str | None:
    """
    Extract the primary command name from a command string.

    Handles cases like:
    - "sudo rm file" -> "sudo"
    - "npm install" -> "npm"
    - "  chmod 755" -> "chmod"
    - "command && other" -> "command"
    - "command | other" -> "command"

    Args:
        command_string: The full command string

    Returns:
        str | None: The primary command name or None if empty
    """
    if not command_string:
        return None

    # Remove leading/trailing whitespace
    command_string = command_string.strip()

    if not command_string:
        return None

    # Split by common command separators (pipe, and, semicolon, etc.)
    # and take the first part
    separators = [';', '&&', '||', '|', '\n']
    first_part = command_string
    for sep in separators:
        if sep in first_part:
            first_part = first_part.split(sep)[0].strip()

    # Extract the first word (the actual command)
    # Split by whitespace and take the first token
    tokens = first_part.split()
    if not tokens:
        return None

    command_name = tokens[0]

    # Remove path components if present (e.g., "/usr/bin/rm" -> "rm")
    # Handle both Unix and Windows paths
    if '/' in command_name:
        command_name = command_name.split('/')[-1]
    if '\\' in command_name:
        command_name = command_name.split('\\')[-1]

    # Remove file extensions (e.g., "command.exe" -> "command")
    if '.' in command_name:
        command_name = command_name.split('.')[0]

    return command_name


def check_dangerous_command(command: str) -> tuple[bool, str, str | None]:
    """
    Check if a command contains dangerous patterns.

    Args:
        command: The bash command to check

    Returns:
        tuple: (is_dangerous, matched_command, category)
    """
    if not command:
        return False, '', None

    # Extract the primary command name
    command_name = extract_command_name(command)

    if not command_name:
        return False, '', None

    # Check if the command is in our dangerous list
    dangerous_commands = get_all_dangerous_commands()

    # Case-insensitive comparison for command names
    command_name_lower = command_name.lower()

    for dangerous_cmd in dangerous_commands:
        if command_name_lower == dangerous_cmd.lower():
            category = get_command_category(dangerous_cmd)
            return True, dangerous_cmd, category

    return False, '', None


def get_category_description(category: str | None) -> str:
    """
    Get a human-readable description of a command category.

    Args:
        category: The category name

    Returns:
        str: Description of the category
    """
    descriptions = {
        'file_deletion': 'File/directory deletion',
        'disk_operations': 'Dangerous disk operations',
        'shell_execution': 'Shell/script execution',
        'windows_system': 'Windows system commands',
        'privilege_escalation': 'Privilege escalation',
        'permissions': 'Permission modification',
        'filesystem_mounting': 'Filesystem mounting',
        'service_management': 'Service management',
        'task_scheduling': 'Task scheduling',
        'process_management': 'Process management',
        'system_control': 'System control',
        'user_management': 'User/group management',
        'firewall': 'Firewall management',
        'macos_security': 'macOS security settings',
        'macos_system': 'macOS system settings',
        'macos_installer': 'macOS software installation',
        'package_managers': 'Package management',
        'container_orchestration': 'Container/orchestration',
        'infrastructure_tools': 'Infrastructure automation',
    }
    return descriptions.get(category or '', 'Unknown category')


def main() -> None:
    """Main hook execution function."""
    try:
        # Read JSON input from stdin
        input_data = json.load(sys.stdin)

        # Extract and validate event and tool
        hook_event_name = input_data.get('hook_event_name', '')
        tool_name = input_data.get('tool_name', '')

        # Initial validation - exit silently if conditions not met
        if hook_event_name != 'PreToolUse':
            sys.exit(0)

        if tool_name != 'Bash':
            sys.exit(0)

        # Extract tool input
        tool_input = input_data.get('tool_input', {})

        # Get the bash command
        command = tool_input.get('command', '')

        if not command:
            sys.exit(0)

        # Check if the command is dangerous
        is_dangerous, matched_cmd, category = check_dangerous_command(command)

        if is_dangerous:
            category_desc = get_category_description(category)

            # Build error message with clear explanation
            error_message = (
                f"BLOCKED: Dangerous Bash command '{matched_cmd}' detected.\n\n"
                f"Category: {category_desc}\n\n"
                f"This command is prohibited for security reasons:\n"
                f"- It could modify critical system settings\n"
                f"- It could delete or corrupt data\n"
                f"- It could compromise system security\n\n"
                f"Command attempted: {command[:200]}"
            )

            if len(command) > 200:
                error_message += '...'

            print(error_message, file=sys.stderr)
            sys.exit(2)  # block action and send feedback for Claude Code

        # Command is safe, allow execution
        sys.exit(0)

    except json.JSONDecodeError:
        sys.exit(0)  # Silent failure for invalid JSON

    except Exception:
        sys.exit(0)  # Silent failure for unexpected errors


if __name__ == '__main__':
    main()
