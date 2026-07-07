---
name: update-design
description: >
  Use when the user says "update the design doc", "sync ARC42STORIES.MD",
  "sync ARC42STORIES.MD", "reflect code changes in the design", or invokes
  /update-design. Also invoked by git-commit when commits affect architecture.
  Routes to the appropriate design doc workflow based on project type.
---

# Update Design Document

Reads project type, then loads the language-specific design sync workflow.
All types update a living design document to reflect current architecture —
only the document format and detection logic differ.

## Step 1 — Detect project type

```bash
python3 ~/.claude/skills/project/ctx.py
```

Read `PROJECT_TYPE` from the output. Also read `HAS_ARC42STORIES` for design doc routing.

`PROJECT_TYPE` may be comma-separated (e.g. `java,ts`) for mixed-language repos.

## Step 2 — Load workflow(s)

If PROJECT_TYPE contains a single language, load that workflow.

If PROJECT_TYPE contains multiple languages (e.g., `java,ts`), load each
applicable workflow and execute them in sequence — each updates the design
doc with its language-specific perspective.

| Language | File to read |
|---|---|
| `java` | `~/.claude/skills/update-design/java.md` |
| `ts` | `~/.claude/skills/update-design/typescript.md` |
| `python` | `~/.claude/skills/update-design/python.md` |
| `generic` (or no match) | `~/.claude/skills/update-design/typescript.md` (lightweight fallback) |

Read the file(s), then execute the workflow(s) they describe.

## Skill Chaining

**Invoked by:** [`git-commit`] alongside [`update-claude-md`]; [`adr`] suggests running this when an ADR documents a new component

**Invokes:** None (terminal skill in the chain)

**Complements:** `adr` — captures point-in-time decisions alongside this skill's living-doc updates
