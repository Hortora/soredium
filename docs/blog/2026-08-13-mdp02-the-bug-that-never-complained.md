---
layout: post
title: "The Bug That Never Complained"
date: 2026-08-13
entry_type: note
subtype: diary
projects: [soredium]
tags: [slots, integrity, silent-failure, path-encoding]
---

The conversation relocation code had been broken since slots launched. Every time a slot was archived, its Claude Code session directories — the per-project memory and transcripts — were supposed to move from the active path to the attic path. They never did. No error, no warning, no indication anything went wrong. Twelve archived slots had orphaned conversations sitting at paths that no longer existed on disk.

The root cause was a mismatch between how paths were passed and how they were encoded. Claude Code stores project data in directories named by replacing `/` with `-` in the absolute CWD path: `/Users/x/slots/101/engine` becomes `-Users-x-slots-101-engine`. The relocation function encoded the slot path the same way to find matching directories. But when the script was invoked with a relative family root — `python3 slot_manager.py remove-slot . slot=101` — the slot path resolved to `slots/101`, which encoded as `slots-101`. That never matches `-Users-x-slots-101-engine`. Zero matches, zero moves, zero complaints.

The fix was `.resolve()` before encoding — two lines. But the bug exposed a deeper problem.

Slot numbering was derived from scanning disk directories for the maximum number. Ghost remnant directories — empty leftovers from prior eras with no `.slot` file — inflated the scan. When those ghosts became invisible to a fresh scan (different CWD, different session), the counter reset and reused numbers already occupied in the attic. Twenty-four casehub slots existed simultaneously in both `slots/N/` and `slots/attic/N/`. No work was lost — every ghost was just an empty directory or a stale `.m2` — but the bookkeeping was fiction.

The fix here was making the worklog DB authoritative for numbering instead of scanning disk. `allocate_slot_number()` now queries `MAX(slot_number) + 1` from SQLite and hard-fails if the DB is unavailable. No fallback to disk scan — the fallback is what caused the collisions.

The decision review caught something I hadn't thought through: you can't have authoritative reads without authoritative writes. The worklog wraps every recording function in a `@safe` decorator that silently swallows exceptions. If `record_slot_create()` fails silently, the next `MAX(slot_number)` query sees stale state and allocates a duplicate — the exact collision the fix was supposed to prevent. The reserve-first pattern solves this: insert a `pending` row before creating any directory, then confirm to `active` after disk operations succeed. The number is reserved the moment it's allocated, even if everything after that crashes.

`list_slots` now cross-references disk state against the DB on every call and emits drift warnings inline. The reconciliation script was rewritten as a three-phase tool — audit, strategy, execute — with quarantine instead of deletion, because twenty-four collisions deserve careful inspection before anything moves.

The thing that made this session interesting wasn't the fix. It was how invisible the damage was. Twelve slots archived without their conversations. Twenty-four number collisions with no error. Every function returned success. The only way to find the problem was to count what should have been there and notice it wasn't.
