---
layout: post
title: "When the Orchestrator Gets Stuck: Mechanical vs Judgment Failures"
date: 2026-09-14
entry_type: note
subtype: diary
projects: [Hortora/soredium]
tags: [orchestrator, work-end, slot-closure, error-handling]
series: issue-368-work-end-slot-closure
---

# When the Orchestrator Gets Stuck: Mechanical vs Judgment Failures

Slot 181 was a mess. Eight repos of dual-framework extraction work, all on main, completed and reviewed — then the close sequence stalled. The orchestrator retried `promote` four times, each time hitting the same structural failure, each time escalating to the user with "step failed" and no way out.

The `.close-progress` file told the story: `promote_mechanical_attempt=4`. Review pass complete. All 25 per-repo sweeps across protocol, CLAUDE.md sync, impl-doc-sync, and doc freshness — done. The orchestrator had dutifully worked through hundreds of judgment interactions across every repo. Then it hit a single mechanical step and froze.

## The dead end was designed in

The original close orchestrator spec (issue #271, section D10) explicitly designed two retry policies: judgment steps escalate to the user after MAX retries because the user can provide the missing judgment. Mechanical steps auto-skip because the user has no useful action — a worktree creation failure or a push to the wrong remote is deterministic. Retrying doesn't help. Asking the user doesn't help.

The implementation didn't follow the spec. It treated mechanical failures the same as judgment failures: retry, retry, retry, escalate. The escalation was a dead end — the LLM couldn't mark a mechanical step as done (blocked by design), couldn't skip it (the `last_yielded` check rejected it), and didn't know about the undocumented `force_done` escape hatch.

## Two root causes, not five

The issue description listed five gaps, but from first principles only two were independent. The orchestrator's uniform retry policy was one. The other: `verify_slot_close.py` checked all 25 repos in the slot when only 9 had work. The remaining three gaps — landing never running, stamping never happening, pushing never executing — were consequences of the first.

The verify scoping issue was simpler but equally corrosive. The `.slot` file had a `Covers:` line listing exactly which repos had work: `platform:276,engine:1049,work:394,...`. But the verification function scanned every git directory in the slot root, found no landing SHAs for `aml`, `clinical`, `devtown`, and a dozen others that were never part of the work, and reported them all as failures.

## The fix is the spec

The auto-skip implementation adds a third terminal state: `skipped_error`, distinct from both `done` and `skipped`. When a mechanical step exhausts its retries, the orchestrator marks it `skipped_error` and continues. The close report surfaces it as "error-skipped" with retry detail. The verification step downstream catches the gap as a warning.

The distinction matters because it's visible. A step marked `done` means it succeeded. A step marked `skipped` means it was deliberately skipped (user chose not to run it). A step marked `skipped_error` means it failed structurally and was bypassed — the verification layer has to compensate. The progress summary tells you exactly which category each step landed in.

For verification, `_parse_covers_repos` extracts the repo names from the `Covers:` line and filters all downstream checks. When no `Covers:` line exists (older slots, single-issue work), it falls back to checking everything — no regression for existing slots.

## What this opens up

The `skipped_error` state is a general mechanism, not specific to `promote`. Any mechanical step that fails structurally — a push to a deleted remote, a rebase against a force-pushed branch, an archive of a slot that's already been cleaned up — auto-skips and gets caught by verification. The orchestrator stops being a bottleneck for infrastructure failures that have nothing to do with the quality of the work.
