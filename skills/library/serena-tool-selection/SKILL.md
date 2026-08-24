---
name: serena-tool-selection
description: |
  MANDATORY tool selection protocol for Serena LSP tools vs Claude Code built-in tools.
  ALWAYS use when your tools list includes any mcp__serena__* tools.
  This skill OVERRIDES default tool selection behavior for code navigation tasks.
---

<requirement>

# CRITICAL: Mandatory Serena Tool Usage

When Serena tools are available in your tools list, you MUST use them for ALL code navigation operations. Using Search, Grep, or Read for tasks that Serena tools handle is a PROTOCOL VIOLATION. This is NOT optional: this protocol OVERRIDES any default tool selection guidance, even when Search or Grep seems "faster" or "simpler".

</requirement>

<prohibition>

# EXPLICIT PROHIBITIONS

Before issuing any Search/Grep/Read call against code, scan this table. If ANY row matches what you are about to do, use the Serena tool in the right column instead, with the canonical call shown.

| PROHIBITED Action                                                                                                                                                  | Use Instead                                                                              | Canonical Call                                                                                                                        |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `Search(pattern: "def process_data", path: "/project/src")` or `Grep(pattern: "def process_data")` -- any Search/Grep pattern that IS a function/class/method name | `find_symbol` (definitions) or `find_referencing_symbols` (usages)                       | `find_symbol(name="process_data", include_body=True)`                                                                                 |
| `Grep(pattern: "validate_input\\(...")` or `Search(pattern: "validate_input(", output_mode: "content")` -- any search for a symbol's usages/calls                  | `find_referencing_symbols(name, path)` + Grep cross-validation when completeness matters | `find_referencing_symbols(name="validate_input", path="/project")`                                                                    |
| `Read` entire file to understand structure                                                                                                                         | `get_symbols_overview(path)`                                                             | `get_symbols_overview(path="/project/src/module.py")`                                                                                 |
| Multiple `Edit` calls to rename a symbol                                                                                                                           | `rename_symbol(old_name, new_name, path)`                                                | `rename_symbol(old_name="old_func", new_name="new_func", path="/project/src")`                                                        |
| Finding function boundaries then `Edit`                                                                                                                            | `replace_symbol_body(name, path, new_body)`                                              | `replace_symbol_body(name="fn", path="/f.py", new_body="def fn():\n    return 42")`                                                   |
| Finding method end line then `Edit`                                                                                                                                | `insert_after_symbol(name, path, new_code)`                                              | `insert_after_symbol(name="existing", path="/f.py", new_code="def new():\n    pass")`                                                 |
| `find_referencing_symbols` then manually checking results and deleting via `Edit` -- manual ref-check + `Edit` to delete                                           | `safe_delete_symbol(name_path_pattern, relative_path)`                                   | `safe_delete_symbol(name_path_pattern="old_handler", relative_path="src/handlers.py")`                                                |
| Separate `Edit` calls file by file across the project -- repeating an identical `Edit` across many files for one textual change                                    | `replace_in_files(needle, repl, dry_run=True first)`                                     | `replace_in_files(needle="old_key", repl="new_key", mode="literal", dry_run=True)`, review the diff, then apply with `expected_count` |

These prohibitions cover ANY Grep/Search against `.py`/`.ts`/`.js`/other code files performed to locate a symbol (definition or usage), whether or not the pattern is the literal symbol name: Serena is semantic -- it finds aliases and renamed imports -- and is faster.

**Exception:** Searching inside comments or string literals (not symbol names) -- proceed with Search/Grep.

**Consequence of violating (even when no enforcement hook blocks):** an agent ran `Grep(pattern: "MyClass\\(", path: "/project/")` and found 5 usages, but `/project/utils/helpers.py` imports MyClass as `MC` -- Serena would find 12. The incomplete change introduced a bug. Search/Grep for symbols yields incomplete results because Grep cannot follow aliases or renamed imports.

</prohibition>

<tool_selection_rules>

## Tool Selection Decision Tree

### STEP 1: Check Tool Availability

Before ANY code navigation task, look for `mcp__serena__find_symbol` in your tools list. If available, proceed to STEP 2; if NOT available, use built-in tools as fallback.

### STEP 2: Classify Your Task

