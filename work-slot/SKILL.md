---
name: work-slot
description: >
  Use when creating parallel worktree slots for multi-repo family work —
  user says "create a slot", "spin up a worktree for issue #N", "parallel
  work on engine and iot", or invokes /work-slot. Also use "work-slot list"
  to see slot status, "work-slot remove" to archive abandoned slots, and
  "work-slot merge" to land ready slots from the main repo.
  NOT for single-repo worktree isolation (use using-git-worktrees for that).
slash-command: true
---

# work-slot

Create and manage numbered worktree slots for parallel development across
a multi-repo family. Each slot is a self-contained work environment with
isolated `.m2`, re-pointed symlinks, and a context file for the session
that works there.

## Slot Lifecycle

| State | Marker | Meaning |
|-------|--------|---------|
| `active` | slot dir exists, no markers | Work in progress |
| `ready to land` | `.phase-a-complete` | Phase A done, awaiting merge |
| `landed` | `.landed` | Merged to main, awaiting archive |
| `archived` | in `worktrees/attic/<N>/` | Worktrees removed, metadata kept |

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

> "Archive slot <N>? Git worktrees will be removed but SLOT.md and
> markers are preserved in `worktrees/attic/<N>/`. (y/n)"

Wait for confirmation. Then:

```bash
python3 ~/.claude/skills/work-slot/slot_manager.py remove-slot <family-root> slot=<N>
```

**Default behaviour is archive to attic, not delete.** The slot directory
moves to `worktrees/attic/<N>/` preserving SLOT.md, `.phase-a-complete`,
`.landed`, and any other metadata for auditing and branch hygiene.

**Never pass `--force-delete`** unless the user explicitly says "permanently
delete" or "destroy". Archived slots cost nothing and enable branch hygiene
scans, blog recovery, and stamp verification.

---

## `work-slot merge`

Merge ready-to-land slots from the main repo. Runs the full Phase B
sequence: rebase, push, close issues, promote artifacts, stamp, archive.

### Step 1 — Find family root

Walk up from CWD looking for a directory that is not itself a git repo
and contains child directories with `wksp` symlinks. For each candidate,
verify its child repos have `.git` directories (not files) — worktree
checkouts have `.git` files and must be skipped.

If the walk-up fails, ask:
> "Which directory is the family root? (e.g., ~/claude/casehub)"

### Step 2 — Scan and present

```bash
python3 ~/.claude/skills/work-slot/slot_manager.py scan-ready <family-root>
```

Parse the JSON output. For each slot, fetch the issue title:
```bash
gh issue view <issue-number> --repo <issue-repo> --json title --jq '.title'
```

Present the rich listing:
```
Slots ready to merge:

  [1] issue-42-spi
      Repos: engine (3 commits, +142/-38)
      Issue: casehubio/engine#42 — "Add expression SPI"
      Context: Implement SPI for pluggable expression evaluation
      Phase A completed: 2026-07-18 14:32

Merge which slot? (number, or "all")
```

If no slots are ready: "No slots ready to merge." Stop.

### Step 3 — Pre-check

For every original repo across all selected slots, verify:
1. Main checked out
2. Clean working tree (`git -C <repo> status --short` is empty)
3. No unpushed commits (`git -C <repo> log origin/main..main --oneline`
   is empty)
4. Fetch origin — warn if remote is ahead (non-blocking)

If any check fails, stop and report which repo failed and why.

### Step 4 — Merge each slot

For each selected slot, in order:

**4a. Rebase and push:**
```bash
python3 ~/.claude/skills/work-slot/slot_manager.py merge-slot <family-root> slot=<N>
```

Read output. If `ERROR=conflict`: stop, report which repo conflicted.
If `ERROR=retry_exhausted`: stop, provide manual instructions.
If `STAGE=push STATUS=pass`: continue to 4b.

**4b. Post-merge actions** (skill handles these):
- Close issues:
  ```bash
  python3 ~/.claude/skills/work-end/artifact_promote.py close-issues <issue-repo> covers=<covers>
  ```
- Promote artifacts from slot workspace to original workspace:
  ```bash
  python3 ~/.claude/skills/work-end/artifact_promote.py to-workspace-main <original-workspace> branch=<branch> artifacts=<paths>
  ```
- Clean up specs in slot workspace:
  ```bash
  python3 ~/.claude/skills/work-end/artifact_promote.py cleanup-specs <slot-workspace> branch=<branch>
  ```
- Publish blog:
  ```bash
  python3 ~/.claude/skills/work-end/blog_dest.py <original-workspace>/blog <branch>
  ```

**4c. Stamp branches** — handled programmatically by `merge_slot()`.
`merge_slot()` writes stamp commits on all repo and workspace worktrees
after confirming all pushes succeeded. Do NOT write stamps manually.

**4d. Mark closed:**
```bash
python3 ~/.claude/skills/work-end/branch_cleanup.py create-epic-closed \
  <slot>/<primary-workspace> branch=<branch> date=$(date +%Y-%m-%d) \
  issues=<covers> single-repo=no
```

**4e. Archive:**
```bash
python3 ~/.claude/skills/work-slot/slot_manager.py archive-slot <family-root> slot=<N>
```

If archive fails: report error but do NOT roll back — code is on main.
Report manual cleanup commands.

### Step 5 — Report

```
✅ Slot <N> merged and archived
   Branch: <branch>
   Repos: <list>
   Issues closed: #<covers>
   Artifacts promoted: <count>
```

If "all" was selected, repeat Step 4 for next slot. If any slot fails at
4a, stop — report which slot failed and that prior slots landed.

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
- **Does not delete slots** — all cleanup paths archive to
  `worktrees/attic/<N>/`. Deletion requires explicit `--force-delete`
  from the user. An archived slot costs nothing; a deleted slot loses
  branch hygiene data, blog entries, and audit trail permanently.

---

## Skill Chaining

**Invoked by:** Human directly (`/work-slot`, "create a slot for...",
"spin up a worktree", "parallel work on...")

**Invokes:** Nothing — creates the environment; the human starts work.

**Complements:**
- `work-start` — runs inside the slot after creation (resume path)
- `work-end` — Phase A writes `.phase-a-complete`; work-slot merge reads
  it and runs Phase B externally. Phase B from inside the slot still works.
- `using-git-worktrees` — same git primitive, different use case
  (single-repo ephemeral isolation for subagent dispatch)
- `handover` — HANDOFF.md for session handoffs (SLOT.md is slot context,
  distinct from session handoff)
- `issue-workflow` — activate-issues called during slot creation
- `artifact_promote.py` / `blog_dest.py` / `branch_cleanup.py` — shared
  scripts used by both work-end Phase B and work-slot merge
