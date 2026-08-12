---
layout: post
title: "The Worktree Trap"
date: 2026-07-30
type: phase-update
entry_type: note
subtype: diary
projects: [soredium]
tags: [git, worktrees, slots, architecture]
series: issue-119-slot-clone-shared
---

Every slot operation that touched workspace main — handover, pause, work-end — was silently failing. The root cause was a fundamental property of git worktrees I hadn't thought through: two worktrees of the same repo cannot have the same branch checked out. The slot's workspace worktree couldn't `git checkout main` because the original repo already had main checked out.

The symptom was diffuse. Handover commits failed. Pause crashed. Work-end Phase B, when run inline from a slot, couldn't switch to main. Each failure was individually fixable with a behavioural patch — detect slot context, skip the checkout. But the patches were accumulating, and each one created a new edge case.

I traced the full combinatorial space: every lifecycle operation against every mode (adhoc, work-start, work-slot) against every configuration (single-repo, multi-repo, single-repo slot, multi-repo slot). The matrix made the problem clear — it wasn't one bug, it was a class of bugs. Any operation that needed workspace main would break in any slot configuration.

The fix came from an unexpected direction. `git clone --shared` creates a completely independent repo that reads objects directly from the original via alternates — zero disk overhead, full history, but with its own branch namespace. `checkout main` works because there's no shared ref database. It gives you everything worktrees give you, minus the constraint that makes them unusable for lifecycle operations.

We replaced `git worktree add` with `git clone --shared` for all repos in a slot — project and workspace alike. Origin stays pointed at the local original, so `push` and `pull` flow naturally. Existing worktree-based slots auto-migrate on first access: clone to temp, verify tree hash matches, atomic swap.

Fixing the slot model exposed two more silent failures hiding underneath. The worklog — which should track every lifecycle event — had recorded zero close events since deployment. macOS resolves `/tmp` to `/private/tmp` via symlink, and the path lookup used exact string matching. Every `record_work_end` call silently failed because the path at close time didn't match the path at start time. `Path.resolve()` at the storage boundary fixed it.

The second was in ctx.py's workspace resolution. `Path.exists()` returns False for symlinks whose target doesn't exist — even when `Path.is_symlink()` returns True. Engine's `wksp` symlink pointed to `../work/engine`, but the workspace git root was at `work/`, not `work/engine/`. ctx.py fell through to single-repo mode, making the entire workspace invisible. The fix walks up from the broken target to find the nearest git root.

Fixing THAT exposed a third problem. The workspace was now found correctly, but the HANDOFF.md on it was from eidos work — the last project to write to the shared workspace. A shared workspace serves multiple projects, but `HANDOFF.md` is a single file. Whoever writes last wins; everyone else finds someone else's handover. The fix: per-project HANDOFF files. The router checks `HANDOFF-{project_name}.md` first, falls back to `HANDOFF.md` for backward compatibility. Each project's handover is isolated without changing the workspace structure.

Four layers of silent failure, each hidden by the one above. The worktree branch lock hid the workspace resolution bug. The workspace resolution bug hid the worklog path mismatch. The workspace resolution fix surfaced the HANDOFF scoping problem. Each fix was the same shape: check more carefully at the boundary, normalize before comparing, scope to the right level.
