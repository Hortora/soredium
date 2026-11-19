---
layout: post
title: "The File That Should Never Be Deleted"
date: 2026-11-05
entry_type: note
subtype: diary
projects: [Hortora/soredium]
tags: [work-end, orchestrator, architecture, deletion, queue]
series: work-end-arc
---

# The File That Should Never Be Deleted

The [previous entry](2026-11-04-mdp01-eighty-bugs-in-seventy-days.md) diagnosed five structural root causes behind eighty bugs in seventy days. Today we deleted the system that produced them.

## The core insight

Every plan-destruction bug — and there were twelve — had the same shape. Something deleted `.plan` as part of ceremony cleanup. The issue queue went with it. The queue held deferred items, tracking state, the list of what to work on next. All gone because the ceremony needed to tidy up after itself.

The fix wasn't "don't delete `.plan`." Seven independent code paths deleted it, each for a defensible reason. The fix was separating the two things that should never have shared a file: the issue queue (persistent, survives failures, carries state across sessions) and the ceremony state (ephemeral, exists only while close is running, disposable on failure).

Two files: `.queue` for the first, `.close-state` for the second. The queue is never deleted during normal operation. The ceremony state is created when the close starts and removed when it succeeds. If the ceremony fails, `.close-state` stays — a marker that says "something was in progress." The queue is untouched.

## What the deletion looks like

The old system: 10,800 lines across 58 files. A lifecycle state machine with 12 states. A corruption detector with 13 scenarios. An orchestrator with 53 steps filtered by 5 modes and 5 dispositions. Recovery mechanisms that triggered other recovery mechanisms.

The new system: `close.py` at 600 lines. One function: `close(workspace)`. It reads the queue and git state, resolves which repos have branches to close, runs preflight checks, lands each branch (rebase + squash-merge), stamps them, advances the queue. Either everything succeeds or nothing changes. No lifecycle states. No progress file. No recovery engine — idempotency replaces recovery.

We removed 28,400 lines across 70 files. The orchestrator, the lifecycle state machine, the corruption detector, the verification subsystem, the handler dispatch, 41 test files for code that no longer exists. What survives is what other systems still depend on — the orchestrator infrastructure that the handover flow uses, the land mechanics that slot archival uses. Those are follow-up rewrites, not blockers.

## The queue model

The `.queue` format is deliberately simple:

```
- [x] Hortora/soredium#381 — Implement batch processing
- [ ] Hortora/soredium#382 — Add retry logic        ← active
- [ ] Hortora/soredium#383 — Dashboard metrics

## State
branch: issue-382-retry-logic
issue-repo: Hortora/soredium
status: active
```

Four status values: `active`, `paused`, `drained`, `idle`. No `closing:review`, no `closing:promoted`, no `closing:stamped`. The ceremony doesn't need states — it's a function call, not a state machine. You call it, it runs, it's done.

Migration from `.plan` is transparent. `read_queue()` detects a `.plan` file, migrates it to `.queue` (converting the old `state: closing:promoted` to `status: active`), and renames the original to `.plan.bak`. Every consumer that used to read `.plan` now reads `.queue` through `queue_io.py` — one module, one format, one migration path.

## What this changes

The bug that finally triggered this rewrite — [#500](https://github.com/Hortora/soredium/issues/500) — was filed after the redesign branch was already underway. The orchestrator skipped mechanical steps in a multi-branch slot close, hit a verification failure, transitioned to `idle`, and deleted the `.plan`. Feature branch commits survived. Everything in the workspace — blog entries, handoff, deferred items, queue state — was gone.

That bug is structurally impossible in the new system. Not "fixed by adding a guard." Impossible. The queue doesn't know the ceremony exists. The ceremony doesn't touch the queue until it succeeds. There is no `idle` transition on failure. There is no transition at all — just a function that returns a result.

The more interesting question is what this opens up. With the queue separated from ceremony state, the queue becomes a portable artifact. It can be copied between workspaces, elevated to slot roots, backed up, diffed. It carries enough information to reconstruct what a session was working on without reading git history or session transcripts. That was always the intent of the `.plan` file. It just couldn't fulfil it while also being the ceremony's scratch pad.
