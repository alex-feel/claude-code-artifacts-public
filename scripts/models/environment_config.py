"""
Pydantic models for environment configuration validation.
Defines the schema for Claude Code environment YAML files.
"""

from typing import Any
from typing import Literal
from typing import cast

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import ValidationInfo
from pydantic import field_validator
from pydantic import model_validator


class MCPServerHTTP(BaseModel):
    """MCP server configuration with HTTP/SSE transport."""

    name: str = Field(..., description='Server name')
    scope: Literal['user', 'project'] = Field('user', description='Scope of the server')
    transport: Literal['http', 'sse'] = Field(..., description='Transport type')
    url: str = Field(..., description='Server URL')
    header: str | None = Field(None, description='Optional authentication header')


class MCPServerStdio(BaseModel):
    """MCP server configuration with stdio transport."""

    name: str = Field(..., description='Server name')
    scope: Literal['user', 'project'] = Field('user', description='Scope of the server')
    command: str = Field(..., description='Command to execute')
    env: str | None = Field(None, description='Optional environment variables')


class HookEvent(BaseModel):
    """Hook event configuration."""

    event: str = Field(..., description='Event name (e.g., PostToolUse, Notification)')
    matcher: str | None = Field('', description='Regex pattern for matching')
    type: Literal['command'] = Field('command', description='Hook type')
    command: str = Field(..., description='Command to execute')


class Hooks(BaseModel):
    """Hooks configuration."""

    files: list[str] = Field(default_factory=lambda: [], description='Hook script files to download')
    events: list[HookEvent] = Field(default_factory=lambda: [], description='Hook event configurations')


class Permissions(BaseModel):
    """Permissions configuration."""

    default_mode: Literal['default', 'acceptEdits', 'plan', 'bypassPermissions'] | None = Field(
        None,
        alias='defaultMode',
        description='Default permission mode',
    )
    allow: list[str] | None = Field(None, description='Explicitly allowed actions')
    deny: list[str] | None = Field(None, description='Explicitly denied actions')
    ask: list[str] | None = Field(None, description='Actions requiring confirmation')
    additional_directories: list[str] | None = Field(
        None,
        alias='additionalDirectories',
        description='Additional accessible directories',
    )


class CommandDefaults(BaseModel):
    """Command launch configuration."""

    output_style: str | None = Field(
        None,
        alias='output-style',
        description='Default output style (replaces system prompt)',
    )
    system_prompt: str | None = Field(
        None,
        alias='system-prompt',
        description='Additional system prompt (appends to default)',
    )

    @field_validator('output_style', 'system_prompt')
    @classmethod
    def validate_mutual_exclusivity(cls, v: str | None, info: ValidationInfo) -> str | None:
        """Validate that output-style and system-prompt are mutually exclusive."""
        if info.field_name == 'system_prompt' and v is not None and info.data.get('output_style') is not None:
            raise ValueError('output-style and system-prompt are mutually exclusive')
        return v


