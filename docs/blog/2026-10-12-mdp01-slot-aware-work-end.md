---
layout: post
title: "The Slot Blindspot: Four Bugs That Could Archive Your Active Work"
date: 2026-10-12
entry_type: note
subtype: diary
projects: [Hortora/soredium]
tags: [work-end, slots, multi-repo, orchestrator, verification]
series: issue-438-archive-slot-check-all-repos
---

# The Slot Blindspot: Four Bugs That Could Archive Your Active Work

The work-end orchestrator was designed for single-repo branches. Slots — multi-repo workspaces where you run neocortex, examples, and blocks side by side — exposed assumptions that had been invisible until now.

The scariest bug was in archive_slot. After closing one repo's work, the orchestrator would offer to archive the entire slot. It checked whether repos classified against the *closing branch* had landed. But it never checked whether another repo in the same slot had active work on a *completely different branch*. The classification function looks for a specific branch name in each repo — if examples is on `issue-115-drive-expression-gap` and you're closing `issue-500-neocortex-work`, examples shows up as `NO_BRANCH`. Not "has active work." Just "doesn't have this branch." The skip predicate let it through, and the user got offered an archive that would bury live work in the attic.

The fix scans the slot directory directly. For each repo, check its actual checked-out branch via `git rev-parse --abbrev-ref HEAD`. If it's not on main, someone is working there. For workspace directories, check for `.plan` files — queued work that hasn't started yet. Either condition blocks the archive offer.

The same classification blindspot showed up in sweep steps. When work-end runs protocol sweeps, CLAUDE.md updates, and doc freshness checks, it iterates *every* repo in the slot. In a session that only touched neocortex, this produces six no-op steps for examples and blocks that the user has to manually skip through. We now auto-mark repos with no changes on the branch as done before the sweep loop runs, using the same repo disposition data that already exists for the land step.

The third fix was about cross-session verification. The verify script checked git state — branches merged, stamps present, issues closed — but it reported failures as a single opaque `VERIFIED=no`. The LLM handler had to guess what to fix. Now verify outputs structured `FAILURE_N=check_name: message` lines for each failing check, and the handler includes a recovery-action table mapping each check name to its specific fix command. When Session A picks up where Session B left off, it knows exactly what's undone.

The forcing function had a cosmetic issue where it reported "1400 OPEN" — counting every open GitHub issue in the repo instead of reading branch-scoped findings from `findings.jsonl`. The data source was already correct in the orchestrator code, but the handler didn't explicitly say "read from findings.jsonl, not GitHub issues." A single missing instruction, and the LLM reached for the wrong tool.

Code review caught one more thing: the sweep auto-mark wrote to disk but didn't update the in-memory progress object. The next line checked in-memory state, found the repo still pending, and yielded a step that should have been skipped. A classic stale-cache-after-write — the kind of bug that works on the second invocation but wastes a round-trip on the first.

These bugs share a theme: single-repo assumptions embedded in code that runs in multi-repo contexts. The classification model, the sweep iterator, the verify output — each was correct for the case it was designed for and wrong for the case it actually encountered. Slots are the primary way multi-repo work happens now, and the orchestrator needs to treat them as first-class, not as a variant of the single-repo path with extra repos bolted on.
