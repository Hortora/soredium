---
layout: post
title: "The Alternate That Nobody Checked"
date: 2026-08-20
entry_type: note
subtype: diary
projects: [soredium]
tags: [slots, git, alternates, stability, audit]
---

After weeks of changes to work-end, workspace layouts, and lifecycle state machines, I wanted to know what we'd broken. The answer: more than expected, less than feared.

## The Audit

I ran a full stability audit across everything — 19 active slots, 48 archived slots, 60 legacy worktrees, 30+ standalone repos, and a dozen workspaces. The reconciliation scripts caught three DB/disk state mismatches immediately. Nine workspace markers were missing and got placed. Twelve pause stacks were all empty (small mercy). Seven legacy `.meta` files were still hanging around on active branches, months after the `.plan` migration.

The interesting finding was in slot 130. Every git operation was failing with `unable to normalize alternate object path` — pointing at a directory that no longer existed. It looked like corruption until I traced it to `objects/info/alternates`.

## How Git Alternates Become Landmines

When `git clone --shared` creates a repo, it writes an absolute path to the source's object store in `.git/objects/info/alternates`. The clone borrows objects from the source rather than copying them — saves time and disk. The problem: that path is written in stone. Move the source directory, and the clone's git breaks on every operation.

Slot 130's `work-work` repo had been cloned from slot 115's `work` repo. When slot 115 was archived — moved from `slots/115/` to `slots/attic/115/` — the path broke. The error message says nothing about the source being moved. It doesn't mention alternates. A developer unfamiliar with this mechanism would investigate corruption, re-clone, or search for missing objects. None of those are the fix.

The fix is `git repack -a -d -l` to internalize all borrowed objects, then delete the alternates file. After that, the repo is self-contained.

## The Systemic Risk

Slot 130 was the only broken one, but there are 188 alternates entries across all active and archived slots. Any future archive operation could create another one. The `archive_slot` function had no awareness of alternates at all — it moved the directory and moved on.

We added `_repack_broken_alternates()` to `slot_manager.py`. Before archiving a slot, it scans all sibling slots for alternates referencing the slot being archived, repacks each affected repo, and removes the stale entry. The slot can then be moved safely.

## The .meta Stragglers

The other fix was for `.meta` files — seven of them still alive on active branches, months after `.plan` became the unified format. Six are git-tracked on active work branches, so I couldn't touch them from outside. We wrote `migrate_meta.py` and wired it into work-start's detection step. Next time anyone opens a session on one of those branches, the `.meta` auto-migrates to `.plan` and gets `git rm`'d. No manual intervention needed.

## What This Tells Me

The slot system has grown into something with real operational surface area — 70+ slots between active and attic, with complex git topologies (shared clones, workspace markers, lifecycle state, cross-slot object sharing) that interact in ways nobody planned for. The alternates problem wasn't a design flaw in archiving — it was a consequence of two independent decisions (shared clones for speed, slot archiving for cleanup) that nobody connected until a repo started failing.

Infrastructure like this needs periodic audits, not just when things break. The reconciliation scripts caught three state mismatches that would have confused the next work-end. The workspace marker scan found nine missing markers that would have broken the new detection path. These are the kind of things that compound silently until they don't.
