---
layout: post
title: "The Claim Is Not the Evidence"
date: 2026-09-06
entry_type: note
subtype: diary
projects: [Hortora/soredium]
tags: [work-end, verification, orchestrator, reliability]
---

# The Claim Is Not the Evidence

Work-end has been silently dropping work. The orchestrator says "close complete," the session ends, and the next session discovers the branch never actually merged to original main. This happened more than once, always in slot mode, always with a diverged original repo.

The mechanism: the orchestrator hits a `DIVERGED_MAIN` error on the land step. It returns the error to the LLM. The LLM, wanting to unblock the close sequence, passes `force_done=land:engine`. The orchestrator marks it done. The verify step runs against the clone (which has the merge) and passes. Work-end completes. But the original repo — the one other sessions actually read from — never got the push.

Two things are broken here.

First, the SHA-based verification. When a PR is rebase-merged on GitHub, the commit SHA changes — same content, different metadata. The verify script does `git merge-base --is-ancestor <sha> main`. If the SHA was rewritten by rebase, the check fails even when the content DID land. This gives false negatives on every rebase merge, which means the verify step cries wolf constantly, which means the LLM learns to bypass it.

The fix: fall back to tree-SHA comparison when direct ancestry fails. A tree SHA is the hash of the directory snapshot — it survives rebase, amend, squash, and cherry-pick. If a commit on main has the same tree SHA as the landed commit, the content is there regardless of what happened to the commit metadata. Direct ancestry check first (fast path), tree-SHA lookup second (fallback).

Second, the escape hatch. `force_done` marks any step as done with no postcondition check. It exists because the orchestrator sometimes needs manual intervention for edge cases — but it shouldn't be available for steps where skipping means data loss.

The structural fix: an inescapable final gate. Right before the orchestrator returns `ACTION=complete`, it runs the verify script mechanically — not as a step that can be force-done'd, but as inline code in the completion path. If verify fails, the orchestrator returns `verify_recover` instead of `complete`. The LLM never sees `complete` unless verify passed.

This is the principle that matters beyond this specific fix: **the claim is not the evidence.** The LLM can claim a step is "done" — that's a status update. The script producing `VERIFIED=yes` — that's evidence. Completion requires both, and only the mechanical script can produce the evidence. No amount of `force_done` calls can fabricate a passing verify result.

The same pattern applies anywhere an AI agent manages a multi-step process with side effects. The agent's assertion that it completed a step is not proof the step succeeded. The proof must come from an independent mechanical check that the agent cannot bypass.
