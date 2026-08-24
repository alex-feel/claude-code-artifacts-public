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

Serena's default Python LSP backend is Pyright, which deliberately does NOT advertise the `implementationProvider` LSP capability (Microsoft design decision; unlikely to change). Per the LSP 3.17 specification, an unsupported method correctly returns JSON-RPC error `-32601 (MethodNotFound)`. This is PROTOCOL-CORRECT behavior, NOT a Serena or deployment defect. The tool works correctly for Java, TypeScript, Go, C#, and Rust.

**Python workarounds:**

1. **`find_referencing_symbols`** -- finds usages including subclass references; combined with manual inspection it surfaces concrete implementations.
2. **`code-review-graph` `inheritors_of` query pattern** -- when the `mcp__code-review-graph__*` tools are available, use `query_graph_tool(pattern="inheritors_of", target="ClassName")` to enumerate Python subclasses.

## Known Limitation: `get_diagnostics_for_symbol` is OPT-IN

This tool is OPTIONAL in Serena upstream (inherits `ToolMarkerOptional` -- disabled by default). This deployment launches Serena with `--context lsp-only` and already opts the tool in: the in-repo source file `extras/serena/lsp-only.yml` (the canonical source-of-truth in the repository that deploys this skill) lists it in `included_optional_tools:` alongside `restart_language_server`:

```yaml
included_optional_tools:
  - restart_language_server
  - get_diagnostics_for_symbol
```

The toolbox setup propagates that source file to `~/.serena/contexts/lsp-only.yml` via the `files-to-download` mechanism, so no manual enablement step is needed.

**Note on `~/.serena/serena_config.yml`:** this is a Serena-level (not deployment-level) configuration with NO in-repo source. Under the current `--context lsp-only` mode, editing it is not required and not recommended; the in-repo `extras/serena/lsp-only.yml` is the canonical source-of-truth for the deployed `included_optional_tools` list.

If the tool returns "tool not found" errors despite the YAML allow list including `mcp__serena__get_diagnostics_for_symbol`, the deployed copy at `~/.serena/contexts/lsp-only.yml` is stale (it predates the opt-in) -- not a YAML defect. Do NOT edit the deployed copy directly, since the toolbox setup overwrites it on the next install; re-run the toolbox setup so it re-downloads the current `extras/serena/lsp-only.yml`, then restart Claude Code (or call `mcp__serena__restart_language_server`) for the refreshed context to take effect.
