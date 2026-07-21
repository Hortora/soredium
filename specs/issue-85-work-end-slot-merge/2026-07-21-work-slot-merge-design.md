# work-slot merge — Full Slot Lifecycle Management

**Issue:** Hortora/soredium#85
**Date:** 2026-07-21
**Status:** Design

## Problem

work-end Phase B (rebase onto main, push, close issues, promote artifacts)
can only be triggered by returning to the slot session and saying "merge".
A session running in the main repo has no way to discover or merge pending
slots. The slot session may no longer exist.

## Solution

Add `work-slot merge` as a user-facing command that runs from any repo in
the family (or the family root). It discovers ready-to-land slots, presents
them, and executes the full Phase B + archival sequence.

## Slot Lifecycle States

Four states, tracked by filesystem markers in the slot directory:

| State | Marker | Meaning |
|-------|--------|---------|
| `active` | slot dir exists, no `.phase-a-complete` | Work in progress |
| `ready to land` | `.phase-a-complete` exists | Phase A done, awaiting merge |
| `landed` | `.landed` exists | Phase B done, code on main, issues closed |
| `archived` | moved to `worktrees/attic/<N>/` | Worktrees removed, metadata preserved |

`landed` is transient — exists between Phase B completion and archival. Its
purpose is to prevent a slot from being offered for merge again if something
fails between push and archive.

`work-slot list` shows active + ready to land by default.
`work-slot list --all` includes archived (from `worktrees/attic/`).

## `work-slot merge` Flow

### Step 1 — Find family root

Walk up from CWD looking for a directory that is not itself a git repo and
contains child directories with `wksp` symlinks. Same logic as `work-slot
create` Step 2, with an additional guard: for each candidate, verify that
its child repos have `.git` directories (not files). Worktree checkouts
have `.git` files containing `gitdir:` pointers — if any child matches
this pattern, the candidate is a slot directory, not the family root. Skip
it and continue walking up. If the walk-up fails, ask the user.

### Step 2 — Scan and present

Call `slot_manager.py scan-ready <family-root>`.

The script returns JSON with per-slot data:
- Slot number, branch name, repos
- SLOT.md context ("What to do" section)
- Per-repo commit count and diff stats (from slot worktree branch vs origin/main)
- Phase A completion timestamp

The skill fetches issue titles via `gh issue view` and formats the rich listing:

```
Slots ready to merge:

  [1] issue-42-spi
      Repos: engine (3 commits, +142/-38)
      Issue: casehubio/engine#42 — "Add expression SPI"
      Context: Implement SPI for pluggable expression evaluation
      Phase A completed: 2026-07-18 14:32

  [2] issue-55-ledger
      Repos: engine (5 commits, +310/-94), iot (2 commits, +48/-12)
      Issue: casehubio/engine#55 — "Ledger event routing"
      Context: Route ledger events to IoT module via CloudEvent dispatch
      Phase A completed: 2026-07-19 09:15

Merge which slot? (number, or "all")
```

If no slots are ready to merge, report and stop.

### Step 3 — User picks

A slot number, or "all". If "all", slots are processed sequentially in
slot-number order.

### Step 4 — Pre-check

For every original repo involved across all selected slots:

1. Verify it has main checked out. If any repo is on a different branch,
   stop and report which repo is on the wrong branch.
2. Verify the working tree is clean (`git -C <repo> status --short` is
   empty). If any repo has uncommitted changes, stop and report.
3. Verify local main has no unpushed commits: `git -C <repo> log
   origin/main..main --oneline` must be empty. If any repo has unpushed
   commits, stop and report — unpushed local commits cause Stage 2's
   `merge --ff-only` to fail because the branch is rebased onto
   `origin/main`, not onto the diverged local main.
4. Fetch origin and check if remote is ahead of local: `git -C <repo> log
   main..origin/main --oneline`. If ahead, warn (non-blocking) — Stage 2
   handles the rebase.

### Step 5 — Sequential merge

For each selected slot, in order:

