---
entry_type: note
subtype: diary
title: "Wiring the orchestrator — from stubs to a real close sequence"
date: 2026-08-25
series: issue-271-mechanise-work-end
issue: 271
branch: issue-271-mechanise-work-end
project: soredium
projects: [Hortora/soredium]
author: mdp
tags: [orchestrator, implementation, crash-recovery, deployment-safety, state-machines]
---

# Wiring the orchestrator — from stubs to a real close sequence

The [last entry](2026-08-24-mdp01-the-llm-that-couldnt-follow-instructions.md) diagnosed the problem: work-end's 660-line SKILL.md was a sequence the LLM couldn't reliably execute. The design answer was inverted control — a Python script that owns the sequence and yields to the LLM only for judgment. That session produced the architecture spec and a partial implementation.

Partial turned out to be the operative word. The orchestrator handled judgment sequencing beautifully — yielding ACTION=review, ACTION=sweep_config, ACTION=squash at the right moments. But every mechanical step was a stub. `update_close_progress(workspace, "land", "done")` without calling a single script. The revert commit said it plainly: "stubs all mechanical steps and has no slot awareness."

Twenty-three tests passed. Every one of them verified the action *sequence* — which ACTION comes next given this progress state — and none verified whether a subprocess was actually *called*. A test that checks "did `land` yield `arc42_scan` next?" passes identically whether `land` calls `work_end_execute.py land` or just marks itself done. The gap was invisible until a real close failed.

## The spec that didn't exist

The design spec had 12 adversarially reviewed decisions. It covered architecture, action types, lifecycle mapping, validation, error policy, slot routing, forward-only constraints, and concurrency protection. What it didn't have was mechanical wiring detail — the exact CLI invocation, output keys, success/failure criteria, and evidence construction for each of the 25+ steps.

Rather than patch the reviewed spec (and risk introducing inconsistencies into a validated document), we wrote a continuation spec that references the original's decisions as settled foundation. Six new decisions targeted the specific failure modes: step definition tables to prevent stubs (D13), a capability matrix pinned to a git SHA to prevent capability loss (D14), evidence-based recovery (D15), verbatim action handler extraction (D16), shadow mode rollout with fallback telemetry (D17), and a scripted dry-run audit (D18).

The capability matrix was the anchor. Ninety-three discrete capabilities extracted from every line of the current SKILL.md — each one mapped to its target in the new system. None dropped. The matrix becomes the implementation checklist and the post-deployment audit artifact. If it's not in the matrix, it doesn't exist in the new system. If it's in the matrix and not wired, the audit catches it.

## Building the step walker

The existing orchestrator was a hand-coded `_next_action` function — a long chain of `if not done("review")... if not done("sweep_config")...` with stubs sprinkled in. The refactoring replaced it with a data-driven step walker: a `STEPS` list of `StepDef` objects, each with a name, phase, type, and optional `script_fn` that returns the subprocess command.

The walker is simple. For each step: skip if the skip condition fires, skip if already done, execute if mechanical, yield if judgment. Mechanical execution calls `_run_script`, which runs the subprocess, parses KEY=VALUE output, and handles errors. The `OrchestratorContext` dataclass threads state through the walk — workspace paths, mode flags, captured output from prior steps, landed SHAs for lifecycle evidence.

Mode routing lives in the `script_fn` lambdas, not in the walker. `_land_script` returns `work_end_execute.py land` for branch mode, `slot_manager.py merge-slot` for slot mode, and `None` for main mode (the orchestrator pushes directly). The walker doesn't know about modes — it just calls whatever `script_fn` returns.

## The reconciliation problem

Crash recovery exposed a subtlety I didn't expect. The spec called for evidence-based reconciliation: on every start, check that steps marked "done" in `.close-progress` have actual evidence (files exist, git state matches, remote state confirmed). The implementation checked review, promote, rebase, land, verify — all of them.

Fourteen tests failed immediately. The reconciliation was resetting `review=done` because no `findings.jsonl` existed — but a clean review (zero findings) legitimately produces no findings file. Forage with nothing garden-worthy produces no entry files. Write-content that's deferred produces no blog file.

