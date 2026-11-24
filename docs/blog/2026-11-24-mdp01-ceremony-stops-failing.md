---
layout: post
title: "Why work end kept failing twice"
date: 2026-11-24
entry_type: note
subtype: diary
projects: [Hortora/soredium]
tags: [lifecycle, pipeline, ceremony, alignment]
series: issue-599-work-end-step-promotion
---

# Why work end kept failing twice

The worklog told the story before we did. Twenty-eight failed ceremonies against fourteen successful ones. Almost every `work end` stopped at `land` for unpromoted artifacts, got retried, stopped again for an unreviewed squash, and got retried a second time. Each retry cost a model turn. Worse: before the resume fix landed, each retry re-asked "is the item finished?" — and answering `yes` a second time marked the *next* item done, one that hadn't been started.

The root cause was structural. `close()` checked for unpromoted artifacts and stale squash reviews inside the same function that lands branches. The pipeline had no way to fix one problem without re-running the whole ceremony. When it hit the first check, it failed. The session fixed it and retried. The second check failed. Another retry. The landing itself almost never failed — the prerequisites were the problem, and they were tangled into the wrong layer.

## Pulling the checks out

The fix was to make each prerequisite its own pipeline step. The end sequence now runs `promote → squash_review → land` instead of `land` alone. Each step is mechanical: it checks one thing, fails with an actionable error if that thing isn't done, and the pipeline stops there. The session fixes it and retries — resume picks up at the failed step, not from the beginning.

The interesting wrinkle was `covers`. After `mark_done` runs, the queue advances: `queue.state.covers` now names the next item, not the one being landed. The old code inside `close()` used `covers` for the promote check, which worked because `close()` ran before `mark_done`. The new steps run after `mark_done`, so they can't use `queue.state.covers`. We had to use `done_items()` and `batch_entries()` instead — the done item's ref and branch are stored on the item itself, not in the queue state.

The same subtlety hit the preflight. `sequence_preflight` now scans for blockers before the first judgment step and prints `PREFLIGHT_WARN=` with everything that will block landing. But the preflight runs *before* `mark_done` too, so it correctly uses `resolve()` with the active branch. The asymmetry is important: preflight checks the active branch, the steps check the done branches, and both are right for where they sit in the pipeline.

## The double-mark-done bug

The `item_finished` guard was the smallest change but prevents the most damage. When a retry re-enters the pipeline, the progress file already has the answer. A `skip_fn` on the step checks for it: if the answer is recorded, the step is skipped and `ITEM_FINISHED_REUSED=yes` is printed. The pipeline never re-asks.

Without this, a retry after a failed `land` would re-present "is the item finished?" The LLM would answer `yes` again. `mark_done` would run again — but by now the queue has advanced, and it marks the *next* item done. An item that was never worked on gets recorded as finished.

## A stale branch that caused a loop

A separate issue surfaced during the session: a workspace on a stale branch from prior work while the project was on main. The alignment module classified this as `project_behind` — workspace ahead of project — but it wasn't repairable. The pipeline gave a decision the LLM couldn't act on and looped.

The fix: `project_behind` is now repairable when the workspace branch is stale (not in the queue). The alignment repair checks the workspace out to main and prints what it did. If the queue *does* name that branch as active work — a possible interrupted start — it stays a decision. The gate is the queue: stale branches are repaired, active branches are presented.
