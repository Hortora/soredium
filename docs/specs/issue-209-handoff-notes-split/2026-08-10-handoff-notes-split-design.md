# HANDOFF/NOTES Split — Design Spec

**Issue:** Hortora/soredium#209
**Branch:** issue-209-handoff-notes-split
**Date:** 2026-08-10

## Problem

HANDOFF.md serves two roles with different lifecycles: ephemeral session narrative (overwritten each session) and persistent notes (should accumulate across branches). The overwrite model destroys accumulated notes.

## Design

### HANDOFF.md stays ephemeral — now branch-scoped

Overwritten each session. Token budget under 200. Git history is the archive. **Post-spec update:** HANDOFF.md is now committed to the workspace branch (not main) so it travels with the work through pause/resume cycles. Each branch carries its own handoff.

### NOTES.md on an orphan branch worktree

```
$WORKSPACE/.notes/           ← permanent git worktree
$WORKSPACE/.notes/NOTES.md   ← the file
```

The `notes` branch is an orphan — no shared history with main or any feature branch. Merge conflicts are impossible by design (same pattern as gh-pages).

**One-time setup** (in workspace-init):
```bash
git -C $WORKSPACE worktree add --orphan -b notes .notes
echo "# Notes" > $WORKSPACE/.notes/NOTES.md
git -C $WORKSPACE/.notes add NOTES.md
git -C $WORKSPACE/.notes commit -m "init notes"
```

**Format:** Append-only, date headers, plain markdown.
```markdown
# Notes

## 2026-08-10

- Remember to check auth token expiry after the migration
- When touching slot_manager, the test suite takes ~60s — run specific classes

## 2026-08-09

- engine reindex needed after next schema change
```

### Read when deciding what to do, not when already tasked

**Show notes when:**
- `work` with no issue (what-next mode) — browsing, notes are context
- After work-end completes — back on main, deciding what's next
- `/brief` — orientation summary

**Don't show notes when:**
- `work start #N` — already have a task, notes are noise
- `work continue` — resuming, HANDOFF.md has the context

Surface the most recent date section — don't dump the whole file.

```
Notes (2026-08-10):
  - Remember to check auth token expiry after the migration
  - When touching slot_manager, the test suite takes ~60s
```

### Writable mid-session

Append to `$WORKSPACE/.notes/NOTES.md` anytime — filesystem write, then commit to the notes branch:

```bash
# Append
echo "- new note" >> $WORKSPACE/.notes/NOTES.md
git -C $WORKSPACE/.notes add NOTES.md
git -C $WORKSPACE/.notes commit -m "note: <summary>"
```

No interaction with main, feature branches, or slots. The worktree is always on the `notes` branch.

### Default ON in wrap checklist

Flip handover item 8 from `[ ]` to `[x]`. Prompt: "anything to note for later?" User can skip with Enter.

## Files changed

| File | Change |
|------|--------|
| `workspace-init/SKILL.md` | Add orphan branch + worktree creation step |
| `handover/SKILL.md` | Flip item 8 default to ON |
| `work/SKILL.md` | Read NOTES.md in Step 2a (what-next, no issue specified) |
| `work-end/SKILL.md` | Surface NOTES.md after Step 5 close summary |
| `brief/SKILL.md` | Include notes in orientation output |

### Slot access

Slots write to the original workspace's `.notes/NOTES.md` via `resolve_original_repo`. Filesystem append — no git involved until wrap time. The original workspace's `.notes/` worktree is always there regardless of what branch the original is on.

### Commit cadence

Notes are appended to the filesystem immediately. Committed to the orphan branch at wrap time (batch). Push is optional — convenience, not durability.

### Pruning

Manual. Delete entries when they're irrelevant. The file won't grow fast.

## Lifecycle summary

| Event | What happens |
|-------|-------------|
| workspace-init | Create orphan branch + worktree (idempotent) |
| Mid-session | Filesystem append to `.notes/NOTES.md` |
| Mid-slot | Append to original workspace's `.notes/NOTES.md` |
| Wrap (handover) | Commit accumulated notes to orphan branch |
| `work` (no issue) | Read and surface recent notes |
| After work-end | Read and surface recent notes |
| `/brief` | Include in orientation |
| Pruning | Manual — delete when irrelevant |
| Push | Optional — convenience, not durability |

## What this does NOT change

- HANDOFF.md — stays ephemeral, overwritten each session (**post-spec:** now branch-scoped)
- work-end — no changes to close sequence (NOTES.md not branch-scoped)
- slot_manager.py — no changes (slots access original workspace directly)

## Test plan

1. **workspace-init** creates `.notes/` worktree with orphan branch
2. **Append** adds entry with date header, commits to notes branch
3. **Read** at session start surfaces most recent section
4. **Multiple branches** — notes persist when workspace switches branches
5. **Worktree isolation** — `git branch` from main doesn't show `notes` in normal listing (it's orphan)
