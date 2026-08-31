# Archive Slot Session Guard

## Problem

`archive_slot()` moves `slots/N/` to `slots/attic/N/` without checking if any
Claude Code session has its CWD inside the slot. The move renames the
directory underneath a running session, causing path resolution failures.

## Design

### 1. Detection — `find_active_sessions(slot_dir)` in `slot_claude.py`

Uses `lsof +D <slot_dir>` to find processes with open file descriptors
(including CWD) inside the slot directory.

**Input:** slot directory path  
**Output:** list of `(pid, command, path)` tuples for active processes

```python
def find_active_sessions(slot_dir: Path) -> list[tuple[int, str, str]]:
    result = subprocess.run(
        ["lsof", "+D", str(slot_dir)],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        return []
    sessions = []
    for line in result.stdout.strip().splitlines()[1:]:  # skip header
        parts = line.split()
        if len(parts) >= 9:
            pid = int(parts[1])
            cmd = parts[0]
            path = parts[-1]
            sessions.append((pid, cmd, path))
    return sessions
```

`lsof +D` recursively scans the directory. On macOS and Linux, this finds
any process with a file descriptor (CWD, open file, mmap) inside the slot.

**Timeout:** 10 seconds. If lsof hangs or is unavailable, return empty
(fail open — the guard becomes a no-op rather than blocking all archival).

### 2. Gate in `archive_slot()`

After existing pre-checks (unmerged, landed, SHA) and before `shutil.move()`.

```python
if not force:
    active = find_active_sessions(slot_dir)
    if active:
        for pid, cmd, path in active:
            print(f"ACTIVE_SESSION={pid}:{cmd}:{path}")
        print(f"ERROR=active_sessions slot={slot_num}")
        print(f"ERROR_DETAIL={len(active)} active process(es) in slot directory")
        print("HINT=close the session first, or pass --force to override")
        sys.exit(1)
else:
    active = find_active_sessions(slot_dir)
    if active:
        for pid, cmd, path in active:
            print(f"WARN_ACTIVE_SESSION={pid}:{cmd}:{path}")
        print(f"WARN=active_sessions_overridden slot={slot_num}")
```

### 3. Deduplication with sweep

`sweep_orphaned_claude_projects()` (called just before the move) already
has PID-checking logic for archived slots. The new guard runs BEFORE the
move — they're complementary, not redundant.

## Testing

- Unit test for `find_active_sessions` with a mock subprocess
- Integration test: `archive_slot` blocks when a process has CWD in the slot
- Integration test: `archive_slot` proceeds when --force is set
- Integration test: `archive_slot` proceeds when no active sessions

## Scope boundaries

- Does NOT add PID files to Claude project directories (out of scope)
- Does NOT change the `.archived-by-pid` mechanism (complementary, not replaced)
- Does NOT scan `~/.claude/projects/` (lsof is more definitive than project dir matching)

## References

- Issue #314 — incident description
- `slot_lifecycle.py:588-677` — archive_slot function
- `slot_claude.py:30-42` — existing relocate_claude_projects
- `slot_claude.py:45-101` — sweep_orphaned_claude_projects (PID check pattern)
