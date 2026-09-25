---
layout: post
title: "The Landing That Shouldn't Have Tried"
date: 2026-09-22
entry_type: note
subtype: diary
projects: [Hortora/soredium]
tags: [work-end, slots, orchestrator, bug-fix]
---

# The Landing That Shouldn't Have Tried

Slot 202 taught us something we should have anticipated: when a slot contains multiple repos but only one has actual work, the landing step still tries to land them all.

The slot had claudony, engine, and blocks. Only claudony had branch commits. Engine and blocks were sitting on main with no feature branch — the orchestrator walked through them anyway, hit `merge_failed` and `dirty_worktree`, and the whole close sequence stalled.

The rebase step already had a guard for this. If a repo's HEAD is an ancestor of main, the per-repo fan-out skips the rebase and marks it done. The landing step had no equivalent — it blindly dispatched `work_end_execute.py land` for every repo in the `.slot` file.

The fix checks two things before landing each repo: does the branch exist, and does it have any commits ahead of the base? If either answer is no, the repo is skipped. The check only fires on positive confirmation from git — if the git commands themselves fail (say the repo isn't properly initialised), the existing error handling picks it up downstream rather than silently swallowing a real problem.

One subtlety worth noting: some of the existing orchestrator tests create fake git repos — just a `.git/` directory with nothing inside. The first version of the fix treated a failing `git branch --list` as "no branch" and skipped, which broke those tests. The distinction matters: `returncode == 0` with empty output means "git works, branch absent." A non-zero return means "git itself failed" — and that's a different problem that shouldn't be silently skipped.

This is the kind of bug that only surfaces in multi-repo slots where work is concentrated in one repo. Single-repo branches and slots where every repo gets touched never hit it. The fix is small but the blast radius of not having it — a stalled close sequence that requires manual intervention — is disproportionate.