The distinction is mechanical vs judgment. Mechanical steps produce independently verifiable artifacts — `land` creates `.execute-progress` entries, `promote` creates files in `docs/`, `stamp` writes an empty commit on the branch. Judgment steps are LLM-executed — the orchestrator yields an action, the LLM does the work, and the orchestrator can't independently verify the LLM actually did it. Reconciliation that checks judgment steps can't distinguish "the LLM did the review and found nothing" from "the LLM was never asked to review."

The fix: reconciliation only evidence-checks mechanical steps. Judgment steps are trusted — if progress says done, the orchestrator accepts it. Phase gating adds a second filter: only check evidence for steps in phases *behind* the current lifecycle state, not the current phase (where the orchestrator is actively working).

## The 20 missing steps

The SKILL.md rewrite exposed a gap I hadn't noticed. The orchestrator's STEPS list had 21 entries — the core judgment and mechanical steps. The spec lists 41. Twenty steps were missing entirely: every report step (`report_init`, `report_promote`, `report_land`, etc.), every lifecycle transition (`review_pass`, `promote_pass`, `push_pass`, `merge_pass`, `stamp_pass`, `cleanup_pass`), the promote step itself, slot-specific steps (`write_marker`, `archive_slot`), and the post-close cleanup (`delete_progress`, `report_render`).

These weren't stubbed — they simply weren't in the sequence. The orchestrator would jump from `write_content` directly to `trajectory`, skipping the `review_pass` lifecycle transition and the entire promote phase. It worked in tests because the tests set `meta_state` directly instead of relying on lifecycle transitions to advance it.

Adding them was mechanical but required two new functions: `_fire_lifecycle` to call `lifecycle.py commit-transition` with evidence dicts, and `_build_evidence` to construct the right evidence for each lifecycle event from captured script output. The evidence dict for `push_pass` pulls `LANDED_SHA` from the land step's stdout. For `promote_pass`, it sums `WORKSPACE_PROMOTED` and `PROJECT_PROMOTED` from the promote output. Each event has a specific shape — the lifecycle state machine validates it.

## The dry-run audit and the set iteration bug

The audit script runs the orchestrator in `dry_run=yes` mode for each of the three modes (branch, slot, main). It calls `run_orchestrator` in a loop, marks judgment steps done to advance, and tracks which steps are reached by diffing `.close-progress` between calls.

The first run cycled infinitely. After trajectory, it looped back to review. The lifecycle transitions were firing correctly inside each call — `review_pass`, `promote_pass` ran and marked themselves done — but the audit was passing `meta_state=closing:review` on every call because it tracked state progression from a Python set. When multiple lifecycle steps appeared in the progress diff, set iteration order determined which advancement "won." If `review_pass` iterated after `promote_pass`, the state regressed from `closing:promoted` back to `closing:verified`. The stale-progress detector then saw progress ahead of meta_state and deleted everything.

The fix was one line of logic: compare all lifecycle advancements against a phase ordering and take the highest, instead of applying them one by one from a set.

## The deployment safety problem

With the audit passing across all three modes, I was ready to sync the new SKILL.md and close the branch. Then the question: what happens to other sessions?

`sync-local` copies all files from the skill directory — SKILL.md and Python scripts — to `~/.claude/skills/work-end/`. The new SKILL.md references the orchestrator's dispatch loop. Any new session invoking work-end would get the new instructions immediately. But the orchestrator code only existed on this feature branch. Sessions on main, other branches, or different repos would get dispatch loop instructions pointing at scripts that don't exist.

I'd already run `sync-local` twice during development. The new SKILL.md was already deployed. The fix was to restore the old SKILL.md from git history and delay the real deployment until after the branch merges to main — when the orchestrator files are accessible from any checkout.

This is a general problem with any system that deploys configuration files independently from their backing implementation. The skill file and the scripts it references need to be deployed atomically. Today they aren't — `sync-local` copies the current working tree unconditionally. A branch-aware deployment check would catch this, but it doesn't exist yet.

The branch closes with the old SKILL.md installed. The orchestrator gets its first real close on the next work-end after merge. The dry-run audit proves the sequence is correct; the real test is whether the subprocess calls produce the expected output when they hit real git repos and real GitHub APIs.