> **Phase B correspondence:** Steps 5a–5f implement the same operations as
> work-end Phase B (B1–B7) plus Step 9 (EPIC-CLOSED.md), invoked externally
> from the main repo. The shared scripts (`artifact_promote.py`,
> `blog_dest.py`, `branch_cleanup.py`) provide the single point of truth
> for each operation. If Phase B gains new steps, they must be reflected
> here — the correspondence is:
>
> | Step | Phase B / work-end | Operation |
> |------|--------------------|-----------|
> | 5a | B1 | Rebase branches onto current main |
> | 5b | B2 | Fast-forward and push |
> | 5c | B3–B5 | Close issues, promote artifacts, clean up specs, publish blog |
> | 5d | B6 | Stamp branches as closed |
> | 5e | Step 9 | Mark closed (EPIC-CLOSED.md) |
> | 5f | B7 | Cleanup / archive |
>
> Not carried over from B8: build verification (8k — slot has no build
> context), ARC42 stale scan (Step 11 — not critical for merge), HANDOFF.md
> (Step 12 — session-specific).

**5a. Rebase** — call `slot_manager.py merge-slot <family-root>
slot=<N>`. The script rebases all project repo branches onto current
`origin/main` in the slot worktrees. If any repo conflicts, the script
outputs `ERROR=conflict repo=<name>` and stops. No repos have been pushed.

**5b. Fast-forward and push** — if rebase passes, the same `merge-slot`
call continues: for each project repo in the original checkout, fetch
origin main, rebase origin/main, merge --ff-only the branch, push origin
main. Returns `LANDED_SHAS=<repo:sha,repo:sha>`. Writes `.landed` marker
with timestamp and SHAs.

If `merge --ff-only` or push fails (concurrent push advanced origin/main),
the script retries from Stage 1 — max 3 attempts. After 3 failures, output
`ERROR=retry_exhausted` and exit non-zero with manual instructions.

If push fails after some repos have already pushed (partial push), the
script writes a `.merge-progress` marker in the slot directory with
per-repo push status. On re-run, merge-slot reads `.merge-progress` and
skips already-pushed repos in Stage 2. See §merge-slot for details.

**5c. Post-merge actions** — the skill handles these (not the script).
Corresponds to Phase B steps B3–B5:
- Close issues: all in COVERS via `artifact_promote.py close-issues`
- Promote artifacts: from slot workspace worktree to the ORIGINAL workspace
  (which has main checked out) via `artifact_promote.py to-workspace-main`
- Clean up specs: via `artifact_promote.py cleanup-specs` in the slot
  workspace worktree (corresponds to Phase B deferred 8c)
- Publish blog: via `blog_dest.py` targeting the ORIGINAL workspace

**5d. Stamp branches** — empty commits on branches in the slot worktrees.
Stamp BOTH project repo branches and ALL workspace worktree branches
(corresponds to Phase B step B6).

Workspace worktree names are NOT fixed — `resolve_workspace_source()`
returns `"work"` (shared workspace) or `"work-{name}"` (external
workspace), and a slot can have multiple. Discover workspace worktrees
dynamically: scan the slot directory for directories whose name starts
with `work` and contain a `.git` file.

```bash
# Project repos
git -C <slot>/<repo> commit --allow-empty -m "chore: branch closed — landed as <SHA> on main"
# ALL workspace worktrees (work, work-iot, work-pages, etc.)
for each <ws-dir> in <slot>/work* where <ws-dir>/.git exists:
  git -C <ws-dir> commit --allow-empty -m "chore: branch closed — landed as <SHA> on main"
```

**5e. Mark closed** — commit `design/EPIC-CLOSED.md` on the workspace
branch in the primary workspace worktree (the first `work*` directory in
the slot). This is the canonical marker that the hygiene scan (work-end
8i) uses to classify branches — without it, merged branches are flagged as
stale after 7 days, and unrecovered-artifact and unstamped-branch checks
are silently skipped.

```bash
python3 ~/.claude/skills/work-end/branch_cleanup.py create-epic-closed \
  <slot>/<primary-workspace> branch=<BRANCH_NAME> \
  date=$(date +%Y-%m-%d) issues=<COVERS> single-repo=no
```

The workspace worktree is already on the branch (created with
`git worktree add -b`), so `single-repo=no` is correct — no branch
checkout needed.

This must run BEFORE archive (5f) because archive removes the worktrees.

