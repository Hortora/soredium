---
layout: post
title: "The Pause Stack Problem"
date: 2026-07-30
type: phase-update
entry_type: note
subtype: diary
projects: [soredium]
tags: [git, slots, pause-resume, architecture]
series: issue-119-slot-clone-shared
---

The worktree-to-clone migration fixed the branch lock. But pausing from a slot opened a different gap: where does the pause stack entry go?

In the original model, `work-pause` writes to the workspace's `.pause-stack` on main, and `work-resume` reads from the same place. When the workspace IS a clone, there's no shared state — the clone has its own main branch, its own stack file, its own commit history. Pause from a slot, return to the original, and the stack is empty. The branch has vanished into the clone's local state.

The fix is a two-part redirect. First, pause detects clone context — if the workspace's origin remote points to a local directory, it's a clone. Resolve the original, and write the stack entry there. Second, the stack entry carries a `slot` field pointing back to the slot directory, so resume knows not to attempt checkout in the original repos. The branch doesn't exist there; it's in the clone. Resume shows the slot path and tells the user to open a session there.

The stack format change was minimal — one new field in serialization, one new line in list output. The pause logic was the interesting part. `_resolve_clone_origin` checks whether origin is a local path with a `.git` directory. `_resolve_slot_dir` walks the resolved path looking for a `worktrees` segment to find the slot root. Both are cheap and only fire when the origin is local — no performance hit for the common case.

One thing surfaced during testing that wasn't obvious beforehand: `pause_exec.py` calls `stack.py` via a hardcoded path to the installed copy at `~/.claude/skills/`. When testing changes to both scripts simultaneously, the tests pass the modified `pause_exec.py` but it calls the old installed `stack.py` — the slot field silently doesn't persist. The fix: prefer the repo-local copy when it exists, fall back to the installed copy otherwise.

The pattern from the previous session holds. Each layer of the slot system that gets fixed exposes the next assumption that doesn't hold in clone context. Worktrees to clone. Symlinks to resolve through git roots. Worklog paths to normalize. HANDOFF to per-project. Now: pause stack to write to original. The remaining item on #119 is work-end's per-repo evidence gate, but the core slot model — create, pause, resume, merge, archive — now handles clones end to end.
