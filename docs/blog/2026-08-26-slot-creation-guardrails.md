---
title: "The slot that wouldn't die"
date: 2026-08-26
entry_type: note
subtype: diary
projects: [Hortora/soredium]
series: soredium-lifecycle
author: mdp
tags: [slots, error-handling, state-machines, sqlite]
---

# The slot that wouldn't die

Slot creation has a recurring failure pattern: something goes wrong mid-creation — a clone fails, a workspace collides, a branch already exists — and the half-built slot stays on disk. The user retries. A new number gets allocated. Now there are two: a ghost and a real slot, both visible in `list-slots`, one of them empty. Slots 131/133, 158/159, and 147 all followed this exact script.

The fix has four parts, and the interesting one isn't the guard.

## The guard is boring (and that's the point)

Duplicate branch detection scans `.slot` files in active slot directories before allocating a number. If a slot already owns the branch you're asking for, it refuses with a message that tells you what to do next. If the existing slot is landed but not yet archived, the message says so — "archive it first" is more useful than "something's in the way" when the user doesn't know what state the old slot is in.

This runs before `allocate_slot_number`, so no DB row gets wasted on a duplicate that would be rejected anyway. The scan uses `parse_slot_md`, the existing parser — no custom header parsing, no DB queries, no new infrastructure.

## The rollback is where it got interesting

`create_slot` had eight `sys.exit(1)` calls scattered through its body. Each one represented a failure point where the function bailed, leaving behind a directory and a `pending` DB row. The refactoring replaced all eight with `raise SlotCreationError(message)`, wrapped the body in try/except, and added cleanup: remove the directory, transition the DB to `state='failed'`.

The original plan was to delete the DB row on failure. Claude's design reviewer caught why that won't work: `confirm_slot_create` logs an event (`_log_event`) that inserts a row into `events` referencing `slots.id`. SQLite enforces `PRAGMA foreign_keys=ON` with no `ON DELETE CASCADE` on that reference. So `DELETE FROM slots WHERE id=?` raises `IntegrityError` — and the rollback handler's `except Exception: pass` would have silently swallowed it. The directory gets cleaned up, the DB row survives as `active`, and you get db/disk drift that only reconciliation catches.

The fix is a state transition: `fail_slot` sets `state='failed'` instead of deleting the row. The audit trail stays intact, the FK is never violated, and `reconcile_slots.py` treats `failed` as another divergence class it knows how to handle.

## Reuse, not waste

When `allocate_slot_number` finds a pending or failed row for the family root, it reuses that number instead of allocating a new one. The debris directory from the old attempt gets cleaned up first. If multiple abandoned rows exist — two consecutive failed creations, for instance — the highest number is reused and the rest transition to `failed`. A `REUSED_PENDING=N` line in the output makes the reuse visible.

## Ghost quarantine

The existing slots that showed as "active" with no `.slot` file (54/67 in the real data) are ghost directories — debris from past failures that predated the rollback. `list_slots` now skips directories without `.slot`, so they stop appearing immediately. For cleanup, `reconcile_slots.py`'s quarantine flow was enhanced: the strategy phase now reports what's actually in a ghost directory (repos with commits ahead of main, worklog DB records) before proposing quarantine, and the execute phase relocates `.claude/projects` conversations alongside the directory — so session history travels with the slot.

## What this opens up

The `sys.exit` → exception refactoring changes `create_slot` from a CLI-exit function to a library function. Callers can now catch `SlotCreationError` and make their own decisions — retry, present a menu, chain to a different operation. The SKILL.md's `main()` catches at the boundary and exits, preserving CLI behavior. But anything that calls `create_slot` programmatically — the TUI, a future API, the orchestrator — gets proper error propagation instead of process death.

The `failed` state also gives reconciliation a new signal. A slot that went from `pending` to `failed` tells you exactly what happened — someone tried to create it, and it broke. That's more information than a ghost directory with no context, and it persists in the audit log even after the directory is cleaned up.
