---
layout: post
title: "The Two-Hop Push Problem"
date: 2026-08-10
entry_type: note
subtype: diary
projects: [soredium]
tags: [git, slots, propagation, updateInstead]
---

## The Two-Hop Push Problem

Slots are `git clone --shared` copies of local repos. They're fast, isolated, zero-cost. The problem is getting work back out.

When a slot finishes, its changes need to reach two places: the original local repo (so the next session sees them) and GitHub (so they're durable and team-visible). The slot's `origin` points to the original repo — a non-bare repo with `main` checked out. Git refuses to push to a checked-out branch. The work sits in the slot clone, invisible to everything else.

This has happened repeatedly. The project repo would lose all floating-workspace commits after work-end completed. The workspace repo would diverge, requiring manual merge commits. Blog entries would publish to their destination but spec and plan artifacts would be invisible to other sessions because the workspace origin never received them.

## Why Both Failure Paths Were Invisible

Two independent mechanisms produce the same symptom — the original falls behind — and neither one errors loudly enough to notice.

The first is artifact promotion. `to-workspace-main` checks out main in the slot workspace, commits the promoted artifacts, and calls `git push`. That push goes to the original workspace repo, which has main checked out. Rejected. The error is caught as `PUSHED=failed` — non-fatal, workflow continues. Artifacts exist in the slot but never reach the original.

The second is the land step itself. `merge_slot()` iterates project repos only. Workspace directories (named `work-*`) are filtered out by `is_project_repo()`. They get stamped with "branch closed" commits but are never merged to their originals' main, never pushed to GitHub.

## The Fix Went Through Three Iterations

The initial design pushed directly from the slot to GitHub, bypassing the original entirely. Claude proposed `receive.denyCurrentBranch=updateInstead` on the originals plus a fallback pull when the push failed.

I pushed back: if the slot can push directly to GitHub, why touch the original at all? The local repo syncs lazily at next session start. Claude agreed and redesigned around a GitHub-direct approach with `origin` reconfigured to point at the fork on GitHub.

But that introduced a sync gap. The original repo wouldn't have the work until someone fetched. If the original is on a feature branch, you can't pull into its main without checking it out. We went in circles until the key insight landed: `updateInstead` handles the case where main IS checked out, and pushing to a non-checked-out branch works by default in git. Between the two, the local original's main is always updated regardless of which branch it has checked out.

The final design chains everything through the original: slot pushes to the original (via `updateInstead`), then the original pushes to GitHub (standard `git push origin main`). The slot never talks to GitHub for writes — `origin` on the slot is fetch-only. A preflight step syncs each original with GitHub before the slot touches anything, auto-pushing unpushed commits and auto-fast-forwarding stale mains.

## What `updateInstead` Actually Does

The name is cryptic enough that it's worth spelling out. When a non-bare repo receives a push to its currently checked-out branch, git normally rejects it — the working tree would become inconsistent with the ref. `receive.denyCurrentBranch=updateInstead` tells git to accept the push and atomically update the ref, index, and working tree together. It refuses if the working tree has uncommitted changes, which is the safety gate.

The non-obvious part: this config only matters when the pushed branch IS the checked-out branch. For branches that aren't checked out, the push updates the ref silently — standard git behavior, no config needed. So setting `updateInstead` on a repo means any branch can be pushed to, regardless of what's checked out. The two mechanisms cover every state.

## What Opens Up

The preflight sync step is the part I didn't initially plan but that matters most. Before the slot does anything, it ensures every original is consistent with GitHub — pushing unpushed commits, fast-forwarding stale mains, hard-stopping on divergence. This eliminates an entire class of "why is my repo behind" problems that have nothing to do with slots.
