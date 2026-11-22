---
layout: post
title: "The Ceremony That Lied"
date: 2026-11-22
entry_type: note
subtype: diary
projects: [soredium]
tags: [lifecycle, testing, landing, context-budget, work-end]
series: lifecycle-hardening
---

Three issues in one session, all circling the same problem: the lifecycle tells you things are fine when they aren't.

## Tests that bypass the code they're testing

The wrap and end tests (`test_work_wrap_end.py`) have been passing for months. Every call hands `workspace=`, `project=`, `branch=`, `covers=`, `plan_path=` to `work.py` as explicit arguments. This means `fill_from_context()` sees `workspace` in the args and skips `ctx.resolve()` entirely — the topology resolver, the queue reader, the workspace validator, all of it. The tests exercise the pipeline. They never exercise the path a real session takes.

The first live `work end` found two defects. Both came from values that changed mid-run after `mark_done` activated the next item. The retry restarted from the review instead of resuming at the failed step, and the promote command carried the next item's reference instead of the done one's. Those bugs were fixed, but no test covered the resolution path that surfaced them.

Ten new tests now call `work.py` with no context arguments, from inside the workspace, the way a session does. Three layouts: plain dual workspace, permanent clone with root queue, numbered slot. Each includes a failed-landing-then-retry path. The clone fixture needed its inherited symlinks committed before branching — the existing tests hid this because they passed explicit args and never hit the dirty-worktree preflight.

## The landing that said LANDED but moved nothing

A casehub-mosaic slot completed its ceremony with `success=True` and a `LANDED=` line naming the closed items. Canonical main hadn't moved. The feature commits existed in the repo — just not on main. `scope.py land` then said `LANDED=nothing` because the queue items were already marked closed. `canonical_sync.py publish` pushed 0 commits because main hadn't advanced.

The gap: `land_all()` records the canonical base SHA *after* landing but never recorded it *before*. When `_prepare()` decides a branch is "already landed" (its tip is an ancestor of main), the entire hold-advance-release sequence is skipped. The result carries the current main SHA as `result.sha`, stamps the branch, closes the queue item, and returns `success=True`. Nobody checked whether main actually moved.

`LandResult` now carries `before_sha`. Four tests pin the invariant: landing a branch with commits always changes the canonical base SHA. The `already_landed` case gets an explicit verification that the branch tip is genuinely on main — belt and suspenders over `verify_content_landed`, which checks the same thing from a different angle but was clearly not enough in practice.

## The recommendation the LLM had to guess

After finishing an item, the pipeline prints `OFFER=wrap_or_continue`. The work skill tells the LLM to present a recommendation based on context usage, next task scale, and topic relevance. But the pipeline supplied none of that data. The LLM estimated context usage by counting issues (unreliable after compression), guessed at the next item's scale from memory, and made a recommendation that was really just a heuristic guess wearing confidence.

Queue items now carry scale and complexity — `(S/Med)` after the title, populated from GitHub issue labels when items are appended, updateable via `plan_manager.py set-scale`. The pipeline prints `NEXT_ITEM=`, `NEXT_SCALE=`, `NEXT_COMPLEXITY=`, and `DONE_WAITING=` alongside `OFFER=wrap_or_continue`. The work skill's recommendation table is now three-way: continue, end-then-continue (land finished items but keep working), or wrap/end and stop. The LLM still makes the call, but it has the data instead of guessing at it.

A new mid-task monitoring section tells the LLM to watch for context exhaustion during long items and suggest `work wrap` before it's too late — not after. No hard threshold; it's a judgment call based on how much of the item remains versus how much context is left.

## The pattern

All three share the same failure mode: a system that reports success without verifying it. Tests that pass without testing the real path. A ceremony that says "landed" without checking main moved. A recommendation that sounds authoritative without having the data. Each fix is small — a `before_sha` field, a `cwd=` parameter, a few KEY=VALUE lines — but each closes a loop that was silently open.
