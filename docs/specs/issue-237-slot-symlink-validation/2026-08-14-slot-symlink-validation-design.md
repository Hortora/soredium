# Slot Symlink Validation — Design Spec

**Issue:** #237 — Slot workspace symlink failures
**Branch:** `issue-237-slot-symlink-validation`
**Date:** 2026-08-14

## Problem

`create_slot` and `add_repo` silently produce broken `wksp/` symlinks in two
scenarios:

1. **Naming collision:** `resolve_workspace_source()` returns `"work"` as the
   default workspace clone name. The collision check only inspects the current
   slot's repo list, not all repos in the family. A family repo named `"work"`
   (not in this slot) collides silently — later `add_repo("work")` fails with
   `ERROR=repo_already_in_slot`.

2. **No post-creation validation:** After cloning and symlinking, neither
   function verifies that `wksp/` symlinks resolve. Broken symlinks are
   invisible — sessions run as `SINGLE_REPO=yes` with handoffs going to the
   wrong place and workspace artifacts invisible.

## Changes

### 1. Family-wide naming collision check

**New function:** `_get_family_repo_names(family_root: Path) -> set[str]`

Scans all top-level directories in `family_root` that contain `.git` (file or
directory). Returns their names as a set.

**Modified:** `create_slot()` — replace `if ws_name in repos` (line 548) with
`if ws_name in _get_family_repo_names(family_root)`. Also apply the same check
at line 552 where `ws_slot_dir` existence is checked for disambiguation.

**Modified:** `add_repo()` — replace `if ws_name in existing_repos` (line 703)
with `if ws_name in _get_family_repo_names(family_root)`. The subsequent
directory-existence disambiguation (lines 707-711) stays — it handles the case
where two workspace sources resolve to the same name.

### 2. Post-creation validation

**New function:** `validate_slot_wksp(slot_dir: Path) -> list[str]`

For each project repo clone in the slot (via `get_slot_repos()`):
- If the original repo has a `wksp` symlink: check the clone has one too,
  and that it resolves to an existing directory
- Returns a list of failure descriptions (empty = all OK)

Resolving the "original repo" for each clone uses `resolve_original_repo()`.

**Modified:** `create_slot()` — after `write_slot_md()` and DB confirmation,
call `validate_slot_wksp()`. If failures, print `ERROR=wksp_validation_failed`
with each failure, then `sys.exit(1)`.

**Modified:** `add_repo()` — after `_update_slot_repos()`, call
`validate_slot_wksp()` scoped to just the added repo. Same error pattern.

### 3. list_slots health surfacing

**Modified:** `list_slots()` — for each active (non-archived) slot, run
`validate_slot_wksp()`. Add `wksp_ok: bool` to the slot dict.

**Modified:** CLI output — append `WKSP=ok` or `WKSP=broken` to each slot line.

### 4. add_repo workspace wiring parity

**Modified:** `add_repo()` — after cloning the workspace (when a new workspace
clone is created at lines 713-720), add `configure_slot_remotes()` and
`configure_update_instead()` calls, matching `create_slot()`'s workspace
wiring at lines 570-571.

## Testing

Each fix gets dedicated test cases in `test_slot_manager.py`:

1. **`TestFamilyRepoNames`** — scan finds git dirs, ignores non-git dirs,
   ignores `.m2`/`attic`/`slots`
2. **`TestValidateSlotWksp`** — passes when symlinks resolve, fails when
   dangling, fails when missing, passes when original has no wksp
3. **`TestCreateSlotValidation`** — create_slot exits 1 on broken wksp
4. **`TestCreateSlotCollisionFamily`** — collision detected against family
   repo not in current slot's repo list
5. **`TestListSlotsWkspHealth`** — list output includes wksp_ok field
6. **`TestAddRepoWorkspaceRemotes`** — add_repo configures remotes on
   workspace clone

## Files Modified

- `work-slot/slot_manager.py` — all changes
- `tests/test_slot_manager.py` — new test classes

## Acceptance Criteria Mapping

| Criterion | Change |
|-----------|--------|
| create_slot creates workspace subdirs and un-ignores | Already implemented (lines 579-585); validation catches failures |
| add_repo same fix | Already implemented (lines 730-732); validation catches failures |
| Post-creation validation with fail-fast | Change 2 — `validate_slot_wksp()` + exit 1 |
| Naming collision against all family repos | Change 1 — `_get_family_repo_names()` |
| list/health surfaces broken symlinks | Change 4 — `wksp_ok` in list_slots |
