# Handler: handoff_write

Write HANDOFF.md — a pointer document that gives the next session enough
context to resume immediately. References are read on demand; the handover
stays small. Git history is the archive.

**Token budget:** HANDOFF.md should be readable in under 200 tokens.

## What This Is Not

- **Not a project blog entry** — blog captures narrative for posterity;
  handover captures operational context for the next 24–48 hours.
- **Not a knowledge-garden entry** — cross-project gotchas go in the garden.
- **Not a replacement for CLAUDE.md** — auto-loaded; don't duplicate.

## Core Principles

1. **Write only deltas** — if unchanged since last handover, write
   `*Unchanged — git show HEAD~1:HANDOFF.md*`
2. **Git history is the archive** — single file, overwritten each session,
   always committed. Previous versions are free in git.
3. **Read nothing just to reference it** — if not in context, write the
   path. The next session reads on demand.

## Steps

### Step 1 — Check previous handover

```bash
git log --oneline -3 -- HANDOFF.md
git diff HEAD -- HANDOFF.md 2>/dev/null || git show HEAD:HANDOFF.md 2>/dev/null
```

### Step 2 — Recall from context

From conversation memory (do NOT read project files):
- What happened this session? (2-3 lines)
- What decisions were made? What didn't work?
- Active cross-module blockers? (Only work gated on another repo — each
  must have a tracked issue)
- Single most important next action?

**No What's Left or What's Next.** Work tracking is in `.plan` and GitHub.

### Step 3 — Gather cheap orientation

```bash
git log --oneline -6
git status --short
```

### Step 4 — Build references table (locate, don't read)

```bash
ls snapshots/ | sort | tail -1
ls blog/ | sort | tail -1
ls adr/ | sort | tail -3
```

### Step 5 — Write HANDOFF.md

Use the template in [handover-reference.md](../handover-reference.md).
For each section: changed → write full, unchanged → write reference.
Overwrite completely.

#### Content boundary check

Scan for personal characterisations, social context, meeting dynamics.
If flagged, present to author:
```
⚠️  Content boundary check — author decision required:
Sentence: "<exact sentence>"
Concern: <one-line reason>
Options: [K] Keep  [R] Rephrase  [D] Delete
```

#### Session rename

If the session has an auto-generated name (random three-word pattern),
suggest a descriptive name AFTER the handover is committed:
> Rename this session? Suggested: **`<Name>`** — type `/rename <Name>`

### Step 6 — Commit (required)

```bash
git -C $WORKSPACE add HANDOFF.md
git -C $WORKSPACE commit -m "docs: session handover"
```

Uncommitted HANDOFF.md is invisible to git history. Always commit.
