---
layout: post
title: "One Slot, One Epic, Many Sessions"
date: 2026-07-28
type: phase-update
entry_type: note
subtype: diary
projects: [soredium]
tags: [work-lifecycle, slots, epic-management]
---

The work-slot system has handled parallel multi-repo development well — spin up a slot, do the work, merge it back. But each slot has always mapped to a single issue. When an epic has ten child issues, the orchestration falls on the human: decide what's next, create a slot, track which issues are done, remember where you left off after clearing the session. That friction compounds across sessions until you're spending more time managing the work than doing it.

I wanted a single slot that could drive through an entire epic — one branch, multiple sessions, with the tooling tracking where you are.

## Batch Planning

The first design question was granularity. Not every issue should be its own iteration — some are tightly related and should land together. I'd been doing this manually in another project, grouping issues into batches:

```
┌────────┬──────────────┬─────────┬──────────────────────────────┐
│ Batch  │    Issues    │  Scale  │         Why together         │
├────────┼──────────────┼─────────┼──────────────────────────────┤
│ 1      │ #108, #109   │ S+S     │ Vocabulary — no API change   │
│ 2      │ #111, #112   │ M+M     │ Weighted profiles — the API  │
│ 3      │ #116         │ M       │ Depends on #111              │
└────────┴──────────────┴─────────┴──────────────────────────────┘
```

Issues grouped by domain affinity and dependency ordering. The batch plan lives in the epic's Scope section on GitHub and in SLOT.md locally. GitHub is the durable source of truth — checkboxes get ticked as issues complete, visible to anyone tracking the epic.

The batch planning itself is an LLM decision — it reads the child issues, their labels, descriptions, and dependency mentions, then proposes groupings. A one-shot judgment call. The approved plan is committed and becomes authoritative; re-running might produce a different grouping, and that's fine because you'd only re-run after a safe exit when circumstances have changed.

## The State Problem

The harder problem was cross-session continuity. After a `/clear`, the LLM has no memory of where you were. SLOT.md became the answer — extended with `## Batch Plan` and `## Session State` sections that record exactly which batch is current, which issue is active, and what's been completed. When you resume, the LLM reads one file and knows everything.

SLOT.md had to stay backward compatible with `parse_slot_md()` in `slot_manager.py`. The parser splits the issue line on `#` and expects exactly two parts — a constraint the design review caught when I'd naively added a title suffix. The new sections (`## Batch Plan`, `## Session State`) are cleanly skipped by the existing parser's section-flag guards. A `Type: epic` line distinguishes epic slots from regular ones.

`work-slot next` advances through issues: checks off the current one in SLOT.md, appends it to `COVERS` in `.meta`, and optionally ticks the GitHub epic checkbox. Each completed batch is a safe exit point — you can merge everything done so far, archive the slot, and create a new one for the remaining batches later. Or just keep going.

## The Routing Bug

There was a second problem hiding behind the epic work. After clearing a session and saying "resume handover" on a feature branch, the `work` skill routed to `work-resume` — the pause-stack path for restoring branches from main. Wrong destination entirely. The LLM was keyword-matching "resume" before checking which branch it was on.

The fix was to stop asking the LLM to interpret state. `work_router.py` checks branch, slot context, epic state, pause stack depth, and handoff existence in a single deterministic call. Outputs `ROUTE=resume_branch`. The skill reads one line and dispatches. No interpretation, no variance, no confusion.

There's a broader pattern here: when a routing decision depends entirely on filesystem state, the LLM adds no value to the decision — it only adds variance. Extract it to a script. Keep the LLM for judgment calls.

## What This Enables

The epic slot is infrastructure for a workflow pattern that didn't have tooling before: sustained multi-session work on a large body of related issues, with the machine tracking progress and the human focusing on the work. Sessions can wrap and resume naturally without losing context. The batch plan gives structure without rigidity — you can exit at any safe point and re-enter later.

The `epic_manager.py` module is deliberately separated from slot infrastructure. It operates on batch plan data structures, not on worktrees or `.m2` isolation. That separation is load-bearing — it enables future single-repo epic support where the same advancement and progress logic stores state in `.meta` extensions rather than SLOT.md, without needing the multi-repo slot machinery.

Between this and the worklog tracking from last week, the work lifecycle is becoming something more than a collection of scripts. It's a system that remembers what you're doing, where you are, and what comes next — across sessions, across repos, across the gaps where context used to get lost.
