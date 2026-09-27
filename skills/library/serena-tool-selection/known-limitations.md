# Known Limitations

## Known Limitations of `find_referencing_symbols`

**CRITICAL: `find_referencing_symbols` has HIGH PRECISION but CRITICALLY LOW RECALL for certain import patterns.** Non-zero results CAN be trusted (zero false positives observed). Zero results CANNOT be trusted (90-100% false negatives in affected patterns).

### Failure Mode Taxonomy

#### Tier 1: Functional Caller Misses (Dangerous -- leads to false "dead code" conclusions)

| #   | Failure Mode                         | Mechanism                                  | Recall |
| --- | ------------------------------------ | ------------------------------------------ | ------ |
| 1   | Dynamic imports via `importlib.util` | `spec_from_file_location()` module loading | 0-10%  |
| 2   | Runtime `sys.path` + standard import | `sys.path.insert()` then `from X import Y` | ~0%    |
| 3   | Attribute chains on runtime objects  | `object.attribute.method()` at runtime     | ~0%    |

#### Tier 2: Non-Functional Reference Misses (Affects completeness metrics)

| #   | Failure Mode      | Mechanism                           | Recall |
| --- | ----------------- | ----------------------------------- | ------ |
| 4   | Mock references   | `mock.method.return_value` in tests | ~0%    |
| 5   | String references | Function name in strings/configs    | ~0%    |

### Mandatory Cross-Validation Rule

**When completeness matters** (dead code analysis, refactoring decisions, removal decisions):

1. Run `find_referencing_symbols` first for high-precision results
2. **ALWAYS** cross-validate with `Grep(pattern: "function_name")` to catch dynamically-loaded callers
3. Treat ZERO results from `find_referencing_symbols` as UNCERTAIN, not CONFIRMED
4. **NEVER conclude "zero callers" from `find_referencing_symbols` alone**

The Grep cross-validation is EXEMPT from any Serena tool-enforcement hook when used explicitly for reference completeness verification.

**Applies to `safe_delete_symbol` too:** it uses the same LSP reference-finding mechanism internally, so its "no references found" result carries the same false-negative risk. When deleting symbols that might be referenced through dynamic imports, cross-validate with Grep before calling `safe_delete_symbol`.

### When Cross-Validation Is NOT Required

- Simple navigation: "Jump to where this function is called" (precision is sufficient)
- Quick inspection: "Show me a few example usages" (non-exhaustive is acceptable)
- Rename operations: Use `rename_symbol` instead (LSP handles the rename scope)

## Known Limitation: `find_implementations` for Python (LSP -32601)

Serena's default Python language server is Pyright, which deliberately does NOT advertise the `implementationProvider` LSP capability (Microsoft design decision; unlikely to change). Per the LSP 3.17 specification, an unsupported method correctly returns JSON-RPC error `-32601 (MethodNotFound)`. This is PROTOCOL-CORRECT behavior, NOT a Serena or deployment defect. The tool works correctly for Java, TypeScript, Go, C#, and Rust. Serena also offers alternative Python language servers (such as basedpyright, ty, pyrefly, and jedi) selected through its own configuration; their `find_implementations` behavior is not covered here, so verify it before relying on it.

**Python workarounds:**

1. **`find_referencing_symbols`** -- finds usages including subclass references; combined with manual inspection it surfaces concrete implementations.
2. **`code-review-graph` `inheritors_of` query pattern** -- when the `mcp__code-review-graph__*` tools are available, use `query_graph_tool(pattern="inheritors_of", target="ClassName")` to enumerate Python subclasses.

## Known Limitation: `get_diagnostics_for_symbol` is OPT-IN

This tool is OPTIONAL in Serena upstream (inherits `ToolMarkerOptional` -- disabled by default). This deployment launches Serena with its `lsp-only` context, which already opts the tool in by listing it under `included_optional_tools` alongside `restart_language_server`:

```yaml
included_optional_tools:
  - restart_language_server
  - get_diagnostics_for_symbol
```

The environment setup installs that context as `~/.serena/contexts/lsp-only.yml`, so no manual enablement step is needed.

**Note on `~/.serena/serena_config.yml`:** this is Serena's global configuration, which the environment setup does not manage. Editing it is not required and not recommended for this tool: the `lsp-only` context is the single place that decides which optional tools are included.

If the tool returns "tool not found" errors, the installed context at `~/.serena/contexts/lsp-only.yml` predates the opt-in -- a stale install, not a configuration defect. Do NOT edit the installed copy directly, since the next environment setup overwrites it; re-run the environment setup so it installs the current context, then restart Claude Code. Serena reads its context only when its MCP server starts, so `restart_language_server` does NOT apply a refreshed context: it restarts the language servers alone.
