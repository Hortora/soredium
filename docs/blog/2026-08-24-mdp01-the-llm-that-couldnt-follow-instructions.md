---
entry_type: note
subtype: diary
title: "The LLM that couldn't follow instructions"
date: 2026-08-24
issue: 271
branch: issue-271-mechanise-work-end-close
project: soredium
tags: [architecture, agent-design, inverted-control, reliability]
---

# The LLM that couldn't follow instructions

Four slot closures audited. Four failures. Every one caused by the same thing: the LLM skipping steps in a 660-line instruction set.

The evidence was damning. Repos not switched to main. Artifacts not promoted. Code not pushed. Blogs left uncommitted. A branch deleted instead of stamped. Not edge cases — the happy path, consistently broken. The failure mode wasn't "the LLM made a bad decision." It was "the LLM didn't execute the step at all."

I'd been tightening the instructions for months. Checklists. Hard gates. Red flag tables. Common pitfalls sections. None of it mattered, because the architecture was wrong. Telling an LLM to follow a 20-step sequence is like handing someone a 20-item shopping list and hoping they don't skip the boring items. They will.

## The inversion

The fix isn't better instructions. It's removing the LLM from the control loop.

A Python script owns the close sequence now. It reads a progress file, runs mechanical steps (push, stamp, verify, promote), and when it hits something that needs judgment — write a blog, review code, classify commits for squash — it prints one instruction and exits. The LLM reads that instruction, does the work, calls the script again. The script validates the output before continuing.

The key insight: the LLM never sees the step list. It gets one instruction at a time. It can't skip step 7 because it doesn't know step 7 exists. Python decides what's next. Python validates. The 660-line skill becomes a 20-line dispatch loop.

This is the opposite of how Claude Code normally works. The standard model is LLM-as-orchestrator: the skill describes what to do, the LLM does it. Claude Code Workflows offer deterministic orchestration, but they spawn a fresh agent per step — conversation context doesn't carry forward. Review findings can't inform the sweep. User decisions evaporate between steps.

The re-entrant script preserves context because it's one continuous conversation. The LLM calls the same script repeatedly, building up session knowledge across yield points. Forage discoveries are available during protocol capture. Protocol captures inform the diary entry. Nothing is lost.

## The crash-safety accident

While designing the orchestrator, we discovered that the existing progress files — the ones tracking which repos had been pushed, stamped, merged — weren't crash-safe. `Path.write_text()` truncates the file before writing. Process crash between truncation and write: empty file. All prior progress gone.

The design spec called this "append-only." It wasn't. The code read the file into a dict, modified it, and rewrote the entire file. The gap had been there since the scripts were written. The fix was the same pattern `lifecycle.py` already uses: write to `.tmp`, then `os.replace()` — atomic on POSIX.

Finding this while designing the orchestrator was fortunate. If we'd built the orchestrator on top of the same pattern, the crash-safety problem would have propagated into a system that runs more steps, not fewer.

## What the rewrite actually looks like

The old SKILL.md had 662 lines of sequential instructions that the LLM was supposed to follow in order. Context resolution. Preconditions. Dirty tree protocol. Review with four sub-steps and a forcing function. Sweep configuration. Six sweep sub-steps. Trajectory capture. Rebase. Squash analysis. Land. Verify. Close issues. Archive. Checkout main. ARC42 scan. Session rename. Garden feedback. Notes. Close summary. All of it described in prose the LLM was expected to parse, sequence, and execute without missing a beat.

The new one is 425 lines and has three sections. Pre-close context handling stays in the skill — that's interactive work the LLM is good at. The dispatch loop is about 20 lines: call the orchestrator, read the action, handle it, call again. Action handlers tell the LLM the judgment constraints for each action type — what the review forcing function's severity rules are, what the sweep toggle defaults to, how to classify commits for squash. The sequencing and validation live in Python where they can't be skipped.

The close report changed too. The old step names — `merge`, `push-fork`, `stamp-project`, `slot-archive` — reflected the script-level operations that work-end used to coordinate directly. The new names — `promote`, `land`, `close-issues`, `verify` — reflect the orchestrator's higher-level sequence. Eight steps instead of fifteen, because the orchestrator combines what the LLM used to manage as separate calls.

## The question that remains

The architecture is proven in tests — the orchestrator yields the right actions in the right order, handles crash recovery, detects stale progress from prior closes, and escalates after repeated judgment failures. What it hasn't done yet is close a real branch end-to-end. The mechanical steps (promote, rebase, push, stamp) are still stubs that mark themselves done without calling the scripts. The sequencing is correct; the wiring to the actual scripts is the next step.

The harder question is the judgment steps. The orchestrator validates that a blog file exists with reasonable word count. It can't validate that the blog captures the session's narrative well. "File exists" is a mechanical check. "Content is good" is a semantic one. That's where the optional Haiku validation layer might earn its place — a cheap model doing a focused quality check that the heuristics can't provide. Whether that's worth building depends on how the judgment steps perform without it.