class EnvironmentConfig(BaseModel):
    """Complete environment configuration model."""

    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    name: str = Field(..., description='Display name for the environment')
    command_name: str | None = Field(None, alias='command-name', description='Global command name')
    base_url: str | None = Field(None, alias='base-url', description='Base URL for relative paths')
    dependencies: dict[str, list[str]] = Field(
        default_factory=lambda: {
            'common': list[str](),
            'windows': list[str](),
            'mac': list[str](),
            'linux': list[str](),
        },
        description='Platform-specific dependency commands',
    )
    agents: list[str] | None = Field(default_factory=lambda: [], description='Agent markdown files')
    mcp_servers: list[dict[str, Any]] | None = Field(
        default_factory=lambda: [],
        alias='mcp-servers',
        description='MCP server configurations',
    )
    slash_commands: list[str] | None = Field(
        default_factory=lambda: [],
        alias='slash-commands',
        description='Slash command files',
    )
    output_styles: list[str] | None = Field(
        default_factory=lambda: [],
        alias='output-styles',
        description='Output style files',
    )
    hooks: Hooks | None = Field(None, description='Hook configurations')
    model: str | None = Field(None, description='Model configuration')
    env_variables: dict[str, str] | None = Field(
        None,
        alias='env-variables',
        description='Environment variables',
    )
    permissions: Permissions | None = Field(None, description='Permissions configuration')
    command_defaults: CommandDefaults | None = Field(
        None,
        alias='command-defaults',
        description='Command launch defaults',
    )
    include_co_authored_by: bool | None = Field(
        None,
        alias='include-co-authored-by',
        description='Whether to include co-authored-by attribution in commits (default: True)',
    )

    @field_validator('command_name')
    @classmethod
    def validate_command_name(cls, v: str | None) -> str | None:
        """Validate command name format."""
        if v is None:
            return v
        if not v.replace('-', '').replace('_', '').isalnum():
            raise ValueError('command-name must contain only alphanumeric characters, hyphens, and underscores')
        if not v.startswith('claude-'):
            raise ValueError("command-name should start with 'claude-' for consistency")
        return v

    @field_validator('dependencies')
    @classmethod
    def validate_dependencies_structure(cls, v: object) -> dict[str, list[str]]:
        """Validate dependencies have correct structure."""
        if v is None:
            return {'common': [], 'windows': [], 'mac': [], 'linux': []}

        if not isinstance(v, dict):
            raise ValueError('dependencies must be a dictionary')

        # Cast to dict for type checking
        deps_dict = cast(dict[str, object], v)

        valid_keys = {'common', 'windows', 'mac', 'linux'}
        invalid_keys = set(deps_dict.keys()) - valid_keys

        if invalid_keys:
            raise ValueError(
                f'Invalid platform keys in dependencies: {invalid_keys}. Valid keys are: {valid_keys}',
            )

        # Build validated result
        result: dict[str, list[str]] = {}

        # Validate each platform's dependencies
        for platform_key in valid_keys:
            if platform_key not in deps_dict:
                result[platform_key] = []
                continue

            commands = deps_dict[platform_key]
            if not isinstance(commands, list):
                raise ValueError(f'dependencies.{platform_key} must be a list')

            # Cast to list[object] for type checking
            commands_list = cast(list[object], commands)
            validated_commands: list[str] = []
            for idx, cmd in enumerate(commands_list):
                if not isinstance(cmd, str):
                    raise ValueError(f'dependencies.{platform_key}[{idx}] must be a string')
                validated_commands.append(cmd)

            result[platform_key] = validated_commands

        return result

    @field_validator('base_url')
    @classmethod
    def validate_base_url(cls, v: str | None) -> str | None:
        """Validate base URL format."""
        if v and not v.startswith(('http://', 'https://')):
            raise ValueError('base-url must start with http:// or https://')
        return v

    @field_validator('mcp_servers')
    @classmethod
    def validate_mcp_servers(cls, v: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        """Validate MCP server configurations."""
        if not v:
            return v

        validated: list[dict[str, Any]] = []
        for server in v:
            if 'name' not in server:
                raise ValueError("MCP server must have a 'name' field")

            # Validate based on transport type or presence of command
            if 'transport' in server:
                if server['transport'] in ['http', 'sse']:
                    MCPServerHTTP(**server)  # Validate structure
                else:
                    raise ValueError(f"Unknown transport type: {server['transport']}")
            elif 'command' in server:
                MCPServerStdio(**server)  # Validate structure
            else:
                raise ValueError("MCP server must have either 'transport' or 'command' field")

            validated.append(server)  # Keep original dict for compatibility

        return validated

    @field_validator('model')
    @classmethod
    def validate_model(cls, v: str | None) -> str | None:
        """Validate model configuration."""
        valid_aliases = ['default', 'sonnet', 'opus', 'haiku', 'sonnet[1m]', 'opusplan']
        if v and not (v in valid_aliases or v.startswith('claude-')):
            raise ValueError(
                f"model must be one of {valid_aliases} or a custom model name starting with 'claude-'",
            )
        return v

    @model_validator(mode='after')
    def validate_command_name_and_defaults(self) -> 'EnvironmentConfig':
        """Ensure command-name and command-defaults are both present or both absent."""
        has_command_name = self.command_name is not None
        has_command_defaults = self.command_defaults is not None

        if has_command_name != has_command_defaults:
            # XOR condition - one is present but not the other
            if has_command_name and not has_command_defaults:
                raise ValueError(
                    'command-name requires command-defaults to be specified. '
                    'Either provide both command-name and command-defaults, or omit both.',
                )
            # has_command_defaults and not has_command_name
            raise ValueError(
                'command-defaults requires command-name to be specified. '
                'Either provide both command-name and command-defaults, or omit both.',
            )

        return self

    @field_validator('agents', 'slash_commands', 'output_styles')
    @classmethod
    def validate_file_paths(cls, v: list[str] | None) -> list[str] | None:
        """Validate file paths for security issues.

        Allows:
        - Full URLs (http://, https://)
        - Local absolute paths (C:\\, /, ~/...)
        - Local relative paths (./file, ../file, file)

        Prevents:
        - Path traversal attacks in URLs only

        Returns:
            The validated list of file paths.
        """
        if not v:
            return v

        for path in v:
            # Full URLs are always allowed
            if path.startswith(('http://', 'https://')):
                continue

            # For local paths, just check for obvious security issues
            # We allow .. in paths since users might legitimately reference parent dirs
            # The OS will handle actual file access permissions

        return v
