# slot_manager.py Decomposition Design

**Issue:** Hortora/soredium#306
**Date:** 2026-08-28
**Branch:** issue-306-slot-manager-decomposition

## Problem

`slot_manager.py` is 2,291 lines with 67 functions spanning 16 concerns. A 1:1 fix-to-feat ratio over 65 commits in 90 days indicates the file is too large to maintain safely. Six orchestrator functions exceed 80 lines each, with `create_slot` at 174 lines tangling clone setup, workspace wiring, maven config, ISX isolation, epic planning, worklog recording, and rollback in a single function.

## Goal

Decompose into focused modules where each is small enough to reason about and test independently. Preserve the CLI contract (KEY=VALUE output), all 298+ existing tests, and all 11 external Python API functions.

## Constraints

- **Incremental extraction** — one module per commit, full test suite green after each
- **Update consumers in-place** — no re-export facade; each extraction updates all importers
- **Tests move with code** — matching `test_slot_<module>.py` created in same commit
- **CLI contract preserved** — every subcommand's KEY=VALUE output format unchanged
- **Protocol: archive promotion verification** — `archive_slot()` must preserve `.artifacts-promoted` stamp check

## External API Surface

### Python Importers (8 files, 11 functions)

| Function | Consumers |
|----------|-----------|
| `parse_slot_md` | `work_end_context.py`, `project/topology.py` |
| `get_slot_repos` | `work_end_context.py`, `scripts/migrate_slot_workspace.py` |
| `is_slot_path` | `work-pause/pause_exec.py` |
| `is_project_repo` | `scripts/place_workspace_markers.py` |
| `is_workspace_clone` | `scripts/migrate_slot_workspace.py` |
| `resolve_workspace_source` | `scripts/migrate_slot_workspace.py` |
| `repoint_wksp` | `scripts/migrate_slot_workspace.py` |
| `create_proj_symlink` | `scripts/migrate_slot_workspace.py` |
| `relocate_claude_projects` | `scripts/reconcile_slots.py` |
| `remove_claude_projects` | `scripts/reconcile_slots.py` |
| `_unignore_subdir` | `scripts/fix_active_slots.py` |

### CLI Subcommands (12)

`create-slot`, `list-slots`, `remove-slot`, `scan-ready`, `merge-slot`, `archive-slot`, `restore-slot`, `check-cross-deps`, `sync-isx`, `migrate-remotes`, `repair-claude-projects`, `ensure-clone-layout`

All output KEY=VALUE pairs on stdout. `scan-ready` outputs JSON.

### Subprocess Callers (2 files)

`work_end_orchestrator.py` and `work_end_execute.py` invoke `slot_manager.py` via subprocess — these are unaffected by internal restructuring as long as the CLI entry point remains `work-slot/slot_manager.py`.

## Module Architecture

### Module Dependency Graph

```
slot_cli.py
  └── slot_lifecycle.py
        ├── slot_observability.py
        ├── slot_query.py
        ├── slot_git.py
        ├── slot_workspace.py
        ├── slot_maven.py
        ├── slot_isx.py
        ├── slot_claude.py
        └── slot_metadata.py
              └── slot_core.py
```

All modules live in `work-slot/`. All test files live in `tests/`.

### Module Specifications

#### 1. `slot_core.py` (~140 lines)

Shared utilities, resolution helpers, constants, and the exception class. No dependencies on other slot modules.

**Contents:**
- Constants: `SLOT_DIR_NAME`, `LEGACY_SLOT_DIR_NAME`, `_IDE_ARTIFACTS`, `_REGENERABLE_DIRS`
- Exception: `SlotCreationError`
- Resolution: `_resolve_slots_dir`, `_resolve_slot_dir_for_number`, `_get_family_repo_names`
- Classification: `is_slot_path`, `is_project_repo`, `is_workspace_clone`, `is_worktree`, `resolve_original_repo`, `_get_clone_origin`
- Repo listing: `get_slot_repos`, `get_all_slot_repos`
- Filesystem: `run_cmd`, `_cleanup_remnant_dir`, `_escape_slot_cwd`, `_has_unmerged_content`

**External API update:** `is_slot_path` → `pause_exec.py` imports from `slot_core`; `is_project_repo` → `place_workspace_markers.py` imports from `slot_core`; `is_workspace_clone` → `migrate_slot_workspace.py` imports from `slot_core`; `get_slot_repos` → `work_end_context.py` and `migrate_slot_workspace.py` import from `slot_core`.

