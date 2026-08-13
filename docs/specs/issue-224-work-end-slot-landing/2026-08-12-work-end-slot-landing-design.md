# Work-End Slot Landing — Design Spec

**Issue:** Hortora/soredium#224, #225
**Branch:** issue-224-work-end-slot-landing
**Date:** 2026-08-12

## Problem

Six observed failures when work-end runs inside a slot (IN_SLOT=yes) all
trace to one root cause: **the slot landing path described in SKILL.md
was never wired up.** `merge-slot` requires a `.phase-a-complete` marker
that work-end never writes. Each failure cascades into the next.

### Failure chain (observed in slot 113)

1. `close_artifacts.py` push fails — slot clone branch has no upstream
2. Squash proceeds but no `.phase-a-complete` marker written
3. `merge-slot` returns `not_ready` — marker missing
4. No `.landed` marker — merge-slot never ran
5. Archive blocked — `.landed` required for safety check
6. Original repos never synced — two-hop push never executed

### Root cause

The SKILL.md describes the correct slot mode flow (call `merge-slot` in
Phase C). The implementation never completes it because nothing writes
the `.phase-a-complete` marker that `merge-slot` requires.

---

## Fix Chain

Each fix enables the next. The total code change is small — one SKILL.md
instruction and verification script extensions.

### 1. Promotion push — no change needed

`close_artifacts.py` push works via `updateInstead` (configured during
slot creation by `configure_update_instead()` in `create_slot()`).
Pushes to `local` remote land on the original repo's checked-out main
immediately. Blog push operates independently to its own repo. merge-slot's
subsequent push for these repos becomes a verified no-op.

### 2. Write `.phase-a-complete` marker

After Phase B (squash) completes, a script function writes the marker
to the slot root (parent of the project clone):

```bash
python3 work-end/work_end_execute.py write-marker slot_path=<SLOT_PATH> branch=<BRANCH>
```

New `cmd_write_marker()` function in `work_end_execute.py`. Writes:
```
branch=<branch-name>
timestamp=<ISO-8601>
```

Three consumers: `merge_slot()` reads `branch=`, `scan_ready()` reads
`timestamp=`, `list_slots()` reads presence for status display.

Script function (not LLM instruction) for testability, determinism,
and alignment with the restructure spec direction.

### 3. `merge-slot` call in Phase C

SKILL.md Step 3.5 already says slot mode calls:
```bash
python3 work-slot/slot_manager.py merge-slot <SLOT_PATH>
```

With the marker present (step 2), `merge_slot()` handles the full
landing: rebase retry (no-op since work-end already rebased), two-hop
push (clone → original → GitHub), SHA verification, `.landed` marker
with audit trail, branch stamps on all repos (project + workspace).

### 4. Archive offer in Step 5.1

SKILL.md Step 5.1 already documents the archive prompt:
```
Slot <N> (<branch-name>) landed and verified.
Archive to slots/attic/<N>/? (y/n)
```

With `.landed` present from step 3, `archive-slot` proceeds without
`--force`. The SKILL.md flow is already correct — it just wasn't
reachable before.

### 5. Verification extensions

Extend `verify_slot_close.py` with slot-specific landing checks:

- **Original repo sync:** For each repo in `.slot`, verify original
  repo's main SHA matches the slot clone's landed SHA
- **`.landed` marker:** Verify it exists and contains valid `landed_shas=`
- **Archive status:** Report whether slot is archived, landed-but-active,
  or active

---

## Cross-Module Close Sequence

work-end owns Phases A+B (rebase + squash + promotion). `merge_slot()`
owns Phase C (landing). The modules are coupled through the
`.phase-a-complete` marker file.

This split is accepted for issue #224 (a bug fix). The work-end
restructure spec (`2026-08-05-work-end-restructure-and-slot-audit-design.md`)
plans a unified close sequence as a separate deliverable.

`merge_slot()` must continue to work standalone for async landing — the
`work-slot merge` use case (landing from the main repo after the slot
session ends) requires it regardless of the unified approach.

---

## SKILL.md Changes

### `work-end/SKILL.md`

**Step 3.4 (Phase B — Squash):** Add after squash plan is applied:
```
After squash completes for all repos, if IN_SLOT=yes, write the
.phase-a-complete marker:

    python3 work-end/work_end_execute.py write-marker slot_path=<SLOT_PATH> branch=<BRANCH>

This enables merge-slot in Phase C.
```

**Step 3.5 (Phase C — Land):** Clarify slot mode path. The existing
text already says to call `merge-slot`. Ensure it's unambiguous that
this replaces `cmd_land()`, not supplements it.

**Step 5.1 (Archive):** No change — already documented correctly. Flow
now reaches it because landing succeeds.

---

## Testing

| Change | Tests |
|--------|-------|
| `work_end_execute.py cmd_write_marker()` | Happy path (writes marker with correct fields), missing slot_path, missing branch |
| `verify_slot_close.py` — original sync check | Original SHA matches landed SHA, original SHA mismatches |
| `verify_slot_close.py` — .landed check | Present with valid SHAs, absent, invalid format |
| `verify_slot_close.py` — archive status | Archived, landed-but-active, active |

Verification extensions use composable check functions (matching existing
pattern: `check_branch_merged()`, `check_branch_stamped()`, etc.).

---

## Scope

### In scope

- `cmd_write_marker()` in `work_end_execute.py` + SKILL.md Step 3.4 instruction
- Phase C slot mode clarification in SKILL.md Step 3.5
- `verify_slot_close.py` extensions (original sync, .landed, archive) as composable check functions
- Tests for marker write and verification extensions

### Not in scope

- `close_artifacts.py` changes — push works via `updateInstead`
- `merge-slot` changes — works correctly once marker exists
- `work_end_execute.py` changes — slot mode doesn't use `cmd_land()`
- Comprehensive `verify_work_end.py` — deferred to follow-up issue
- Unified close sequence — separate deliverable per restructure spec
