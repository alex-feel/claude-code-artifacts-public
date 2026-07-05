# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in this repository or in one of its artifacts, please report it privately.

1. **Do NOT** open a public issue.
2. Report it through [GitHub Security Advisories](https://github.com/alex-feel/claude-code-artifacts-public/security/advisories/new).
3. Include:
   - A description of the vulnerability.
   - Steps to reproduce, or a proof of concept.
   - The affected artifact (path) and its potential impact.
   - A suggested fix, if you have one.

You can expect an initial acknowledgment within a few days. Please give us a reasonable window to release a fix before any public disclosure.

## Scope

Artifacts in this repository can contain executable code and setup instructions — hook scripts, environment configurations that run installation commands, and slash commands or agents that drive automated actions. Relevant reports include, for example:

- A hook or setup command that behaves unsafely or leaks secrets.
- An environment configuration that fetches or executes untrusted content.
- Repository tooling (CI, validation scripts) that can be abused.

## Using artifacts safely

- Review any artifact before installing or running it, especially hooks and environment configurations.
- Never commit API keys, tokens, or other secrets into an artifact; use environment variables.
- Prefer pinning to a specific commit when consuming an artifact by raw URL in an automated setup.
