#!/usr/bin/env python3
"""
Validate XML-style semantic tags in Markdown files.

This script checks for common XML tag errors in Markdown files:
- Unclosed tags (<role> without </role>)
- Mismatched tags (<role> closed by </constraints>)
- Improper nesting (<outer><inner></outer></inner>)

It skips content within fenced code blocks to avoid false positives.
Designed for use as a pre-commit hook.

Requires Python 3.12+
"""

import re
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class TagInfo:
    """Information about an XML tag found in content."""

    name: str
    line_number: int
    is_closing: bool


def remove_fenced_code_blocks(content: str) -> tuple[str, dict[int, int]]:
    """
    Remove fenced code blocks from content and build line number mapping.

    Args:
        content: The original file content

    Returns:
        tuple[str, dict[int, int]]: Cleaned content and mapping from cleaned line numbers
            to original line numbers
    """
    lines = content.split('\n')
    result_lines: list[str] = []
    line_mapping: dict[int, int] = {}
    in_code_block = False
    result_line_num = 0

    for original_line_num, line in enumerate(lines, 1):
        # Check for code block delimiter (``` with optional language specifier)
        if re.match(r'^```', line.strip()):
            in_code_block = not in_code_block
            # Include empty line to preserve some structure but mark it as empty
            result_lines.append('')
            result_line_num += 1
            line_mapping[result_line_num] = original_line_num
            continue

        if in_code_block:
            # Replace code block content with empty lines to preserve line count
            result_lines.append('')
            result_line_num += 1
            line_mapping[result_line_num] = original_line_num
        else:
            result_lines.append(line)
            result_line_num += 1
            line_mapping[result_line_num] = original_line_num

    return '\n'.join(result_lines), line_mapping


def extract_tags(content: str) -> list[TagInfo]:
    """
    Extract all XML-style tags from content.

    Matches tags with lowercase_snake_case names and optional attributes.
    Pattern: <tag_name> or </tag_name> or <tag_name attr="value">

    Args:
        content: The content to search for tags

    Returns:
        list[TagInfo]: List of found tags with their information
    """
    # Pattern matches opening and closing XML tags
    # Group 1: optional "/" for closing tags
    # Group 2: tag name (lowercase_snake_case)
    # Group 3: optional attributes (anything before >)
    tag_pattern = re.compile(r'<(/?)([a-z][a-z0-9_]*)(?:\s+[^>]*)?>')

    tags: list[TagInfo] = []
    lines = content.split('\n')

    for line_num, line in enumerate(lines, 1):
        for match in tag_pattern.finditer(line):
            is_closing = match.group(1) == '/'
            tag_name = match.group(2)
            tags.append(TagInfo(name=tag_name, line_number=line_num, is_closing=is_closing))

    return tags


def validate_xml_tags(file_path: Path) -> list[str]:
    """
    Validate XML tags in a Markdown file.

    Uses a stack-based algorithm to detect:
    - Unclosed tags
    - Mismatched closing tags
    - Improper nesting

    Args:
        file_path: Path to the Markdown file to validate

    Returns:
        list[str]: List of error messages (empty if valid)
    """
    content = file_path.read_text(encoding='utf-8')

    # Remove fenced code blocks and get line number mapping
    cleaned_content, line_mapping = remove_fenced_code_blocks(content)

    # Extract tags from cleaned content
    tags = extract_tags(cleaned_content)

    errors: list[str] = []
    stack: list[TagInfo] = []  # Stack of opening tags

    for tag in tags:
        # Map cleaned line number to original line number
        original_line = line_mapping.get(tag.line_number, tag.line_number)

        if tag.is_closing:
            if not stack:
                errors.append(f'Line {original_line}: Closing tag </{tag.name}> without opening tag')
            else:
                open_tag = stack.pop()
                open_original_line = line_mapping.get(open_tag.line_number, open_tag.line_number)

                if open_tag.name != tag.name:
                    errors.append(
                        f'Line {original_line}: Mismatched tags - <{open_tag.name}> (line {open_original_line}) '
                        f'closed by </{tag.name}>',
                    )
        else:
            # Create a new TagInfo with the original line number for the stack
            stack.append(TagInfo(name=tag.name, line_number=tag.line_number, is_closing=False))

    # Check for unclosed tags
    for tag in stack:
        original_line = line_mapping.get(tag.line_number, tag.line_number)
        errors.append(f'Line {original_line}: Unclosed tag <{tag.name}>')

    return errors


def main() -> int:
    """
    Main entry point for the XML tag validator.

    Processes command-line arguments and validates each file.

    Returns:
        int: Exit code (0 for success, 1 for errors found)
    """
    if len(sys.argv) < 2:
        print('Usage: validate_xml_tags.py <file1.md> [file2.md ...]', file=sys.stderr)
        return 1

    has_errors = False

    for file_arg in sys.argv[1:]:
        file_path = Path(file_arg)

        if not file_path.exists():
            print(f'File not found: {file_path}', file=sys.stderr)
            has_errors = True
            continue

        errors = validate_xml_tags(file_path)

        if errors:
            has_errors = True
            print(f'{file_path}:')
            for error in errors:
                print(f'  {error}')

    return 1 if has_errors else 0


if __name__ == '__main__':
    sys.exit(main())
