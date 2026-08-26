# Duplicate Slot Guard and Partial Failure Cleanup — Design Spec

**Issue:** #291 — Guard against duplicate slot creation and clean up partial failures
**Branch:** issue-291-duplicate-slot-guard
**Date:** 2026-08-26

## Problem

Duplicate slot creation is a recurring pattern (slots 131/133, 158/159, 147):

1. `allocate_slot_number()` reserves a DB number and creates a directory
2. `create_slot()` fails partway through (clone failure, branch collision, workspace error)
3. Broken slot left on disk with partial state — directory exists, `.slot` file absent
4. User retries, allocating a NEW number — broken slot never cleaned up
5. Both coexist: the ghost and the real slot, causing confusion in listing

Additionally, ghost directories (no `.slot` file) from past partial failures show as
"active" in `list_slots` output (e.g. slots 54/67).

## Solution Overview

Four changes to `slot_manager.py` and `reconcile_slots.py`:

1. **Duplicate branch guard** — before allocating a slot number, scan active slots
   for an existing `.slot` with the same branch name. Refuse with a clear message.

2. **Internal rollback on failure** — refactor `create_slot()` error paths from
   `sys.exit(1)` to raised exceptions. Wrap the body in try/except to clean up
   the directory and DB row on failure.

3. **Pending slot reuse** — when allocating, check if the most recent DB entry for
   this family_root is `state='pending'` (abandoned from a prior failed attempt).
   Reuse that number after cleaning up any debris directory.

4. **Ghost quarantine** — enhance `reconcile_slots.py` quarantine flow with
   content-aware triage and `.claude/projects` relocation. Add a defensive
   `.slot`-file check to `list_slots` so ghosts stop appearing immediately.

## Detailed Design

### 1. Duplicate branch guard

A new function `find_slot_by_branch(family_root, branch)` scans active slot
directories and returns `(slot_number, is_landed)` if a `.slot` with a matching
branch exists, or `None` otherwise.

```python
def find_slot_by_branch(family_root: Path, branch: str) -> tuple[int, bool] | None:
    for dir_name in (SLOT_DIR_NAME, LEGACY_SLOT_DIR_NAME):
        slots_dir = family_root / dir_name
        if not slots_dir.exists():
            continue
        for d in sorted(slots_dir.iterdir()):
            if not d.is_dir() or not d.name.isdigit():
                continue
            info = parse_slot_md(d)
            if info.get("branch") == branch:
                landed = (d / ".landed").exists()
                return int(d.name), landed
    return None
```

Called at the top of `create_slot()`, before `allocate_slot_number()`:

```python
result = find_slot_by_branch(family_root, branch)
if result is not None:
    slot_num, landed = result
    if landed:
        raise SlotCreationError(
            f"Slot {slot_num} has branch `{branch}` (landed, not yet archived). "
            f"Archive it first."
        )
    raise SlotCreationError(
        f"Slot {slot_num} already has branch `{branch}`. "
        f"Use that slot or archive it first."
    )
```

**Placement before allocation** prevents wasting a slot number on a duplicate
and avoids interaction with the rollback/reuse paths. The landed/active
distinction gives the user actionable information about what to do next.

### 2. Internal rollback on failure

#### 2a. Replace `sys.exit(1)` with exceptions

Introduce `SlotCreationError(Exception)` in `slot_manager.py`. Replace all
`sys.exit(1)` calls inside `create_slot()` with `raise SlotCreationError(message)`.
The `main()` function catches `SlotCreationError`, prints the error, and calls
`sys.exit(1)` — preserving CLI behavior.

Error paths to refactor (current `sys.exit(1)` sites in `create_slot`):
- Line 605-606: ISX not found
- Line 621-622: repo not found
- Line 629-630: clone failed
- Line 635-636: branch create failed
- Line 654-657: workspace name collision
- Line 665-666: workspace clone failed
- Line 669-670: workspace branch failed
- Line 740-741: wksp validation failed

#### 2b. Try/except wrapper with cleanup

