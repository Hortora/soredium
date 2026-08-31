"""slot_claude.py — Claude Code project directory management."""

import os
import shutil
import sys
from pathlib import Path

from slot_core import SLOT_DIR_NAME, LEGACY_SLOT_DIR_NAME
from slot_metadata import _read_promotion_stamp

_lib = Path.home() / ".claude" / "lib"
if _lib.exists():
    sys.path.insert(0, str(_lib))
try:
    import worklog as _wl
except ImportError:
    _wl = None


def _claude_project_matches(proj_name: str, slot_path_encoded: str) -> bool:
    """Check if a Claude project directory name matches a slot path.
    Uses boundary-aware matching to prevent /worktrees/1 matching /worktrees/10."""
    if proj_name == slot_path_encoded:
        return True
    if proj_name.startswith(slot_path_encoded + "-"):
        return True
    return False


def relocate_claude_projects(slot_dir: Path, dest_dir: Path) -> int:
    """Record the archiving session's PID so the sweep knows when it's safe to rename.

    Does NOT touch the .claude/projects/ directory — the active Claude Code
    session is still writing to it. The sweep (called on every subsequent
    archival) checks the PID and renames once the session has exited.
    """
    pid_file = dest_dir / ".archived-by-pid"
    try:
        pid_file.write_text(str(os.getppid()))
    except OSError:
        pass
    return 0


def find_active_sessions(slot_dir: Path) -> list[tuple[int, str, str]]:
    """Find processes with open file descriptors inside slot_dir.

    Uses lsof +D for recursive scan. Returns [(pid, command, path)].
    Fails open (returns []) if lsof is unavailable or times out.
    """
    import subprocess as _sp
    try:
        result = _sp.run(
            ["lsof", "+D", str(slot_dir)],
            capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, _sp.TimeoutExpired):
        return []
    if not result.stdout.strip():
        return []
    sessions = []
    seen_pids: set[int] = set()
    for line in result.stdout.strip().splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            pid = int(parts[1])
        except ValueError:
            continue
        if pid in seen_pids:
            continue
        seen_pids.add(pid)
        cmd = parts[0]
        path = parts[-1] if len(parts) >= 9 else ""
        sessions.append((pid, cmd, path))
    return sessions


def sweep_orphaned_claude_projects(family_root: Path) -> int:
    """Rename project dirs for archived slots whose archiving session has exited.

    For each slot in attic with an .archived-by-pid marker, check if the
    PID is still alive. If dead, rename the old-keyed project dir to the
    attic-keyed name — .jsonl files travel with the rename, preserving
    server-side conversation correlation.

    Called during each archival — eventually consistent cleanup.
    """
    claude_projects = Path.home() / ".claude" / "projects"
    if not claude_projects.is_dir():
        return 0

    swept = 0

    for proj_link in list(claude_projects.iterdir()):
        if proj_link.is_symlink():
            proj_link.unlink()
            swept += 1

    for dir_name in (SLOT_DIR_NAME, LEGACY_SLOT_DIR_NAME):
        attic_dir = family_root / dir_name / "attic"
        if not attic_dir.is_dir():
            continue
        for slot_entry in sorted(attic_dir.iterdir()):
            if not slot_entry.is_dir() or not slot_entry.name.isdigit():
                continue

            pid_file = slot_entry / ".archived-by-pid"
            if not pid_file.exists():
                continue

            try:
                pid = int(pid_file.read_text().strip())
                os.kill(pid, 0)
                print(f"SKIPPED=slot-{slot_entry.name} (pid {pid} still alive)")
                continue
            except (ValueError, OSError):
                pass

            old_slot_path = family_root / dir_name / slot_entry.name
            old_encoded = str(old_slot_path.resolve()).replace("/", "-")
            attic_encoded = str(slot_entry.resolve()).replace("/", "-")

            for proj_dir in list(claude_projects.iterdir()):
                if proj_dir.is_symlink() or not proj_dir.is_dir():
                    continue
                if not _claude_project_matches(proj_dir.name, old_encoded):
                    continue
                new_name = proj_dir.name.replace(old_encoded, attic_encoded, 1)
                new_path = claude_projects / new_name
                if new_path.exists():
                    shutil.rmtree(str(new_path))
                shutil.move(str(proj_dir), str(new_path))
                swept += 1
                print(f"RENAMED={proj_dir.name} -> {new_name}")

            if _wl:
                try:
                    _conn = _wl.connect()
                    promoted, published, pub_dest = _read_promotion_stamp(slot_entry)
                    _wl.record_slot_archived(
                        _conn, int(slot_entry.name), str(family_root),
                        promoted=promoted, published=published,
                        publish_dest=pub_dest,
                    )
                    _conn.close()
                except Exception:
                    pass
            pid_file.unlink(missing_ok=True)
    return swept


def remove_claude_projects(slot_dir: Path) -> int:
    """Remove .claude/projects/ directories that reference a slot being destroyed."""
    claude_projects = Path.home() / ".claude" / "projects"
    if not claude_projects.is_dir():
        return 0

    slot_path_encoded = str(slot_dir.resolve()).replace("/", "-")
    removed = 0

    for proj_dir in list(claude_projects.iterdir()):
        if not proj_dir.is_dir():
            continue
        if _claude_project_matches(proj_dir.name, slot_path_encoded):
            shutil.rmtree(str(proj_dir), ignore_errors=True)
            removed += 1
    return removed