**5f. Archive** — call `slot_manager.py archive-slot <family-root>
slot=<N>`. The script runs `git worktree remove` for each repo and
workspace worktree, then moves `worktrees/<N>/` to `worktrees/attic/<N>/`.
SLOT.md, `.phase-a-complete`, `.landed`, and other metadata survive in
the attic.

If archive-slot fails (e.g., a process holds a file lock in the worktree),
report the error but do NOT roll back the merge — the code is already on
main. The slot stays in `landed` state. Report the manual cleanup command:
`git worktree remove --force <path>` followed by
`mv worktrees/<N> worktrees/attic/<N>`.

If "all" was selected and slot N fails at 5a (conflict), slots N+1 onward
are not attempted. Slots before N are already landed and archived (5f). This is
intentional: each slot rebases against the current main, which advances
after each successful merge. Slot N+1's rebase target depends on slot N's
outcome — continuing would require rebasing against either the pre-slot-N
main (stale) or the expected post-slot-N main (unknown, since slot N
didn't merge).

## Script Changes: `slot_manager.py`

**Slot number allocation fix:** `allocate_slot_number()` must scan both
`worktrees/*/` and `worktrees/attic/*/` when computing the next number.
Without this, archiving all active slots resets the counter to 1, and
archiving a new slot 1 overwrites the original slot 1's metadata in the
attic.

Three new subcommands:

### `scan-ready <family-root>`

Scans `worktrees/*/` for directories with `.phase-a-complete` (and no
`.landed`). For each slot, reads SLOT.md for branch name, repos, issue
info, and context. Runs `git log --oneline` and `git diff --shortstat`
in each repo's slot worktree to get commit count and diff stats. Reads
Phase A timestamp from `.phase-a-complete`.

Returns JSON:
```json
{
  "slots": [
    {
      "number": 1,
      "branch": "issue-42-spi",
      "repos": [
        {"name": "engine", "commits": 3, "diff": "+142/-38"}
      ],
      "issue": "42",
      "issue_repo": "casehubio/engine",
      "covers": "42",
      "context": "Implement SPI for pluggable expression evaluation",
      "phase_a_timestamp": "2026-07-18T14:32:00"
    }
  ]
}
```

### `merge-slot <family-root> slot=<N>`

Executes in two stages with progress output. Retry loop wraps both stages
— max 3 attempts total.

Only project repos are processed (workspace worktrees are excluded — filter
as `not name.startswith("work")` and `name != ".m2"`, matching the
`list_slots()` filter).

**Stage 1 — Rebase.** For each project repo in the slot:
```bash
git -C <slot>/<repo> fetch origin main
git -C <slot>/<repo> rebase origin/main
```
If any rebase fails: abort that rebase, output `ERROR=conflict
repo=<name>`, exit non-zero. No push has happened.

Output: `STAGE=rebase STATUS=pass` or `STAGE=rebase STATUS=fail`

**Stage 2 — Fast-forward and push.** For each project repo (in original
checkout):
```bash
git -C <original>/<repo> fetch origin main
git -C <original>/<repo> rebase origin/main
git -C <original>/<repo> merge --ff-only <branch>
git -C <original>/<repo> push origin main
```

As each repo pushes successfully, append to `.merge-progress` in the slot
directory: `<repo>=pushed:<sha>`. This enables partial push recovery.

If `merge --ff-only` or `push` fails: retry from Stage 1 (re-rebase all
repos, re-attempt push for unpushed repos). Max 3 attempts total. After 3
failures: output `ERROR=retry_exhausted repo=<name>`, exit non-zero.

**Partial push recovery.** On re-run (or retry), if `.merge-progress`
exists, read it and skip Stage 2 push for repos already listed as
`pushed`. Stage 1 re-rebases all repos (safe — git detects
already-applied patches by patch-id and skips them). This handles the case
where repo A pushed but repo B failed, leaving the family in an
inconsistent state.

On full success: remove `.merge-progress`, write `.landed` marker:
```
branch=<BRANCH_NAME>
repos=<comma-separated>
landed_shas=<repo:sha,repo:sha>
timestamp=<ISO-8601>
```

Output: `STAGE=push STATUS=pass LANDED_SHAS=engine:<sha>,iot:<sha>`

The script resolves original repo paths by reading the git worktree's
commondir (the original repo that owns the worktree).

### `archive-slot <family-root> slot=<N>`

1. For each repo and workspace worktree in the slot:
   `git worktree remove --force <path>`
2. Move `worktrees/<N>/` to `worktrees/attic/<N>/`
3. Output `ARCHIVED=<N>`

The attic directory preserves SLOT.md, `.phase-a-complete`, `.landed`,
and any other metadata files for auditing.

## Skill Changes: `work-slot/SKILL.md`

Add a `## work-slot merge` section after the existing `work-slot remove`
section. The skill orchestrates the flow described above, calling
`slot_manager.py` subcommands and handling GitHub API calls and cross-skill
invocations.

## Changes to `work-slot list`

Update `list_slots()` to:
- Show the lifecycle state using all markers (active / ready to land /
  landed)
- Accept a `--all` flag that also scans `worktrees/attic/` for archived
  slots. For archived slots, read repo information from SLOT.md (the
  `## Repos` section), not from `.git` files — after `git worktree
  remove`, the `.git` files in attic repo directories point to dead
  worktree gitdirs and are unreliable.
- Include per-repo commit count and diff stats for active and ready-to-land
  slots (not for archived — worktrees no longer exist)

## Files Changed

| File | Change |
|------|--------|
| `work-slot/slot_manager.py` | Add `scan-ready`, `merge-slot`, `archive-slot` subcommands. Update `list_slots` for new states and `--all`. |
| `work-slot/SKILL.md` | Add `work-slot merge` section. Update lifecycle state documentation. |
| `work-end/SKILL.md` | No changes — Phase A/B logic stays as-is. The existing Phase B path (from inside the slot) continues to work. |

## What This Does NOT Change

- **Phase A** — still runs inside the slot via work-end, unchanged.
- **Phase B from inside the slot** — still works. If the user returns to
  the slot session and says "merge", work-end detects `.phase-a-complete`
  and runs Phase B as before.
- **work-end** — no modifications. `work-slot merge` is a parallel entry
  point to the same post-Phase-A operations.
- **`work-slot create`** — unchanged.
- **`work-slot remove`** — unchanged (force-deletes without merge).

## Testing

### Core flow
- Create a multi-repo slot, run Phase A, verify `scan-ready` returns
  correct data
- `merge-slot` with clean rebase — verify ff-only merge and push succeed
- `merge-slot` with conflict — verify error output and no push
- `archive-slot` — verify worktrees removed, slot dir in attic with
  metadata preserved
- "all" with 2 slots — verify sequential processing, second slot rebases
  against updated main
- "all" with conflict on slot 2 — verify slot 1 is landed/archived, slot 2
  stops cleanly

### Pre-check
- Pre-check failure — verify error when original repo not on main
- Pre-check with uncommitted changes — verify error reports dirty repo
- Pre-check with unpushed commits on local main — verify error reports
  diverged repo

### Failure modes and recovery
- Slot number allocation with existing attic entries — verify new slot
  number is max of active + archived + 1
- Partial push failure (repo A pushed, repo B failed) — verify
  `.merge-progress` written, re-run skips repo A and retries repo B
- Retry on ff-only failure — verify Stage 1 re-rebase + Stage 2 retry
  succeeds when concurrent push caused the initial failure
- Archive failure after merge success — verify slot stays `landed`, error
  reported, manual instructions provided

### Family root detection
- Family root detection from within a slot worktree CWD — verify the slot
  directory is rejected (`.git` file guard) and the real family root is
  found

### Workspace worktree handling
- Workspace worktrees excluded from merge-slot rebase/push
- Artifact promotion targets the original workspace, not the slot workspace
- Branch stamping discovers all workspace worktrees dynamically (work,
  work-iot, etc.), not just hardcoded "work"
- Spec cleanup runs during Step 5c post-merge actions

### Lifecycle markers
- EPIC-CLOSED.md created on workspace branch before archive (Step 5e)
- Subsequent work-end hygiene scan does NOT flag the merged branch as stale
- Unrecovered artifact and unstamped branch checks work on the merged branch

### Listing
- `list-slots --all` — verify archived slots appear with repo info from
  SLOT.md (not from dead `.git` files)
