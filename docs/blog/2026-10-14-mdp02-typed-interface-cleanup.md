---
layout: post
title: "Cleaning Up After a Type Migration"
date: 2026-10-14
entry_type: note
subtype: diary
projects: [Hortora/soredium]
tags: [orchestrator, typed-interface, schemas, git]
---

# Cleaning Up After a Type Migration

The typed LLM interface landed last session — `JudgmentRequest`, `JudgmentResponse`, `Outcome` enum, `StepType` enum. Everything the orchestrator sends to and receives from the LLM now flows through typed structures instead of ad-hoc string parsing. But a migration like that leaves debris: the old code paths kept around "just in case," identical schemas that were supposed to diverge, and a bug that only surfaced because the new types exposed a duck-typing assumption.

Three cleanup issues, all small, all in the same domain. The kind of work that's easy to defer and dangerous to forget.

## The Skip Fallback That Outlived Its Purpose

The old way to skip a step was `skip_step=X`. The new way is `step_done=X outcome=skipped` — structured, validated against the same schema as any other response. We kept both paths during the migration because the handler docs still told the LLM to send the old format. Now we updated the docs and pulled the fallback out of all three orchestrators: `work.py`, `work_end_orchestrator.py`, and `wrap_orchestrator.py`.

The interesting find was in `wrap_orchestrator.py`. It was loading progress via `read_close_progress()` — a function that returns a raw `dict[str, str]`. But `OrchestratorContextBase` declares `progress: Progress`, and the engine's `run_loop` calls `ctx.done()` which delegates to `progress.is_done()`. Python dataclasses don't enforce type annotations at runtime, so the raw dict was silently accepted at construction time. The `AttributeError` only surfaced when `run_loop` hit a mechanical step — which meant the existing tests for skip behaviour were already broken before we touched anything.

The fix was one line: `Progress.load(workspace)` instead of `read_close_progress(workspace)`. But the lesson is broader — when you migrate from raw dicts to typed wrappers in Python, the callers that construct the containing object are where the bugs hide, and they're invisible until a specific code path exercises the typed method.

## Checkout That Reports Success Before Verifying

`checkout_main` ran `git checkout main` (checked the result), then `git pull --rebase origin main` (didn't check the result), then printed `SWITCHED=yes`. If the pull hit a conflict, the repo was left in a detached rebase-in-progress state. Every subsequent `git checkout` call failed because git locks the repo during rebase. After three retries the step got marked `skipped_error` and the final gate caught it — but by then the close sequence was stuck.

The fix has three parts: abort any in-progress rebase before attempting checkout (clears leftovers from prior failures), abort the rebase if pull fails (prevents the stuck state), and verify HEAD is actually on `main` before reporting success. The pull is still non-fatal — it's fine if there's nothing to pull — but a failed rebase can no longer poison subsequent runs.

## Schemas That Were Supposed to Differ

`PRODUCED_REQUIRED_SCHEMA` and `DEFAULT_JUDGMENT_SCHEMA` were introduced as separate constants, but both had identical content. The infrastructure validated responses against schemas — but every step got the same validation regardless of what it actually needed.

Now they diverge. `DEFAULT_JUDGMENT_SCHEMA` requires only `step` and `outcome` — appropriate for sweep steps like forage and protocol where a findings count is optional. `PRODUCED_REQUIRED_SCHEMA` adds `produced` as required — for review steps and squash where the count matters. Two new schemas go further: `FORCING_FUNCTION_SCHEMA` requires `evidence.open_findings` as an integer (the gate can't pass without it), and `SQUASH_SCHEMA` requires `evidence.verified` as a boolean. The `validate_response` function now walks nested evidence schemas when the outcome is `completed`, so each step's contract is actually enforced rather than rubber-stamped.

The validation only fires on completed outcomes — skipped and blocked responses don't need evidence, and requiring it would make the skip path needlessly strict.

These three changes are the kind of follow-through that separates a migration from a migration that's actually done. The typed interface was the hard part; this is the hygiene that makes it trustworthy.
