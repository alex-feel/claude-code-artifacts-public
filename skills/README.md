# Skills

[Agent Skills](https://docs.claude.com/en/docs/claude-code/skills) are multi-file packages that extend Claude Code with specialized, progressively disclosed capabilities.

## Layout

Each skill is a directory under `skills/library/` containing a `SKILL.md` entry point plus any supporting files:

```text
skills/library/
└── <skill-name>/
    ├── SKILL.md            # required: YAML frontmatter (name, description) + instructions
    ├── references/         # optional: reference material loaded on demand
    ├── scripts/            # optional: helper scripts
    └── assets/             # optional: templates and other assets
```

## Conventions

- The directory name is the skill's kebab-case identifier and should match the `name` in `SKILL.md` frontmatter.
- `SKILL.md` must start with YAML frontmatter that includes a `name` and a `description` (the description drives when Claude activates the skill).
- Semantic XML-style tags inside `SKILL.md` must be balanced — this is checked by the `validate-xml-tags` pre-commit hook.

## Consuming a skill

There are two ways to install a skill from this library into Claude Code, and the right one depends on how complex the skill is.

### Simple skills — the toolbox `skills` key

The [Claude Code Toolbox](https://github.com/alex-feel/claude-code-toolbox) `skills` key installs a skill by copying an explicit, hand-listed set of files. It suits **simple skills only** — a single directory whose files you can enumerate:

```yaml
skills:
  - name: "my-skill"
    base: "https://raw.githubusercontent.com/alex-feel/claude-code-artifacts-public/main/skills/library/my-skill"
    files:
      - "SKILL.md"
      - "references/guide.md"
```

`SKILL.md` is always required in `files`. Because every file must be listed by hand, this approach does not scale to large or deeply nested skills. See the toolbox [Environment Configuration Guide](https://github.com/alex-feel/claude-code-toolbox/blob/main/docs/environment-configuration-guide.md) for details.

### Rich skills — the `skills` CLI (`npx skills`)

For larger skills, skills with many or nested supporting files, or when installing several skills at once, it is usually better to use the `skills` CLI from an environment's `dependencies` block. It resolves and copies each skill's full contents for you, so you do not enumerate files:

```yaml
dependencies:
  common:
    - npx --y skills@latest add alex-feel/claude-code-artifacts-public --skill my-skill -g -a --copy claude-code -y
```

Pin a specific CLI version for reproducibility. For a real-world example that installs many skills this way, see the `dependencies` block of [`aegis.yaml`](https://github.com/alex-feel/claude-code-artifacts/blob/main/environments/library/aegis.yaml) in the source repository.
