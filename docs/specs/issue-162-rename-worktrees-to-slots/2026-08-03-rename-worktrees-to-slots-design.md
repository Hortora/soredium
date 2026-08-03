# Rename slot directory: worktrees/ → slots/

**Issue:** #162
**Date:** 2026-08-03
**Status:** Approved

## Problem

Three things named "worktrees":
1. **Our slots** — `worktrees/<N>/` (git clone --shared, NOT git worktrees)
2. **Our git worktrees** — `.worktrees/` (actual git worktrees via `using-git-worktrees`)
3. **Claude Code worktrees** — `.claude/worktrees/<name>/` (actual git worktrees via `EnterWorktree`)

The detection heuristic `"/worktrees/" in path` matches all three, causing
skills to misidentify Claude Code worktrees as slots (#161).

## Approach: Dual-path read

New slots created under `slots/`. Existing `worktrees/` slots continue to work.
No migration step required — reads check both directories.

## Design

### Constants (slot_manager.py)

```python
SLOT_DIR_NAME = "slots"
LEGACY_SLOT_DIR_NAME = "worktrees"
```

### Resolution helper (slot_manager.py)

```python
def _resolve_slots_dir(family_root: Path) -> Path:
    new = family_root / SLOT_DIR_NAME
    old = family_root / LEGACY_SLOT_DIR_NAME
    if new.exists():
        return new
    if old.exists():
        return old
    return new  # default to new for creation
```

- **Creation** (`create_slot`): always `family_root / SLOT_DIR_NAME`
- **Reading** (all other functions): `_resolve_slots_dir(family_root)`
- **Attic**: stays under the active directory (`slots/attic/` or `worktrees/attic/`)

### Detection heuristic (slot_manager.py, exported)

```python
def is_slot_path(path: str) -> bool:
    return "/slots/" in path or "/worktrees/" in path
```

Replaces inline `"/worktrees/" in path` checks in:
- `work_router.py` (line 75)
- `pause_exec.py` (line 189)
- `ctx.py` (line 171/193)

### pause_exec.py path parsing

`_resolve_slot_dir()` parses path parts by name. Updated to check both:

```python
for name in ("slots", "worktrees"):
    try:
        idx = parts.index(name)
        ...
```

### SKILL.md updates (separate commit)

8 SKILL.md files reference `worktrees/<N>/` paths and `"/worktrees/" in path`
detection. Update to `slots/` as primary with legacy note. Separate commit
to keep code changes reviewable.

### Tests

- `test_slot_manager.py`: fixtures create under `slots/`, add backward-compat tests
  for existing `worktrees/` slots
- `test_work_router.py`: detection with both `/slots/` and `/worktrees/` paths
- `test_slot_terminology.py`: enforce `slots/` as canonical name

## What does NOT change

- `.worktrees/` (dot-prefixed, actual git worktrees) — unchanged
- `.claude/worktrees/` (Claude Code worktrees) — unchanged
- `.slot` file format and content — unchanged
- Slot numbering scheme — unchanged
- Archive structure (`attic/<N>/`) — unchanged, just under different parent

## Risks

- **Mixed state**: a family root could have both `slots/` and `worktrees/` if
  old slots weren't archived before new ones are created. `_resolve_slots_dir()`
  prefers `slots/` — old slots in `worktrees/` become invisible. Mitigated by:
  old slots should be archived or merged before this change deploys.
  If both exist, `list_slots` should scan both.

  **Decision:** `_resolve_slots_dir` returns one directory. For `list_slots`,
  scan both if both exist (merge results, deduplicate by slot number).
  For `create_slot`, always use `slots/`. For single-slot operations
  (`merge_slot`, `archive_slot`, etc.), check `slots/<N>` first, then
  `worktrees/<N>`.