```python
def create_slot(family_root, repos, branch, ...):
    # D3: Guard runs first, before any allocation
    existing = find_slot_by_branch(family_root, branch)
    if existing is not None:
        raise SlotCreationError(...)

    slot_num = allocate_slot_number(family_root)
    slot_dir = slots_dir / str(slot_num)
    confirmed = False

    try:
        slot_dir.mkdir()
        # ... existing creation logic with sys.exit -> raise ...

        # After successful creation:
        conn = _wl.connect()
        try:
            _wl.confirm_slot_create(conn, slot_num, ...)
            confirmed = True
        finally:
            conn.close()

        # Post-confirmation validation
        wksp_failures = validate_slot_wksp(slot_dir)
        if wksp_failures:
            raise SlotCreationError(...)

        return {...}
    except Exception:
        # Cleanup: remove directory if it exists
        if slot_dir.exists():
            shutil.rmtree(str(slot_dir), ignore_errors=True)
        # Cleanup: transition DB row to failed state
        if _wl:
            try:
                conn = _wl.connect()
                _wl.fail_slot(conn, slot_num, str(family_root))
                conn.close()
            except Exception:
                pass  # Best effort — reconcile handles the rest
        raise
```

#### 2c. New worklog functions

`fail_slot` transitions a slot to `state='failed'` regardless of current state.
This preserves the audit trail (event log rows referencing the slot remain
intact) and avoids FK constraint violations — the `events` table references
`slots.id` with no `ON DELETE CASCADE`, so deleting a confirmed slot would
fail. The `failed` state is naturally handled by `reconcile_slots.py` as
another divergence class.

```python
def fail_slot(conn, slot_number, family_root):
    """Transition a slot to failed state. Works for both pending and active slots.
    Preserves audit trail — no deletion. No @safe — errors propagate."""
    family_root = _norm(family_root)
    conn.execute(
        "UPDATE slots SET state='failed' WHERE slot_number=? AND family_root=?",
        (slot_number, family_root),
    )
    conn.commit()
```

### 3. Pending slot reuse

Modify `allocate_slot_number()` to check for reusable pending/failed rows
before allocating a new number:

```python
def allocate_slot_number(family_root: Path) -> int:
    if _wl is None:
        # ... existing hard fail ...
    conn = _wl.connect()
    try:
        reusable = _wl.find_reusable_slot(conn, str(family_root))
        if reusable is not None:
            slot_num, others = reusable
            # Clean up debris directory if it exists
            for dir_name in (SLOT_DIR_NAME, LEGACY_SLOT_DIR_NAME):
                debris = family_root / dir_name / str(slot_num)
                if debris.exists():
                    shutil.rmtree(str(debris), ignore_errors=True)
            # Clean up any older pending/failed slots too
            for other_num in others:
                for dir_name in (SLOT_DIR_NAME, LEGACY_SLOT_DIR_NAME):
                    debris = family_root / dir_name / str(other_num)
                    if debris.exists():
                        shutil.rmtree(str(debris), ignore_errors=True)
                _wl.fail_slot(conn, other_num, str(family_root))
            print(f"REUSED_PENDING={slot_num}")
            return slot_num
        slot_num = _wl.reserve_slot_number(conn, str(family_root))
    finally:
        conn.close()
    return slot_num
```

New worklog function:

```python
def find_reusable_slot(conn, family_root):
    """Find reusable pending/failed slots for a family_root.
    Returns (highest_number, [other_numbers]) or None.
    The highest-numbered pending/failed slot is reused; others are
    transitioned to failed and their debris cleaned up."""
    family_root = _norm(family_root)
    rows = conn.execute(
        "SELECT slot_number FROM slots "
        "WHERE family_root=? AND state IN ('pending', 'failed') "
        "ORDER BY slot_number DESC",
        (family_root,),
    ).fetchall()
    if not rows:
        return None
    highest = rows[0][0]
    others = [r[0] for r in rows[1:]]
    return highest, others
```

### 4. Ghost quarantine enhancements

#### 4a. Defensive check in `list_slots`

Add to `list_slots()`, inside the active-slot iteration loop, after the
`if not d.is_dir() or not d.name.isdigit()` check:

```python
if not (d / ".slot").exists():
    continue
```

This immediately stops ghost directories from appearing as "active" in
listings, regardless of reconcile cadence.

