---
layout: post
title: "The workspace leaves the branch"
date: 2026-11-27
entry_type: note
subtype: diary
projects: [hortora/soredium]
tags: [workspace, orphan-branch, notes-store, architecture]
series: fix/no-workspace-clones
---

The workspace model has been through three rewrites in a month. Each one fixed
the symptom in front of it and left the root cause untouched. This week I
finally named the root cause and built the first real fix.

## The problem nobody was solving

Every iteration of the workspace — companion repos, queue-root markers,
workspace isolation — shared one assumption: workspace state lives on the same
branch timeline as project code. Queue, plans, work notes, pipeline state — all
of it tracked a feature branch, got rebased with it, conflicted with it, and
had to be aligned with it.

But workspace state has a completely different lifecycle. It doesn't stack. It
doesn't rebase. It doesn't land. Putting it on a code branch was like storing
your notebook inside a shipping container — every time the container moves, the
notebook falls off the shelf.

## The design: an orphan branch

The fix is an orphan `notes` branch inside the project repo, checked out as a
`.notes/` worktree. Code lives on `main` and feature branches. Workspace state
lives on `notes`. They share a `.git` directory and nothing else.

For permanent clones (where I do most of my work), this means:

- The queue lives at `.notes/.queue` on the orphan branch
- `queue_io` already had `.notes/` routing — it just needed to be activated
- `topology.py` and `ctx.py` detect the `.notes/` worktree and report `WORKSPACE_OK=yes`
- No `wksp` symlink, no companion repo, no branch alignment

Slots will get a different treatment: the slot root becomes a coordination repo
with project clones gitignored. That's future work — the clone model landed
first because it's what I use daily.

## Three phases, one migration

I structured the implementation as three commits, each self-contained:

**Phase 1 — Discovery.** `notes_store.py` got queue directory management
(`ensure_queue_dir`, `list_queue_dirs`). `topology.py` grew a `notes_path`
field that detects `.notes/` as a worktree on the `notes` branch — not just
any directory. `ctx.py` now accepts the notes store as a valid workspace
indicator, so sessions opening from a migrated clone see `WORKSPACE_OK=yes`
without needing symlinks.

**Phase 2 — Pipeline.** `branch_create.py` and `resume_exec.py` skip workspace
operations when workspace and project resolve to the same path. Five functions
across two files, each guarded by `project.resolve() == workspace.resolve()`.
Before this, the pipeline created branches, checked out, rebased, and reset WIP
in both repos — harmless when they were the same repo (redundant no-ops), but
the explicit skip makes the single-repo path visible and testable.

**Phase 3 — Migration.** `clone_manager.py` now activates the notes store when
creating a clone, migrating the inherited queue into `.notes/.queue`.
`migrate_to_notes.py` handles existing clones: activate the notes store, copy
the queue, remove the `wksp` symlink, drop the `.queue-root` marker. It's
non-destructive — the original workspace clone stays on disk as a backup.

I ran the migration on this clone (soredium itself). The queue — 79 items,
7,431 bytes — moved cleanly. The old workspace clone (`wsp-soredium/`) is still
on disk but nothing reads it any more.

## What Claude caught

A separate Claude session implemented the three phases. I reviewed the work and
found one real gap: the Phase 2 `same_repo` guards had zero test coverage. The
existing tests all used separate project and workspace repos, so the new code
paths were exercised only by the real migration, never by pytest. I added nine
tests covering all five guard points — create-branches, sync-main, checkout,
rebase, and reset-wip — each with workspace equal to project.

The documentation was also stale. The lifecycle maintainer guide still called
the notes store "dormant" and CLAUDE.md described the old `wksp` symlink model.
Both now reflect the actual state: clones on `.notes/`, canonical repos and
slots pending migration.

## What this opens up

The queue is decoupled from code branching. That's the structural change, and
it has consequences:

- **No more alignment.** `alignment.py` checked that workspace and project were
  on the same branch. With the queue on an orphan branch, that check is dead
  code. One fewer thing to break during rebases.
- **Work notes instead of handoffs.** The spec describes `queue/<slug>/WORK-NOTES.md`
  — persistent living documents scoped to each work area. A handoff is a
  one-shot document written under time pressure. Work notes accumulate context
  that any session can read. This is next.
- **Slots as coordination repos.** The slot root becomes a git repo with project
  clones gitignored. Same idea, different topology. The spec covers it; the
  implementation is queued.

The workspace has been a source of bugs for months — branch mismatches,
contamination, stale handoffs, queue collisions. Each fix was local. This one
changes the structure so the class of bugs can't recur. The queue doesn't care
what branch the code is on, because it's not on any of them.
