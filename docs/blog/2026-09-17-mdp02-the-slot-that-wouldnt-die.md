---
title: "The slot that wouldn't die"
date: 2026-09-17
author: mdp
entry_type: note
subtype: diary
tags: [slot-lifecycle, work-end, orchestrator, state-machine]
---

# The slot that wouldn't die

Slot 198 finished its work. Code landed on canonical. `.landed` written. By every signal the archive tooling knows to check, the slot was done. Then new issues got appended to its `.plan` — and the slot was live again, with active work queued, but still carrying a `.landed` marker that made it look archivable.

The current mitigation — `archive-landed.py` checking `has_active_plan()` — is a secondary defence that works until it doesn't. If the `.plan` happens to be empty between issues (after one closes, before the next is appended), the slot passes every archive check. The primary signal was lying.

The real problem isn't stale markers. It's that work-end has no concept of "cycle" — finishing one issue and continuing to the next on the same slot. Every work-end is terminal: sync code, write `.landed`, stamp branches, archive. There's no path where you land the code but keep the slot active.

## What changed

I wanted work-end to be queue-aware. When the `.plan` has remaining items, work-end should cycle: sync code to canonical, close the current issue, advance the queue, and stay active. When the queue is empty, it terminates normally. The user never picks the mode — the orchestrator reads the `.plan` and acts accordingly.

Terminal closure with remaining items is a hard gate. The orchestrator won't do it. You must explicitly empty the `.plan` first — no `--force` flag, no "are you sure?" prompt that someone clicks through. The queue is the source of truth for slot liveness.

The implementation turns out to be mechanical. The orchestrator already has a `skip_fn` field on every step — predicates that decide whether a step runs. We added `_skip_cycle_mode`, which checks `has_uncompleted_items()` on the `.plan`, and `_or_skip`, which composes it with existing predicates. Ten terminal steps (`.landed`, stamp, archive, checkout-main, cleanup) gained cycle-mode skip predicates. A new `cycle_pass` lifecycle step fires `issue_cycle` to transition `closing:merged → active` when cycling.

The lifecycle state machine needed one new transition. The slot state machine needed one new entry (`landed → active`). And `append_to_queue()` gained a `slot_path` parameter as a belt-and-suspenders — if `.landed` somehow exists when new work is appended, it gets cleaned up retroactively.

## Why it matters

Slots are how multi-repo work gets done. A slot that finishes one issue and starts the next is the normal workflow for large epics — you don't want to archive and re-create the slot infrastructure just because the first issue landed. Being able to call work-end mid-epic, have it sync code to canonical with the full review pipeline, and continue seamlessly is the difference between "slots work for one-shot issues" and "slots work for sustained multi-issue campaigns."

The pattern also surfaces something I hadn't considered: work-end's review pipeline runs in full during a cycle. It's not a shortcut — the code still goes through code-review, branch-audit, sweeps, and content creation before landing. The only things skipped are the terminal steps that don't make sense when the slot continues. That means every issue in an epic gets the same quality gate, not just the last one.