#### 4b. Enhanced reconcile quarantine

The existing `reconcile_slots.py` already detects ghosts and proposes
quarantine. Enhance with:

**Strategy phase** — before proposing quarantine, check for meaningful content:
- Scan repos in the directory for commits ahead of main
- Query worklog DB for any slot_number record
- Report findings: "Ghost slot 54: empty, no DB record" vs
  "Ghost slot 67: has repos with 3 commits ahead of main, DB shows pending"

**Execute phase** — when quarantining:
- Move to `slots/quarantine/N/` (existing behavior)
- Relocate `.claude/projects` conversations using the same pattern as
  `archive_slot`'s `relocate_claude_projects()`

**No new DB state** — quarantine status is derived from the `quarantine/`
directory location, consistent with the unified-work-state principle of
deriving state from disk reality rather than caching it.

## Assumption

**Concurrent slot creation is not supported.** Two sessions running
`create-slot` simultaneously for the same family_root is undefined behavior.
This is a single-user CLI tool. Guards protect against sequential retry
(the common failure mode), not concurrent execution.

## Test Plan

Per the `externalised-scripts-require-tests` protocol, all new functions
ship with pytest tests in the same commit.

### slot_manager tests

- `test_find_slot_by_branch_finds_match` — create a slot with `.slot` file, verify detection
- `test_find_slot_by_branch_returns_landed_flag` — slot with `.landed` marker → `(num, True)`
- `test_find_slot_by_branch_no_match` — verify None return when branch doesn't exist
- `test_find_slot_by_branch_ignores_attic` — archived slot with same branch doesn't match
- `test_create_slot_duplicate_branch_raises` — create slot, try same branch again → `SlotCreationError`
- `test_create_slot_duplicate_landed_branch_message` — landed slot → different error message mentioning "archive it first"
- `test_create_slot_clone_failure_cleans_up_dir` — simulate clone failure, verify directory removed
- `test_create_slot_clone_failure_transitions_db_to_failed` — simulate clone failure, verify DB state is `failed`
- `test_create_slot_post_confirm_failure_transitions_to_failed` — fail after `confirm_slot_create`, verify DB state is `failed` (not deleted — events FK preserved)
- `test_allocate_reuses_pending` — create pending row, allocate again → same number returned, `REUSED_PENDING` emitted
- `test_allocate_reuses_failed` — create failed row, allocate again → same number returned
- `test_allocate_reuses_pending_cleans_debris` — create pending + directory, verify directory removed on reuse
- `test_allocate_cleans_older_pending_slots` — two pending rows, reuse highest, transition older to failed
- `test_allocate_fresh_when_no_pending` — no pending/failed rows → new number allocated

### worklog tests

- `test_find_reusable_slot_returns_highest_pending`
- `test_find_reusable_slot_returns_all_pending_as_others`
- `test_find_reusable_slot_returns_none_when_no_pending`
- `test_fail_slot_transitions_pending_to_failed`
- `test_fail_slot_transitions_active_to_failed`
- `test_fail_slot_preserves_events` — verify events rows still reference the slot after transition

### reconcile tests

- `test_quarantine_checks_content` — ghost with commits ahead of main → reported in strategy
- `test_quarantine_relocates_claude_projects` — verify `.claude/projects` moved with directory

### list_slots tests

- `test_list_slots_skips_ghost_directories` — directory with no `.slot` → not in results

## References

- `work-slot/slot_manager.py` — primary implementation target
- `~/.claude/lib/worklog.py` — DB layer for slot lifecycle
- `scripts/reconcile_slots.py` — existing quarantine flow to enhance
- `docs/specs/issue-195-slot-db-disk-integrity/2026-08-13-slot-db-disk-integrity-design.md` — DB-authoritative numbering foundation
- `docs/specs/2026-08-06-unified-work-state-design.md` — derive state from disk, don't cache
- `docs/protocols/externalised-scripts-require-tests.md` — tests required in same commit
- Issue #291 — problem statement and test cases
- GE-20260810-8f1daa — cross-org workspace wiring failures (related failure mode)
- GE-20260816-2dddda — ctx.py topology resolution at slot root