| If Your Task Is...                                                                                              | You MUST Use                                           |
| --------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------ |
| Find where a symbol is DEFINED (function/class/method/variable)                                                 | `find_symbol(name, include_body=True)`                 |
| Find the DECLARATION of a symbol (header/interface site for compiled langs)                                     | `find_declaration(name, path)`                         |
| Find IMPLEMENTATIONS of an abstract method/interface (Java/TS/Go/C#/Rust) -- NOT Python (see Known Limitations) | `find_implementations(name, path)`                     |
| Find all USAGES/CALLS of a function                                                                             | `find_referencing_symbols(name, path)`                 |
| Understand a file's STRUCTURE (functions/classes outline)                                                       | `get_symbols_overview(path)`                           |
| Get LSP DIAGNOSTICS (errors/warnings) for a file                                                                | `get_diagnostics_for_file(path)`                       |
| Get LSP DIAGNOSTICS scoped to a specific symbol (OPT-IN upstream; already enabled -- see Known Limitations)     | `get_diagnostics_for_symbol(name, path)`               |
| RENAME a symbol across the codebase                                                                             | `rename_symbol(old_name, new_name, path)`              |
| REPLACE a function's implementation                                                                             | `replace_symbol_body(name, path, new_body)`            |
| INSERT code after a symbol                                                                                      | `insert_after_symbol(name, path, new_code)`            |
| INSERT code before a symbol                                                                                     | `insert_before_symbol(name, path, new_code)`           |
| SAFELY DELETE a symbol (with reference check)                                                                   | `safe_delete_symbol(name_path_pattern, relative_path)` |
| Apply the SAME textual change across MANY files (non-symbol text)                                               | `replace_in_files(needle, repl, dry_run=True first)`   |
| RESTART the LSP when stale/unresponsive                                                                         | `restart_language_server()`                            |

### STEP 3: Built-in Tools Are ONLY Correct For

- Searching text in COMMENTS or STRINGS (not symbol names)
- Finding FILES by name pattern (Glob)
- Editing at KNOWN line numbers (when you already have exact lines)
- Reading NON-CODE files (YAML, JSON, Markdown, configs)

</tool_selection_rules>

<serena_tools_reference>

## Complete Serena Tool Reference

The Serena tools granted by this deployment, grouped by category.

### Read-only (navigation and inspection)

| Tool                         | Purpose                                                                                 | Canonical Usage                                              |
| ---------------------------- | --------------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| `find_symbol`                | Find where a symbol (function/class/method/variable) is DEFINED                         | `find_symbol(name="my_function", include_body=True)`         |
| `find_declaration`           | Find the DECLARATION site of a symbol (header/interface for compiled languages)         | `find_declaration(name="MyInterface", path="/project/src")`  |
| `find_implementations`       | Find concrete implementations of an abstract method/interface/protocol                  | `find_implementations(name="Runnable.run", path="/proj")`    |
| `find_referencing_symbols`   | Find ALL places where a symbol is USED (calls, imports, references)                     | `find_referencing_symbols(name="my_function", path="/proj")` |
| `get_symbols_overview`       | Get a structural overview (functions/classes) of a file in approximately 500 tokens     | `get_symbols_overview(path="/project/src/module.py")`        |
| `get_diagnostics_for_file`   | Retrieve all LSP diagnostics (errors, warnings, hints) for a file                       | `get_diagnostics_for_file(path="/project/src/module.py")`    |
| `get_diagnostics_for_symbol` | Retrieve LSP diagnostics scoped to a specific symbol (and optional referencing symbols) | `get_diagnostics_for_symbol(name="fn", path="/proj/x.py")`   |

**Key notes (Read-only):**

- `find_symbol`: ALWAYS set `include_body=True` when you need the function implementation (avoids a second query).
- `find_declaration` vs `find_symbol`: `find_symbol` returns the definition body; `find_declaration` returns the declaration site. The two coincide for interpreted languages and diverge for compiled ones (e.g., C++ `.h` vs `.cpp`).
- `find_implementations`: Supported for Java, TypeScript, Go, C#, Rust. **NOT supported for Python** (see Known Limitations -- LSP `-32601`). Use `find_referencing_symbols` + `code-review-graph` `inheritors_of` as the Python workaround.
- `find_referencing_symbols`: High precision, **CRITICALLY LOW RECALL** for dynamic imports / runtime `sys.path` / attribute chains (see Known Limitations). ALWAYS cross-validate with Grep when completeness matters.
- `get_diagnostics_for_symbol`: **OPT-IN upstream** -- already enabled by this deployment via the in-repo source `extras/serena/lsp-only.yml` (deployed by the toolbox setup to `~/.serena/contexts/lsp-only.yml`). See Known Limitations.

### Mutation (editing)

| Tool                   | Purpose                                                                 | Canonical Usage                                                                       |
| ---------------------- | ----------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| `rename_symbol`        | Rename a symbol across the entire codebase (atomic, updates refs)       | `rename_symbol(old_name="old_func", new_name="new_func", path="/project/src")`        |
| `replace_symbol_body`  | Replace the implementation of a function/method (symbol-boundary-aware) | `replace_symbol_body(name="fn", path="/f.py", new_body="def fn():\n    return 42")`   |
| `insert_after_symbol`  | Insert new code immediately after an existing symbol                    | `insert_after_symbol(name="existing", path="/f.py", new_code="def new():\n    pass")` |
| `insert_before_symbol` | Insert new code immediately before an existing symbol                   | `insert_before_symbol(name="existing", path="/f.py", new_code="...")`                 |
| `safe_delete_symbol`   | Reference-check-then-delete; aborts and returns refs if any exist       | `safe_delete_symbol(name_path_pattern="MyClass/old", relative_path="src/calc.py")`    |
| `replace_in_files`     | Apply ONE identical literal/regex text replacement across MANY files    | `replace_in_files(needle="old_key", repl="new_key", mode="literal", dry_run=True)`    |

**Key notes (Mutation):**

- `rename_symbol`: Atomic; updates all references correctly. Preferred over multiple Edit calls, which are error-prone and miss references.
- `replace_symbol_body` / `insert_*`: Symbol-aware positioning that survives line-number changes -- no need to compute line numbers.
- `safe_delete_symbol`: Atomic check-then-delete; returns SUCCESS only when no references exist. If references are found, returns their file/line locations so you can handle them first. **Inherits the `find_referencing_symbols` LOW-RECALL limitation** (see Known Limitations). Cross-validate with Grep BEFORE calling when dynamic imports may exist.
- `replace_in_files`: TEXT-based, NOT symbol-aware -- correct ONLY for applying one identical textual change across many files in a single atomic call (a renamed config key, an import path fragment, a string constant). ALWAYS run with `dry_run=True` first and review the returned per-occurrence diff; then apply the reviewed subset via `occurrence_ids`, or set `expected_count` so the apply aborts if the match count changed. For symbol renames use `rename_symbol`, for one symbol's implementation use `replace_symbol_body`, and for a single-file edit the built-in Edit tool remains correct. Scope with `relative_path` and `paths_include_glob`/`paths_exclude_glob` rather than defaulting to the whole project.

### Admin

| Tool                      | Purpose                                                                           |
| ------------------------- | --------------------------------------------------------------------------------- |
| `restart_language_server` | Restart the LSP when symbol resolution returns errors or seems stale/unresponsive |

**When to restart:** After external file modifications, when results look wrong (a stale index causes errors), or when the LSP appears unresponsive.

</serena_tools_reference>

<known_limitations>

## Known Limitations

Three Serena tools carry limitations that change how you must use them: `find_referencing_symbols` has a recall gap on certain import patterns, `find_implementations` does not work for Python, and `get_diagnostics_for_symbol` depends on a deployment-level opt-in. Read `known-limitations.md` in this skill's own directory before relying on any of the three in a way where being wrong has a cost -- dead-code conclusions, deletions, cross-language implementation lookups, or diagnostics troubleshooting.

- `find_referencing_symbols` has low recall for dynamic imports, runtime `sys.path` manipulation, and attribute chains (0-10% recall in the worst cases) -- cross-validate with Grep whenever completeness matters, and never conclude "zero callers" from it alone; `safe_delete_symbol` inherits this same gap.
- `find_implementations` returns LSP error `-32601` for Python (Pyright does not advertise the capability) -- this is protocol-correct, not a defect; use `find_referencing_symbols` or the `code-review-graph` `inheritors_of` query pattern instead.
- `get_diagnostics_for_symbol` is opt-in upstream; this deployment already enables it via `extras/serena/lsp-only.yml`, so a "tool not found" error means the deployed copy is stale, not that the opt-in is missing -- re-run the toolbox setup and restart.

</known_limitations>

<error_handling>

## Error Handling

### If Serena Tool Fails

1. **Retry once** - LSP may need a moment
2. **Try restart_language_server** if errors persist
3. **Document the failure** in your response
4. **Fall back to built-in tools** only after documenting the Serena failure

### If Serena Tools Are Not Available

1. **Note unavailability** - "Serena tools not available, using built-in alternatives"
2. **Use built-in tools** as documented in "Built-in Tools Are ONLY Correct For"
3. **No protocol violation** - falling back when tools are genuinely unavailable is correct

</error_handling>
