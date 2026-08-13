# Slot DB/Disk Integrity — Design Spec

**Issue:** #195 — Slot numbering and DB/disk integrity
**Branch:** issue-195-slot-db-disk-integrity
**Date:** 2026-08-13

## Problem

Slot numbering is derived from disk scans (`allocate_slot_number()` reads
`slots/` and `slots/attic/` for `max + 1`). This has caused:

- **Numbering collisions:** 24 casehub slots exist in both `slots/N/` and
  `slots/attic/N/` — ghost remnant directories at the active path inflated
  the disk scan, then when those ghosts became invisible to a fresh scan,
  the counter reset and reused numbers already in the attic.
- **DB/disk state drift:** DB says active but disk is in attic (and vice
  versa). Gaps in the DB sequence (slots 52, 58, 66 never recorded).
- **Silent write failures:** `@safe` decorator on `record_slot_create()`
  swallows DB write errors, so the worklog silently misses slot creations.

No work has been lost — the ghost directories contain no `.slot` files and
the attic copies have the real data. But the bookkeeping is unreliable.

## Solution Overview

Four changes:

1. **DB-authoritative numbering with reserve-first** —
   `allocate_slot_number()` inserts a DB row with `state='pending'`
   before creating any directory. The number is reserved immediately.
   Hard fail if the DB is unavailable (D3).

2. **Authoritative writes for slot creation** — the entire slot creation
   DB write path (including `ensure_repo()`) runs in a single transaction.
   If any part fails, the transaction rolls back and slot creation fails.
   Other worklog functions remain informational/best-effort (D4).

3. **Inline drift detection on list** — `list_slots()` cross-references
   disk state against DB state and emits `WARN=db_drift` lines for
   mismatches. Zero-cost since list already iterates all slots.

4. **Repeatable reconciliation** — rewritten `reconcile_slots.py` with
   three phases: audit (report with taxonomy), strategy (propose actions),
   execute (apply approved actions with quarantine).

Plus the already-implemented fix from this session: `relocate_claude_projects()`
and `remove_claude_projects()` now resolve paths to absolute before encoding,
fixing the bug where conversation directories silently failed to move during
archival when the script was invoked with a relative family root.

## Detailed Design

### 1. `allocate_slot_number()` — reserve-first pattern

The current disk-scan approach is replaced with a DB reservation that
atomically allocates and persists the number. This prevents the failure
mode where directory creation succeeds but the DB write fails, leaving
a dead-end where the number can't be reused.

```python
def allocate_slot_number(family_root: Path) -> int:
    if _wl is None:
        print("ERROR=worklog_unavailable")
        print("ERROR_DETAIL=worklog module required for slot numbering")
        sys.exit(1)
    conn = _wl.connect()
    slot_num = _wl.reserve_slot_number(conn, str(family_root))
    conn.close()
    return slot_num
```

In `worklog.py`, a new `reserve_slot_number()` function:

```python
def reserve_slot_number(conn: Connection, family_root: str) -> int:
    family_root = _norm(family_root)
    row = conn.execute(
        "SELECT MAX(slot_number) FROM slots WHERE family_root=?",
        (family_root,),
    ).fetchone()
    next_num = (row[0] or 0) + 1
    conn.execute(
        "INSERT INTO slots (slot_number, family_root, state, created_at) "
        "VALUES (?, ?, 'pending', ?)",
        (next_num, family_root, _now()),
    )
    conn.commit()
    return next_num
```

No `@safe` — errors propagate. The slot row exists in the DB the moment
the number is allocated, so even if directory creation fails downstream,
the number is never reused.

`create_slot()` then confirms the reservation after all disk operations
succeed by updating the state from `pending` to `active`.

### 2. Authoritative writes for slot creation

The full `create_slot()` flow becomes:

1. `allocate_slot_number()` → reserves number in DB (state='pending')
2. Create directory, clone repos, set up infrastructure
3. Write `.slot` file
4. Confirm slot in DB (state='pending' → 'active', write work_items)

Step 4 runs in a single transaction with no `@safe`:

```python
def confirm_slot_create(conn: Connection, slot_number: int,
                        family_root: str, repos: list[str],
                        branch: str, issue_number: int,
                        issue_repo: str,
                        covers: str | None = None) -> int:
    family_root = _norm(family_root)
    sid = _find_slot(conn, slot_number, family_root)
    if sid is None:
        raise ValueError(f"No pending slot {slot_number} for {family_root}")
    conn.execute(
        "UPDATE slots SET state='active' WHERE id=?", (sid,))
    # Insert work_items and issue linkages in same transaction
    for repo_path in repos:
        repo_id = _ensure_repo_strict(conn, repo_path,
                                       family_root=family_root)
        wi_cur = conn.execute(
            "INSERT INTO work_items (...) VALUES (...)",
            (branch, repo_id, 'active', 'slot', sid, _now()),
        )
        # ... issue linkages
    _log_event(conn, "slot-create", slot_id=sid, ...)
    conn.commit()
    return sid
```

`_ensure_repo_strict()` is the non-`@safe` variant of `ensure_repo()`,
used only in the slot creation critical path. The original `ensure_repo()`
keeps `@safe` for all other callers.

If step 4 fails, the slot directory exists on disk but the DB row stays
`state='pending'`. The drift detection in `list_slots()` catches this
(disk has a real slot, DB says pending), and `reconcile_slots.py` can
either confirm it (set to active) or clean it up.

### 3. Inline drift detection on `list_slots()`

After building the slot list from disk, query the DB:
```python
if _wl:
    conn = _wl.connect()
    db_slots = _wl.slot_status(conn, family_root=str(family_root))
    conn.close()
    # Compare and emit warnings
```