#### 2. `slot_metadata.py` (~130 lines)

Pure data layer: parsing and writing `.slot` files, promotion stamps, landed markers.

**Contents:**
- `parse_slot_md`, `write_slot_md`
- `_read_promotion_stamp`
- `is_slot_landed`, `verify_landed_shas`
- `_fix_stale_checkboxes`

**Deps:** `slot_core` (for `run_cmd`, `get_slot_repos`)

**External API update:** `parse_slot_md` → `work_end_context.py` and `topology.py` import from `slot_metadata`.

#### 3. `slot_maven.py` (~95 lines)

Maven settings generation and slot repo setup.

**Contents:**
- `_write_slot_settings`
- `setup_slot_repo`

**Deps:** `slot_core` (for `run_cmd`, `_REGENERABLE_DIRS`)

#### 4. `slot_isx.py` (~75 lines)

ISX instance lifecycle: availability check, creation, teardown, remote wiring, sync.

**Contents:**
- `_check_isx_available`, `_truncate_instance_name`
- `_teardown_isx`, `_wire_isx_remotes`
- `sync_isx`

**Deps:** `slot_core` (for `run_cmd`), `slot_metadata` (for `parse_slot_md`, `get_slot_repos` via core)

#### 5. `slot_claude.py` (~100 lines)

Claude Code project directory management: matching, relocation, sweep, removal.

**Contents:**
- `_claude_project_matches`
- `relocate_claude_projects`
- `sweep_orphaned_claude_projects`
- `remove_claude_projects`

**Deps:** `slot_core`, `slot_metadata` (for `_read_promotion_stamp`, `parse_slot_md`)

**External API update:** `relocate_claude_projects` and `remove_claude_projects` → `reconcile_slots.py` imports from `slot_claude`.

#### 6. `slot_git.py` (~115 lines)

Git clone infrastructure: remote configuration, hooks, alternates, worktree migration.

**Contents:**
- `configure_slot_remotes`, `configure_update_instead`
- `install_post_commit_hook`
- `sync_main`
- `_symlink_gitignored_assets`, `_exclude_symlinks`
- `_repack_broken_alternates`
- `_migrate_worktree_to_clone`, `ensure_clone_layout`

**Deps:** `slot_core` (for `run_cmd`, `is_worktree`, `resolve_original_repo`, `_REGENERABLE_DIRS`)

**Module-level state:** `_detect_topology` (optional import from `work-end/common.py`) moves here — it's only used by `configure_slot_remotes`.

#### 7. `slot_workspace.py` (~130 lines)

Workspace discovery, symlink wiring, CLAUDE.md replication, validation.

**Contents:**
- `resolve_workspace_source`, `discover_workspace`
- `repoint_wksp`, `create_proj_symlink`
- `_unignore_subdir`
- `replicate_claude_md`
- `validate_slot_wksp`

**Deps:** `slot_core` (for `run_cmd`, `is_workspace_clone`)

**External API update:** `resolve_workspace_source`, `repoint_wksp`, `create_proj_symlink` → `migrate_slot_workspace.py` imports from `slot_workspace`; `_unignore_subdir` → `fix_active_slots.py` imports from `slot_workspace`.

#### 8. `slot_query.py` (~150 lines)

Read-only queries: listing, scanning, cross-repo dependency checking.

**Contents:**
- `list_slots`
- `scan_ready`
- `check_cross_deps`
- `find_slot_by_branch`
- `get_repo_stats`

**Deps:** `slot_core`, `slot_metadata` (for `parse_slot_md`), `slot_workspace` (for `validate_slot_wksp`)

#### 9. `slot_observability.py` (~80 lines)

Worklog recording wrapper and disk/DB drift detection.

**Contents:**
- Worklog helper: a `record_worklog(event, slot_dir, ...)` function wrapping the inline try/connect/record/close pattern that appears 7 times
- `_check_drift`, `_map_db_to_disk_state`

**Deps:** `slot_core`, `slot_metadata` (for `parse_slot_md`)

**Module-level state:** `_wl` (worklog module import) moves here — it's the only module that uses it directly. Other modules call through the `record_worklog` wrapper.

#### 10. `slot_lifecycle.py` (~510 lines → ~450 after dedup)

