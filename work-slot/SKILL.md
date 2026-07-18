---
name: work-slot
description: >
  Use when creating parallel worktree slots for multi-repo family work —
  user says "create a slot", "spin up a worktree for issue #N", "parallel
  work on engine and iot", or invokes /work-slot. Also use "work-slot list"
  to see slot status and "work-slot remove" to clean up abandoned slots.
  NOT for single-repo worktree isolation (use using-git-worktrees for that).
slash-command: true
---

# work-slot

Create and manage numbered worktree slots for parallel development across
a multi-repo family. Each slot is a self-contained work environment with
isolated `.m2`, re-pointed symlinks, and a context file for the session
that works there.

---

## `work-slot create`

### Step 1 — Gather input

Ask the user for:
- **Repos:** which repos in the family to include (e.g., "engine", "engine and iot")
- **Issue:** the issue number and repo (e.g., `#42` on `casehubio/engine`)
- **Context:** what needs doing and any background (constraints, relevant files, design decisions)

The user may provide all of this in one sentence or you may need to ask.

### Step 2 — Find family root

Walk up from CWD looking for a directory that is not itself a git repo
and contains child directories with `wksp` symlinks. Or accept an
explicit path from the user.

```bash
# The family root is NOT a git repo but contains git repos with wksp symlinks
```

If the family root cannot be determined, ask:
> "Which directory is the family root? (e.g., ~/claude/casehub)"

### Step 3 — Derive branch name

`issue-<N>-<slug>` from the primary issue, same convention as work-start
Step 5. Show to the user, allow override.

### Step 4 — Create the slot

```bash
python3 ~/.claude/skills/work-slot/slot_manager.py create-slot <family-root> \
  repos=<csv> branch=<branch-name> issue=<N> issue-repo=<owner/repo> \
  covers=<csv> context=<text>
```

Read output: `SLOT_NUMBER`, `SLOT_DIR`, `BRANCH`. If `ERROR=`, report
and stop.

### Step 5 — Activate issues on project board

If the project has `GitHub project:` configured in CLAUDE.md (read via
ctx.py `GITHUB_PROJECT`), activate issues on the project board:

```bash
python3 ~/.claude/skills/issue-workflow/issue_setup.py activate-issues \
  <issue-repo> issues=<covers> project=<github-project-number>
```

Non-fatal — warn and continue on failure.

### Step 6 — Offer iTerm2 tab

> "Open an iTerm2 tab in the slot? (y/n)"

If yes:
```bash
osascript -e 'tell application "iTerm2"
    tell current window
        create tab with default profile
        tell current session
            write text "cd <slot-dir>/<primary-repo>"
        end tell
    end tell
end tell'
```

Warn and continue if iTerm2 is unavailable.

### Step 7 — Report

```
Slot <N> created: <branch-name>
  Repos: engine, iot
  Workspace: work (shared) / work-iot (external)
  .m2: worktrees/<N>/.m2
  Slot context: worktrees/<N>/SLOT.md
  iTerm2: tab opened / skipped

Open a CLI in <slot-dir>/<primary-repo> and run work-start.
work-start will detect the existing scaffold and run the resume path.
```

---

## `work-slot list`

```bash
python3 ~/.claude/skills/work-slot/slot_manager.py list-slots <family-root>
```

Format output as a table:

| Slot | Branch | Repos | State |
|------|--------|-------|-------|
| 1 | issue-42-spi | engine | active |
| 2 | issue-55-ledger | engine, iot | ready to land |

---

## `work-slot remove <N>`

> "Remove slot <N>? This will delete the worktrees and all local changes. (y/n)"

Wait for confirmation. Then:

```bash
python3 ~/.claude/skills/work-slot/slot_manager.py remove-slot <family-root> slot=<N>
```

---

## How slots work

- **Self-contained.** Everything under `worktrees/<N>/` — repo worktrees,
  workspace worktree, isolated `.m2`, SLOT.md context file.
- **Isolated .m2.** Every slot gets its own Maven local repo via
  `.mvn/maven.config`. No cross-contamination with the originals.
- **Symlinks re-pointed.** `wksp`/`proj` symlinks point to the slot's
  workspace, not the originals. ctx.py follows them transparently.
- **Scaffold pre-created.** `.meta` and `JOURNAL.md` exist in the slot.
  work-start detects state 2 (scaffold exists) and runs the resume path.

### What happens in the slot

1. Human opens a CLI session in `worktrees/<N>/<primary-repo>`
2. Runs work-start — detects existing scaffold, runs resume path
3. Does the work (implementation, tests, etc.)
4. Runs work-end — detects slot mode, runs Phase A (review, verify,
   squash, push branch), stops before merge. Desktop notification.
5. Human returns later, says "merge" — work-end Phase B runs (rebase,
   push main, close issues, promote artifacts, cleanup slot)

### What it doesn't do

- Does not run work-start — the human does that in the new session
- Does not merge to main — work-end Phase B handles that
- Does not coordinate between slots — the human sequences merges

---

## Skill Chaining

**Invoked by:** Human directly (`/work-slot`, "create a slot for...",
"spin up a worktree", "parallel work on...")

**Invokes:** Nothing — creates the environment; the human starts work.

**Complements:**
- `work-start` — runs inside the slot after creation (resume path)
- `work-end` — handles Phase A/B in slot context
- `using-git-worktrees` — same git primitive, different use case
  (single-repo ephemeral isolation for subagent dispatch)
- `handover` — HANDOFF.md for session handoffs (SLOT.md is slot context,
  distinct from session handoff)
- `issue-workflow` — activate-issues called during slot creation
