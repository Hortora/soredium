---
entry_type: note
subtype: diary
title: "Trust but verify — making the orchestrator a gatekeeper"
date: 2026-08-27
series: issue-301-sync-main-rebase-fix
issue: 301
branch: issue-301-sync-main-rebase-fix
project: soredium
projects: [Hortora/soredium]
author: mdp
tags: [orchestrator, verification, state-machines, llm-safety, hooks, worklog]
---

# Trust but verify — making the orchestrator a gatekeeper

*Continues from [The backdoor in inversion of control](2026-08-26-mdp01-the-backdoor-in-inversion-of-control.md).*

The slot 162 post-mortem laid it out cleanly: six failures, all in the orchestration layer, none in the execution scripts. The promote, rebase, land, and verify scripts worked fine. The orchestrator — the thing coordinating them — was the source of every bug.

The common thread: the orchestrator trusted everything it was told. `step_done=review` — believed. `.close-progress` from a different branch — believed. Path to `.slot` being a file instead of a directory — never checked. When the LLM improvised manual workarounds after a crash, the orchestrator had no way to detect that half the side effects were missing.

## Verify artifacts, not claims

The first-principles question: what CAN the orchestrator verify? The LLM's claim that it ran code review is unreliable. But findings.jsonl entries with `source=code-review` either exist or they don't. That's ground truth.

The fix adds `verify_fn` to the step definition model. When the LLM calls `step_done=code_review`, the orchestrator checks the postcondition before accepting. For review sub-steps: `produced=N` must be set (even `produced=0` for clean reviews). For the forcing function: no open findings may remain in findings.jsonl. The orchestrator rejects `step_done` when verification fails.

This split review into seven individual orchestrator steps — code_review, four branch-audit dimensions (conformance, coherence, structure, robustness), loose_ends, and forcing_function. The old single "review" step bundled all seven with no enforcement. Conformance and coherence checks were silently dropped for weeks.

## Branch scoping

`.close-progress` now carries `_branch=<name>`. On entry, if the branch doesn't match, the file is discarded. This killed the stale-progress-from-another-branch class of bugs in one line.

## The LLM reads everything and picks what it wants

The most interesting discovery was behavioural: a 700-line SKILL.md with both the orchestrator loop (abstract) and handler details (concrete) trained the LLM to skip the loop. It read "write HANDOFF.md using this template" in the handler section, latched onto it as the most actionable instruction, and went straight there — never calling the orchestrator.

The fix: extract handlers into separate files loaded lazily. The SKILL.md shrinks to ~80 lines — context resolution, the orchestrator call, and a dispatch table pointing to handler files. The LLM has one instruction: call the orchestrator and follow its output. It can't shortcut to handlers it hasn't read.

## The hook as the final gate

Even with lazy loading, the LLM can still bypass the orchestrator entirely. The PreToolUse hook catches this: `orchestrator-gate.sh` blocks HANDOFF.md commits without wrap orchestrator completion, and blocks branch-closed stamps without close orchestrator review. The LLM can ignore the SKILL.md. It cannot ignore the hook.

## What's next

The remaining gap is auto-resume: when a session crashes mid-close, the next session finds `.close-progress` with partial state. The detection and routing exist; the user-facing "resume from step X?" flow (#304) doesn't yet.

Also landed on this branch: sync-main merge-vs-rebase (don't rewrite already-pushed SHAs), upstream PR step (detect fork drift and offer PRs), plan_manager dedup, and `.landed` as an append-only ledger for sequential slot branches.
