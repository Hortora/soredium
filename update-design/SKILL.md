---
name: update-design
description: >
  Use when the user says "update the design doc", "sync DESIGN.md",
  "sync ARC42STORIES.MD", "reflect code changes in the design", or invokes
  /update-design. Also invoked by git-commit when commits affect architecture.
  Routes to the appropriate design doc workflow based on project type.
---

# Update Design Document

Reads project type from CLAUDE.md, then loads the language-specific design
sync workflow. All types update a living design document to reflect current
architecture — only the document format and detection logic differ.

## Step 1 — Detect project type

```bash
grep -A 2 "## Project Type" CLAUDE.md 2>/dev/null | grep "^type:"
```

Extract: `java` | `ts` | `python` | `generic`

## Step 2 — Load workflow

| Project type | File to read |
|---|---|
| `java` | `~/.claude/skills/update-design/java.md` |
| `ts` | `~/.claude/skills/update-design/typescript.md` |
| `python` | `~/.claude/skills/update-design/python.md` |
| `generic` | `~/.claude/skills/update-design/typescript.md` (lightweight fallback) |

Read the file, then execute the workflow it describes.

## Skill Chaining

**Invoked by:** [`git-commit`] alongside [`update-claude-md`]; [`adr`] suggests running this when an ADR documents a new component

**Invokes:** None (terminal skill in the chain)

**Complements:** `adr` — captures point-in-time decisions alongside this skill's living-doc updates
