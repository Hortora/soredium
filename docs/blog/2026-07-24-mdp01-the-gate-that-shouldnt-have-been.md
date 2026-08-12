---
layout: post
title: "The Gate That Shouldn't Have Been"
date: 2026-07-24
type: phase-update
entry_type: note
subtype: diary
projects: [soredium]
tags: [work-end, lifecycle, graceful-degradation]
---

# soredium — The Gate That Shouldn't Have Been

**Date:** 2026-07-24
**Type:** phase-update

---

## What I was trying to achieve: making work-end survivable without its scaffold

work-end has a hard gate at pre-condition 2: if `design/.meta` doesn't exist, the entire close operation stops dead. This made sense when `.meta` was guaranteed — work-start creates it, every branch has one. But branches created manually, branches from before the scaffold system, branches where someone accidentally deleted the file — all of them hit a wall. The fix needed to close on two issues: #87 (graceful degradation) and #88 (slot-mode per-repo sweep for multi-repo worktrees).

## What we believed going in

That `.meta` was load-bearing — that work-end's downstream steps genuinely needed it. The design review proved otherwise. `close_artifacts.py` doesn't read `.meta` at all; it takes everything as CLI arguments. `ctx.py` already handles missing `.meta` gracefully, defaulting to empty strings. The hard gate was protecting nothing. Every value work-end needs can be reconstructed from what's already available: the branch name, the GitHub API, and sensible defaults.

## ctx.py already knew the answer

The reconstruction didn't need a new script or a separate code path. ctx.py already parses the branch name, already reads CLAUDE.md for the GitHub repo, already defaults missing fields to empty. We added one output — `INFERRED_ISSUE` — that parses `issue-(\d+)` from the branch name when `.meta` is absent. Five lines of Python, five tests, and the deterministic part of the reconstruction lives where it belongs: in the context resolver that every lifecycle skill already trusts.

The interactive part — confirming with the user, creating an issue if none exists — stays in the skill instructions. That split matters. ctx.py is mechanical and testable. The skill instructions handle the human conversation. Mixing them would have been the wrong abstraction.

## The review caught what the spec missed

The adversarial design review raised 18 issues across 3 rounds. Most were refinements, but two were genuine gaps. First: Step 3 in work-end re-reads `.meta` directly with a grep command, bypassing ctx.py's output entirely. A second read path that contradicts the "all values from ctx.py" contract — and one that fails silently when `.meta` is absent. We removed it.

Second: Phase B in slot mode calls `close_artifacts.py` after merging the slot workspace to main. At that point the original workspace is on main — the branch artifacts are gone. Without passing `scan-workspace` pointing at the slot workspace, Phase B would scan an empty directory and promote nothing. The spec had designed the parameter but hadn't wired it into the Phase B flow.

## The slot sweep is a loop in markdown, not in Python

For #88, the per-repo sweep in slot mode could have gone into `close_artifacts.py` as a `--repos` flag. We kept it in the skill instructions instead. The script stays composable — one workspace pair per call, slot-agnostic. The loop that iterates over repos lives in the SKILL.md where the LLM reads it. This is consistent with how work-end already works: the script handles mechanics, the skill handles orchestration.

The sweep order matters: protocol first (captures rules), then update-claude-md (syncs conventions including new protocols), then implementation-doc-sync (syncs docs using up-to-date CLAUDE.md). Session-bound items — forage, adr, write-content — run once against the primary workspace, not per-repo.

---

The interesting thing about this work is what it reveals about `.meta`'s actual role. It's not a runtime dependency — it's a creation-time record. What branch, what issue, what routing decisions were made at the moment of creation. When it's absent, almost everything can be reconstructed from the current state. The things that can't — multi-issue COVERS, workspace-vs-project design routing — are the things that genuinely belong in a creation-time record. The hard gate was treating a convenience as a necessity.
