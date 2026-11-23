---
layout: post
title: "The Survey That Doesn't Touch Anything"
date: 2026-11-23
entry_type: note
subtype: diary
projects: [hortora/soredium]
tags: [lifecycle, read-only, drift-detection, survey]
series: issue-589-read-only-survey-command
---

# The Survey That Doesn't Touch Anything

Before the survey command existed, I ran the equivalent by hand — `ls`, `git status`, `git log`, file listings across every slot, clone, and workspace in a family root. It found real problems: a diverged clone, queues naming branches that weren't checked out, a stale `.close-state`, five differing queues in one slot. It also found 33 blog promotion gaps, of which 32 were false.

The false positives all had the same cause. The hand-survey compared files on disk. When a project checkout was on a feature branch cut before a promotion, the entry was absent on disk but present on `main`. The file was there — just not visible from the current checkout. Comparing disk files was fundamentally the wrong approach.

## Base Refs, Not Disk

The fix is in what you compare. `git ls-tree -r main -- docs/blog/` returns every entry on the base branch regardless of what's currently checked out. The survey compares base branches:

```
workspace base entries  ∩  ¬project base entries  =  promotion gaps
workspace HEAD entries  -  workspace base entries =  waiting for landing
```

No disk reads for entry enumeration. The working tree is irrelevant to drift detection.

## Three Functions That Lie About Being Read-Only

Building the survey meant composing existing building blocks — `canonical_sync` for drift measurement, `queue_home` for queue discovery, `slot_io` for slot metadata. Most of them are genuinely read-only. Three are not.

`canonical_sync.follow()` runs `git fetch` and then `git merge --ff-only`. It updates the clone. `ahead_of_canonical()` calls `_onto()`, which also fetches. `reference()` fetches for non-same-store repos. All three are silent mutations — they look like read operations, they're named like read operations, but they write to the repo.

The survey inlines read-only replacements. `follow_state_readonly()` compares SHAs via `rev-parse --verify` and `merge-base` — no fetch, no merge. `ahead_readonly()` does `rev-list --count` between the canonical SHA and the branch. Both work because clone repos use `--shared` alternates and can see canonical's objects without fetching.

The read-only guarantee isn't just structural. The test snapshots every file under the family root before the survey runs, then asserts byte-for-byte equality after. If anything changes — a ref update, a working tree modification, a `.git` state file — the test fails.

## What the Survey Reports

Three layers: discover, inspect, report.

**Discovery** walks the filesystem to find every area — canonical repos, numbered slots, permanent clones, attic. Workspaces are paired with their project (via `wsp-` naming or `proj` symlink), not treated as separate areas.

**Inspection** collects per-repo state (branch, dirty count, remotes, ahead-of-canonical, follow state, rebase-in-progress), queue info (via `queue_home.candidates()`), markers, closure status (stamp parsing with unstamped branch classification by area status), and blog drift. It also predicts what `work end` would do — which branches would land, what gates would refuse.

**Reporting** rolls everything into findings using the existing `verification.Finding` model. Fourteen categories from `ERROR:drift` (clone diverged from canonical) to `INFO:landed-not-archived` (slot ready for archive).

## Closure Refs

The brainstorm surfaced a related gap. When a branch closes, the stamp commit (`chore: branch closed — landed as <SHA>`) moves the branch tip. The stamp is the record — but it's embedded in a commit message, which means tools that want to know "was this branch's work landed?" have to parse commit messages.

I filed a separate issue for structured closure refs in the workspace repo — `refs/soredium/closed/<branch>` pointing at the last real commit, with metadata in a blob. The survey reads these when present and falls back to stamp parsing for older branches. The dual path means the survey works now and gets better automatically when closure refs ship.

## The Practical Value

The survey is what tells you whether your machine is healthy. Run it against a family root, get back a list of everything that needs attention: diverged clones, stuck operations, queue mismatches, promotion gaps, stale branches. Same numbers every time you run it with no changes in between.

It replaces the hand-survey that found 32 false positives out of 33 reported gaps. The new one finds zero — because it asks the right question of the right data.
