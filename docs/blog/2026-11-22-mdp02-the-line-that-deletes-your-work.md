---
layout: post
title: "The Line That Deletes Your Work"
date: 2026-11-22
entry_type: note
subtype: diary
projects: [soredium]
tags: [lifecycle, slots, data-loss, safety-guards]
series: lifecycle-hardening
---

# The Line That Deletes Your Work

Continues [The Ceremony That Lied](2026-11-22-mdp01-the-ceremony-that-lied.md).

Slot 227 had nine commits of implementation work and a full set of workspace artifacts — specs, decisions, plans. A session in a different slot asked to create a new slot. The allocator assigned number 227. `shutil.rmtree` deleted the directory. `ignore_errors=True` meant it didn't even complain.

The engine branch survived because branches live in `.git`, not the working tree. The workspace artifacts — the ones that only existed in the slot's clone — are gone.

## How the allocator betrayed itself

`allocate_slot_number` has two paths. The primary path calls `find_reusable_slot`, which queries the worklog DB for slots in `pending` or `failed` state. If the DB says a slot is pending, the allocator takes the number and `rmtree`s the directory to clean up "debris." The secondary path takes `MAX(slot_number) + 1` from the DB.

Both paths trust the DB completely. Neither checks disk.

The DB said slot 227 was pending. On disk, slot 227 had a git repo with nine commits, a workspace clone with artifacts, and a `.slot` file marking it active. The allocator didn't look. It took the number, deleted the directory, and handed the number to `create_slot` for reuse.

The likely cause: the creating session resolved `worklog.py` from a different location, connecting to a different DB where slot 227's creation was never confirmed. Two DBs, two truths. The disk — the actual source of truth — was never consulted.

## The fix is boring and that's the point

Three guards, each independent, each sufficient on its own:

**`_slot_dir_has_content`** checks whether a slot directory contains anything beyond creation debris (`.m2`, `.mvn`, Maven wrapper files). A slot with only those artifacts is genuine debris from a failed `create_slot` — safe to remove. A slot with git repos, workspace clones, or any other content is occupied. The allocator checks this before reusing any number and falls back to `reserve_slot_number` if the directory is occupied.

**`_safe_remove_debris`** replaces every bare `shutil.rmtree` call. It refuses to delete any directory that has content. The allocator cleaned up "other" reusable slots too — if the DB listed three pending slots, the allocator would reuse the highest and `rmtree` the rest. Each of those directories now gets the same content check.

**`create_slot` itself** checks after allocation. Even if `allocate_slot_number` returns a colliding number — different DB, concurrent session, whatever — `create_slot` sees the directory exists and raises `SlotCreationError` instead of proceeding.

The guards are layered. The allocator skips occupied numbers. If it doesn't, `create_slot` catches the collision. `rmtree` is never called on anything with content. Any one of these prevents the data loss. All three together mean the failure mode is closed regardless of which path the allocation takes.

## What this says about DB-authoritative numbering

The worklog DB is useful for coordination but it is not the source of truth for what exists on disk. Disk is. A DB row saying `state='pending'` is a claim. A directory containing nine commits and a `.slot` file is a fact. When the claim and the fact disagree, the fact wins.

The original code treated the DB as authoritative and disk as disposable. The fix inverts this: disk state is checked first, DB state is used for allocation hints, and no destructive operation proceeds without verifying disk.
