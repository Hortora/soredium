---
layout: post
title: "The Orchestrator's State Machine Had Holes"
date: 2026-08-27
entry_type: note
subtype: diary
projects: [Hortora/soredium]
tags: [orchestrator, work-end, state-machine, reliability]
---

# The Orchestrator's State Machine Had Holes

The work-end orchestrator drives a 30+ step close sequence across code review, artifact promotion, squash, push, and stamp. It's a state machine implemented as a Python loop that yields judgment steps to the LLM and runs mechanical steps itself. Each invocation reads `.close-progress`, decides what to do next, and writes the result back.

Casehub slot 140 — a three-repo slot with engine, worker, and devtown — exposed seven holes in this state machine. Not subtle edge cases. Fundamental problems with how the orchestrator tracked what had been done.

## The Most Damaging Bug

The orchestrator uses `meta_state` (from the lifecycle state machine) and `.close-progress` (its own step-by-step tracker) as two independent state models. When `meta_state=closing:stamped` — meaning the lifecycle had already advanced past review, promotion, and push — the orchestrator would still re-run review steps if `.close-progress` didn't have entries for them.

This happened because the orchestrator only checked whether progress was *ahead* of the lifecycle (stale from a prior close) and reset it. It never checked the reverse: whether the lifecycle was ahead of progress. So after a crash-resume where `.close-progress` was partially populated, the loop would start from scratch on steps the lifecycle had already passed.

The fix is `_phase_skip`: before entering the loop, scan all steps and auto-complete any whose phase is behind `meta_state`. If the lifecycle says we're at `closing:stamped`, every review-phase and promotion-phase step gets marked done. One function, about 20 lines, but it's the single change that would have saved the most time in slot 140.

## Manual Work Was Invisible

The orchestrator validates `skip_step` against `last_yielded` — you can only skip the step that was just yielded. And `step_done` rejects mechanical steps entirely (only the orchestrator completes those). Both are correct guardrails in the normal flow. But when something was done manually — a squash run outside the orchestrator, a push done by hand — there was no way to tell the orchestrator "this is already done, move on."

The escape hatch is `force_done=<step>`. No postcondition checks, no mechanical-step rejection. It writes `<step>=done` to close-progress and clears `last_yielded` if it matches. Crude, but the alternative was hand-editing `.close-progress`, which the orchestrator is supposed to own.

## Smaller Fixes That Mattered

**user_input responses lacked a STEP field.** When the orchestrator yielded `ACTION=user_input CONTEXT=arc42_scan`, the LLM had to infer from the CONTEXT that the step name was `arc42_scan`. Sometimes it guessed wrong and reported `step_done=user_input` instead. Adding `STEP=arc42_scan` to the response made the protocol unambiguous.

**Stamp pushes bypassed `--no-verify`.** The landing and sync pushes already used `--no-verify` (the pre-push hook checks for squash candidates, which conflicts with work-end's merged commits). But the stamp push and the main-mode push didn't. Every orchestrator-driven push in slot 140 failed until `PREPUSH_ALLOW` was set manually.

**Squash had no postcondition.** A squash that reordered commits left a file on the branch that should have been removed (an add commit followed by a remove commit, but the reorder broke the patch context). The new `_verify_squash` postcondition checks for a `verified: true` field in the squash plan file — forcing the LLM to confirm diff=0 before reporting squash complete.

**Rebase after filter-repo replayed the entire history.** When `git filter-repo` rewrites branch ancestry, `git rebase origin/main` can't find the correct merge-base and falls back to the repo root. The fix: a `.rebase-onto-{repo}` file written after filter-repo, read by the orchestrator's rebase step, which passes `--onto` to skip the rewritten ancestry.

## What This Reveals

The orchestrator was designed for the happy path: a single invocation that runs from code-review to completion without interruption. Every one of these bugs was triggered by crash-resume, manual intervention, or multi-call sequences where state had to survive across process boundaries. The state machine worked fine when it ran in one shot. It broke when real life got in the way.
