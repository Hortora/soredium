---
name: dependency-update
description: >
  Use when the user says "bump a version", "upgrade dependencies", "check for
  newer versions", "add a dependency", or "run audit" — for Java/Maven,
  TypeScript/npm, or Python/pip projects. Routes to the correct package manager
  based on project type declared in CLAUDE.md.
---

# Dependency Update

Reads project type, then loads the package-manager-specific workflow.

## Step 1 — Detect project type

```bash
python3 ~/.claude/skills/project/ctx.py
```

Read `PROJECT_TYPE` from the output.

`PROJECT_TYPE` may be comma-separated (e.g. `java,ts`) for mixed-language repos.
Check whether it **contains** a given language rather than matching exactly.

If type is missing or `generic`, inspect files:
- `pom.xml` present → treat as containing `java`
- `package.json` present → treat as containing `ts`
- `pyproject.toml` or `requirements.txt` present → treat as containing `python`

## Step 2 — Load package manager workflow(s)

If PROJECT_TYPE contains a single language, load that workflow.

If PROJECT_TYPE contains multiple languages (e.g., `java,ts`), load each
applicable workflow and run them in sequence.

| Language | File to read |
|---|---|
| `java` | `~/.claude/skills/dependency-update/maven.md` |
| `ts` | `~/.claude/skills/dependency-update/npm.md` |
| `python` | `~/.claude/skills/dependency-update/pip.md` |

Read the file(s), then execute the workflow(s) they describe.

## Skill Chaining

**Invoked by:** User directly — "bump versions", "check for updates", "add dependency"

**Invokes:** [`adr`] when major version upgrades warrant recording; [`git-commit`] after successful updates
