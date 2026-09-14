---
layout: post
title: "The Guard That Watched the Wrong Thing"
date: 2026-09-11
entry_type: note
subtype: diary
projects: [Hortora/soredium]
tags: [work-end, slot-lifecycle, session-guard, artifact-promotion]
---

# The Guard That Watched the Wrong Thing

Two bugs in the slot lifecycle, both about the same mistake: using a proxy signal when you need the real one.

## lsof Sees File Descriptors, Not Sessions

The `archive_slot` function has a guard that checks whether a Claude session is actively working in a slot before archiving it. The guard uses `lsof +D` — scan the directory tree for open file descriptors. If any process has files open, block the archive.

The problem: `/clear` in Claude Code resets the conversation context, which releases file descriptors. The process — same PID, same working directory — is still alive and about to resume work. But `lsof` sees nothing. The guard passes. The slot gets archived out from under the session.

This happened with slot 186. Session A was working in `pages/`. Session A ran `/clear`. Session B ran `work-end`, `lsof` found no open FDs, and the slot moved to `attic/186/`. Session A came back to a broken working directory with no lifecycle files and no git repo.

The fix is a PID stamp. `write_occupant_pid` writes the session's PID to `.occupant-pid` at slot activation. `check_occupant_pid` calls `os.kill(pid, 0)` — the Unix "are you alive?" signal that doesn't actually kill anything. If the process is alive, the archive blocks. If it's dead (stale file from a crashed session), it falls through to the existing `lsof` check as a secondary signal.

The PID check is now the first guard in the archive chain — before active plan, unmerged content, landed verification, and `lsof`. A live session should block everything.

## Promote Was Broadcasting to Every Repo

The second bug was in the work-end orchestrator. In a multi-repo slot, three mechanical steps fan out per-repo: promote, rebase, and land. Rebase and land genuinely need per-repo execution — each repo's branch needs rebasing and merging independently. But promote is different. Artifact promotion (specs, ADRs, blog entries) should target the repo that owns the issue, not every repo in the slot.

What happened: in a slot with neocortex, engine, and soredium, work-end promoted neocortex's specs into engine's `docs/specs/`. Engine's repo didn't expect those directories. The merge failed, a rescue branch was created, and the final verification gate blocked.

The fix: remove `promote` from `PER_REPO_EXECUTE_STEPS`. Promote now runs once as a single step, targeting `ctx.project` (the issue-owning repo from the orchestrator args) with its per-repo workspace resolved via `_resolve_repo_workspace`. Rebase and land stay per-repo. The design spec already said "close_artifacts.py runs once per unique workspace, not once per repo" — the code just hadn't caught up.

Both bugs share a root cause: treating a collection of things as uniform when they aren't. File descriptors aren't sessions. Repos in a slot aren't all artifact targets. The proxy worked until the edge case arrived.