Divergence types detected (from D2 taxonomy):

| Type | Condition | Warning |
|------|-----------|---------|
| `db-only` | DB record (non-pending), no disk directory | `WARN=db_drift type=db-only slot=N` |
| `disk-only` | Disk directory, no DB record | `WARN=db_drift type=disk-only slot=N` |
| `state-mismatch` | DB state != disk state | `WARN=db_drift type=state-mismatch slot=N db=X disk=Y` |
| `ghost` | Dir with no `.slot` file | `WARN=db_drift type=ghost slot=N` |
| `pending` | DB says pending, disk has real slot | `WARN=db_drift type=pending slot=N` |

Drift detection is non-blocking — warnings only, never errors. The user
runs `reconcile_slots.py` to fix detected drift.

### 4. Repeatable reconciliation (`reconcile_slots.py`)

Rewrite the existing script with three explicit phases.

**Phase 1 — Audit:**

Scan all four disk locations (`slots/`, `slots/attic/`, `worktrees/`,
`worktrees/attic/`) and the DB. For each slot number, report:

```
SLOT 3 (casehub):
  disk:  slots/3/ — NO .slot file, contains: [aml/]
  disk:  slots/attic/3/ — .slot=yes .landed=no
  db:    state=archived, created=2026-08-03, archived=2026-08-04
  class: ghost (active dir has no .slot, attic has real data)
```

Classify each divergence per the taxonomy in D2.

**Phase 2 — Strategy:**

For each divergence, propose an action:

| Class | Proposed action |
|-------|-----------------|
| `ghost` | Quarantine to `slots/quarantine/N/` |
| `db-only` | Remove DB record (slot doesn't exist on disk) |
| `disk-only` | Backfill DB record from `.slot` file metadata |
| `state-mismatch` | Update DB state to match disk reality |
| `collision` | If both have `.slot`: renumber the active one (allocate new number from DB). If only attic has `.slot`: treat active as ghost |
| `pending` | Confirm to active (if disk has real slot) or remove (if no disk dir) |

Present the full plan and wait for user approval.

**Phase 3 — Execute:**

Apply approved actions. Log each action. Ghost directories go to
`slots/quarantine/N/` (not deleted) so they can be inspected or
recovered.

**Quarantine is excluded from all automation.** `allocate_slot_number()`,
`list_slots()`, `_resolve_slot_dir_for_number()`, and `scan_ready()` do
not scan the quarantine directory. It exists solely for manual inspection
and recovery. Quarantined slots have no DB record.

### 5. Already implemented: path resolution fix

`relocate_claude_projects()` and `remove_claude_projects()` now call
`.resolve()` on `slot_dir` and `dest_dir` before encoding to match
Claude Code's absolute-path-based project directory names. This fixes
the bug where conversations silently failed to move during archival.

Regression tests added in `TestRelocateClaudeProjectsRelativePath`.

## Follow-up scope (not in this issue)

- **`add_repo()` DB tracking:** `add_repo()` adds repos to existing
  slots without any DB write. The DB picture of slot repo membership
  can drift after add_repo calls. Needs a `record_slot_add_repo()`
  function. (R1-03)
- **Archive/merge write failures:** `record_slot_archive` and
  `record_slot_merge` use `@safe`. Silent failures produce state
  drift that the inline drift detection catches and reconcile fixes.
  Making these authoritative too would eliminate that drift source
  but is a larger contract change. (R1-04)
- **Archive atomicity:** The archive path does disk move then DB
  write. If the DB write fails, the disk state is correct but the
  DB lags. Drift detection catches this. Full atomicity would
  require a reserve-confirm pattern similar to slot creation. (R1-05)

## Files Changed

| File | Change |
|------|--------|
| `work-slot/slot_manager.py` | `allocate_slot_number()` → DB reserve; `create_slot()` → reserve-first + confirm; `list_slots()` → inline drift check; `relocate_claude_projects()` / `remove_claude_projects()` → `.resolve()` (done) |
| `scripts/worklog.py` | Add `reserve_slot_number()`, `confirm_slot_create()`, `_ensure_repo_strict()`; `pending` state for slots |
| `scripts/reconcile_slots.py` | Three-phase audit/strategy/execute with taxonomy, quarantine |
| `tests/test_slot_manager.py` | Tests for DB-authoritative numbering, reserve-first, hard fail, drift detection, path resolution (partially done) |
| `tests/test_reconcile_slots.py` | Tests for enhanced reconciliation phases |

## Testing Strategy

- **`allocate_slot_number()`**: test DB reserve returns max+1 and
  inserts pending row; test hard fail when `_wl` is None; test hard
  fail when DB connection fails
- **`create_slot()`**: test reserve-first then confirm flow; test
  that DB write failure after directory creation leaves pending row
  (not reused); test that pending row is confirmed to active on success
- **`list_slots()` drift detection**: test each divergence type emits
  correct warning; test no warnings when aligned; test pending state
  detection
- **`reconcile_slots.py`**: test audit output for each divergence class;
  test quarantine rather than delete; test DB backfill from disk;
  test pending row handling
- **Path resolution**: done — `TestRelocateClaudeProjectsRelativePath`

## Acceptance Criteria (from #195)

- [x] Slot numbering uses DB as authority, not disk scan
- [ ] Archive operation updates DB and disk (drift detection catches failures)
- [ ] `work-slot list` flags DB/disk divergences when detected
- [ ] No gaps in slot numbering for new slots going forward
- [ ] Existing divergences documented (reconciliation audit)
