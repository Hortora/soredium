---
layout: post
title: "Stop Pushing Work End on Cold Sessions"
date: 2026-11-23
entry_type: note
subtype: diary
projects: [Hortora/soredium]
tags: [lifecycle, ux, pipeline, clone-guard]
---

# Stop Pushing Work End on Cold Sessions

The work pipeline had a habit of nudging new sessions toward `work end`. You'd open a fresh session, type `work continue`, and instead of carrying on it would present the wrap-or-continue decision — pushing you toward landing, diary entries, and closing ceremonies that need context from the session that did the actual work.

The root cause was a single line in `work_route.py`: `offer = bool(done)`. If any done-but-not-closed items existed in the queue, every route — `continue`, `start`, `resume`, everything — set `offer=True`. That triggered the wrap-vs-continue decision gate in the work skill, and the LLM dutifully presented "End then continue" and "End and stop" options. A fresh session has no review context, no diary material, no memory of what was tried and rejected. Work end without that context produces hollow ceremonies.

The fix is straightforward: `OFFER=wrap_or_continue` now fires only after `work done` — the moment when the user has just finished an item and the question of what comes next is genuinely relevant. For `continue` and `start`, done items appear as an informational `DONE_WAITING=N` line. The LLM can mention them, but it's not gated into a decision about landing.

There was a second path that made it worse. When only done items remained in the queue and no open item existed, the router returned `stop="end"` with `reason="done_items_await_close"`. This hard-stopped the pipeline and said "run work end." No choice, no alternatives. That's now `stop="nothing"` with `reason="done_items_informational"` — the user knows items are waiting and runs `work end` when they're ready, in a session that has the context to do it properly.

## The clone guard, while we were in there

The same branch converted the clone guard from a blunt stop to a decision flow. When you ran a work command in a canonical repo of a clone-enabled family, the guard used to emit `ACTION=stop` with a command string to copy-paste. Now it emits `ACTION=decision` with `DECISION=clone_guard` and options — open the existing clone, create one, or stop. The handler file follows the same pattern as `move-on-gate.md`: present options, recommend one, call back with the choice.

The clone guard change is mechanical — it follows an existing pattern. The routing change is the one that matters. A lifecycle tool that nags you into ceremonies you can't do properly is worse than one that says nothing at all.
