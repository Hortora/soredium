---
layout: post
title: "When the orchestrator lies about what it did"
date: 2026-08-31
entry_type: note
subtype: diary
projects: [Hortora/soredium]
tags: [orchestrator, slot-mode, work-end, duplicate-detection, git]
series: issue-312-detect-merge-rebase-dupes
---

This session started with a simple bug report about rebase conflicts being retried three times for no reason, and ended with a fundamental reworking of how the work-end orchestrator handles multi-repo slot work.

The rebase retry bug was straightforward: `REBASE_CONFLICT` is a deterministic failure. Same branch, same base, same conflicts — retrying produces identical results. The fix was a `NON_RETRYABLE_ERRORS` classification set and an `on_mechanical_error` callback in the engine. First occurrence yields `ACTION=user_input` with the conflict scope (file count, file list), and the user decides: resolve manually, skip the rebase, or abort. The `conflict_resolved=yes` parameter — which had been documented but never wired up — now marks the step done.

But the real discoveries came from the slot-mode per-repo machinery.

`_phase_skip()` writes single keys like `promote=done` when the lifecycle state is ahead of the close progress. In non-slot mode, that's correct — one step, one key. In slot mode, the step fans out across repos (`promote:engine`, `promote:blocks`, `promote:qhorus`), and `ctx.done("promote")` returning `True` from the single key means the per-repo handler is never called. Secondary repos are silently skipped. The fix writes composite keys in slot mode, but the deeper fix was structural: `run_loop` now checks the per-repo callback *before* `ctx.done(step.name)`, so a stray single key from any code path — not just `_phase_skip` — can never bypass per-repo handling again.

The subtler bug was in the engine's error escalation path. When a per-repo mechanical step fails three times, `_make_error_result` returns `{"ACTION": "user_input", "CONTEXT": "step_failed"}` — no `ERROR` key. The engine checked `if "ERROR" in handled`, which returned `False` for the escalation dict, and silently continued past the step. The step appeared to succeed. Changed to `if handled` — truthiness instead of key membership — matching how the judgment branch already works.

Once per-repo handling worked correctly, it became clear that failing on the first repo and stopping was wrong too. If engine's rebase has 33 conflicts but blocks and qhorus are clean, the user needs to see all three results before deciding strategy. `_close_per_repo_mechanical` now tries all remaining repos, marks successes, collects failures, and returns a consolidated `CONTEXT=per_repo_failures` report.

The progress summary got a visual overhaul — bordered table with Step/Status/Result columns, per-repo breakdown for slot mode, retry counts for steps that needed multiple attempts, and an Incidents section that reads from `.close-log.jsonl` to surface errors, reconciliation corrections, and stale progress resets. The report is generated mechanically by the orchestrator when it returns `ACTION=complete` — no skill instruction needed, no LLM discretion.

Two smaller fixes that prevent future corruption: `commit_transition()` now deletes the `.plan` file when transitioning to `idle` instead of leaving it on disk with `state: closing:stamped`, and a new `check_active_work()` function in the worklog queries for active work items on the same issue before `scaffold.py` or `plan_manager.py append` allows new work to start. The duplicate work detection gates at both work-start and plan queue append, with `skip-duplicate-check=yes` as an explicit override.

The duplicate commit detection for #312 — the branch's focal issue — uses a two-stage algorithm: message pre-filter for speed, then `git patch-id --stable` for precision. The pre-merge gate in `_sync_repo` detects duplicates before the merge/rebase decision, then reconciles by dropping the duplicate commits via `GIT_SEQUENCE_EDITOR` — a Python script that edits the rebase todo list to remove `pick` lines for commits whose patch-id already exists on the blessed branch. One non-obvious discovery during testing: cherry-picking between repos that share the same bare ancestry produces identical SHAs when the histories haven't diverged. You need an independent upstream commit to create genuinely different SHAs — otherwise git resolves both commits to the same object and the duplicate detection finds nothing.

What ties this session together is a pattern: the orchestrator was treating non-deterministic problems as deterministic (rebase retries), deterministic problems as non-deterministic (single-key bypass), and partial information as complete (one-repo-at-a-time reporting). Each fix moved toward the same principle — when something fails, show the full picture and let the human decide.