Orchestrators as explicit pipelines. Each orchestrator becomes a sequence of named steps calling into leaf modules.

**Contents:**
- `_setup_repo_in_slot` — extracted shared 12-step pipeline from `create_slot`/`add_repo`
- `create_slot`, `add_repo`, `remove_repo`, `_update_slot_repos`
- `merge_slot`
- `archive_slot`, `remove_slot`, `restore_slot`
- `_build_epic_plan`, `allocate_slot_number`
- `migrate_remotes`

**Deps:** All leaf modules.

**Dedup:** `create_slot` and `add_repo` both call `_setup_repo_in_slot(slot_dir, repo_path, branch, m2_dir)` instead of duplicating the clone→checkout→symlink→remote→hook→setup→workspace sequence. Eliminates ~60 lines.

#### 11. `slot_cli.py` (~155 lines)

CLI dispatch. Thin wrapper: parse args, validate, call lifecycle/query functions, format output.

**Contents:**
- `parse_args`
- `main`

**Deps:** `slot_lifecycle`, `slot_query`, `slot_isx` (for `sync_isx`), `slot_git` (for `ensure_clone_layout`), `slot_claude` (for `sweep_orphaned_claude_projects`)

**Entry point:** `slot_manager.py` becomes a 3-line shim:
```python
#!/usr/bin/env python3
from slot_cli import main
if __name__ == "__main__":
    main()
```

This preserves the `python3 work-slot/slot_manager.py` CLI contract for all subprocess callers.

## Extraction Sequence

Each step is one commit. Full test suite (`python3 -m pytest tests/test_slot_manager.py -v`) must pass after each.

| Step | Module | Functions moved | Consumers updated | Test file created |
|------|--------|----------------|-------------------|-------------------|
| 1 | `slot_core.py` | 16 | 4 files | `test_slot_core.py` |
| 2 | `slot_metadata.py` | 6 | 2 files | `test_slot_metadata.py` |
| 3 | `slot_maven.py` | 2 | 0 files | `test_slot_maven.py` |
| 4 | `slot_isx.py` | 5 | 0 files | `test_slot_isx.py` |
| 5 | `slot_claude.py` | 4 | 1 file | `test_slot_claude.py` |
| 6 | `slot_git.py` | 9 | 0 files | `test_slot_git.py` |
| 7 | `slot_workspace.py` | 8 | 2 files | `test_slot_workspace.py` |
| 8 | `slot_query.py` | 5 | 0 files | `test_slot_query.py` |
| 9 | `slot_observability.py` | 3 + wrapper | 0 files | `test_slot_observability.py` |
| 10 | `slot_lifecycle.py` | 12 + dedup | 0 files | `test_slot_lifecycle.py` |
| 11 | `slot_cli.py` | 2 + shim | 2 files (subprocess) | `test_slot_cli.py` |

## Verification

After each extraction:
1. `python3 -m pytest tests/test_slot_manager.py tests/test_slot_<new>.py -v` — all tests pass
2. After all extractions: `python3 -m pytest tests/ -v` — full suite passes (298+ tests)
3. CLI smoke test: `python3 work-slot/slot_manager.py list-slots <family-root>` — KEY=VALUE output unchanged

## Risks

| Risk | Mitigation |
|------|------------|
| Circular imports between modules | Dependency graph is a DAG — core at the bottom, lifecycle at the top. No cycles by construction. |
| Test identification errors (wrong tests moved to wrong module) | Each moved test must exercise only functions in its new module. Verify by running `test_slot_<module>.py` in isolation. |
| Subprocess callers break | `slot_manager.py` shim preserves the entry point path. CLI output format unchanged. |
| `sys.path` manipulation for imports | All modules in `work-slot/` — same directory, no path manipulation needed between them. Consumer files already do `sys.path.insert(0, ...)` to reach `work-slot/`. |

## References

- [Hortora/soredium#306](https://github.com/Hortora/soredium/issues/306) — issue with full audit
- `work-slot/slot_manager.py` — source file (2,291 lines, 67 functions)
- `tests/test_slot_manager.py` — test file (4,315 lines, 298+ tests)
- Protocol PP-20260609-df21ed — externalised scripts require tests
- Protocol PP-20260801-a1b2c3 — archive requires promotion verification
- `decisions.md` — D1 (module boundaries), D2 (extraction order), D3 (test organization), D4 (dedup strategy)
