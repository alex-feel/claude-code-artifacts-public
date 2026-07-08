# CLAUDE.md

Guidance for Claude Code when working in this repository.

This repository is a public library of reusable Claude Code artifacts. Each artifact type lives under its own `<type>/library/` directory (`skills/library/`, `hooks/library/`, `rules/library/`, `agents/library/`, `slash-commands/library/`) or, for environments, under `environments/library/` and `environments/templates/`. Every type also carries a short README describing its own layout, conventions, and installation.

## README maintenance

The root `README.md` is a **catalog organized by artifact category**, not a description of the directory tree. It deliberately has no "repository structure" section: a reader should meet the actual, useful artifacts first, then learn how to consume them.

### Category order

Present categories in this fixed order, skipping any that are currently empty:

1. Environments
2. Skills
3. Rules
4. Hooks
5. Agents
6. Slash commands

The order is fixed even as categories come and go; when a category gains its first artifact it takes its slot in this sequence, and the categories that remain are shown in this same relative order.

### A category appears only when it has content

A category earns its own `##` section in the root README only when the repository actually contains at least one artifact of that type under the type's `library/` directory. A type whose `library/` holds no artifacts yet — only its own `README.md` — is omitted from the root catalog until its first artifact lands. The goal is that every section a reader sees points at something real they can use, never at an empty placeholder.

### Section shape

Each populated category is a `##` section that opens with a short intro: what the type is (linked to the relevant Claude Code documentation), where the artifacts live, and a link to that type's own README for conventions and installation. Under the intro, each individual artifact gets a `###` subsection whose heading is the artifact's identifier (the skill directory name, the hook filename, and so on). The subsection is a concise, benefit-first description of what the artifact does and when to reach for it, ending with a link to the artifact file itself. Supporting files that are not standalone artifacts (for example a shared helper used by several hooks) are mentioned within the relevant category rather than given their own subsection.

### Keep the catalog in sync with the library

Adding, renaming, or removing an artifact is one change together with the README update that reflects it — never a code change now and a doc fix later. On every such change, harmonize the catalog with a three-part edit: ADD the new artifact's `###` subsection (and, when it is the first artifact of its type, add the whole category `##` section in its canonical slot); MODIFY the affected entries in place — a rename updates the artifact's `###` heading (its identifier) and its link path, and any change updates a description whose accuracy it affects; and REMOVE the subsection of a deleted artifact (and, when it was the last of its type, remove the now-empty category section). After editing, re-read the section end to end so it still reads as one coherent catalog rather than entries tacked on over time.
