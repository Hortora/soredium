#!/usr/bin/env python3
"""
Reconcile slot filesystem state with worklog DB.

Scans all four slot locations (slots/, slots/attic/, worktrees/, worktrees/attic/)
and compares against worklog.db. Fixes stale DB states, moves active legacy slots
to slots/, and removes ghost directories.

Usage:
    python3 scripts/reconcile_slots.py <family-root>          # dry-run
    python3 scripts/reconcile_slots.py <family-root> --apply  # execute
"""

import shutil
import sqlite3
import sys
from pathlib import Path

_lib = Path.home() / ".claude" / "lib"
if _lib.exists():
    sys.path.insert(0, str(_lib))

_slot_mgr = Path(__file__).resolve().parent.parent / "work-slot"
if _slot_mgr.exists():
    sys.path.insert(0, str(_slot_mgr))

try:
    import worklog as _wl
except ImportError:
    _wl = None

try:
    from slot_manager import relocate_claude_projects, remove_claude_projects
except ImportError:
    relocate_claude_projects = None
    remove_claude_projects = None


def scan_disk(family_root: Path) -> dict[int, dict]:
    """Scan all four slot locations and return a map of slot_number -> disk info."""
    results: dict[int, dict] = {}

    for dir_name, is_legacy in [("slots", False), ("worktrees", True)]:
        base = family_root / dir_name
        if not base.exists():
            continue

        for d in base.iterdir():
            if not d.is_dir() or not d.name.isdigit() or d.name == "attic":
                continue
            num = int(d.name)
            has_slot_file = (d / ".slot").exists()
            has_m2_only = not has_slot_file and (d / ".m2").exists() and len(list(d.iterdir())) <= 1
            has_landed = (d / ".landed").exists()
            has_phase_a = (d / ".phase-a-complete").exists()

            if num in results and results[num]["location"] == "active":
                continue

            results[num] = {
                "location": "active",
                "dir_type": "legacy" if is_legacy else "current",
                "path": str(d),
                "has_slot_file": has_slot_file,
                "has_m2_only": has_m2_only,
                "has_landed": has_landed,
                "has_phase_a": has_phase_a,
            }

        attic = base / "attic"
        if attic.exists():
            for d in attic.iterdir():
                if not d.is_dir() or not d.name.isdigit():
                    continue
                num = int(d.name)
                has_landed = (d / ".landed").exists()
                has_phase_a = (d / ".phase-a-complete").exists()

                if num in results:
                    existing = results[num]
                    if existing["location"] == "active" and existing["has_slot_file"]:
                        results.setdefault(f"{num}_attic", {
                            "location": "attic",
                            "dir_type": "legacy_attic" if is_legacy else "current_attic",
                            "path": str(d),
                            "has_landed": has_landed,
                            "has_phase_a": has_phase_a,
                        })
                        continue
                    if existing["location"] == "active" and not existing["has_slot_file"]:
                        results[f"{num}_ghost"] = existing
                        results[num] = {
                            "location": "attic",
                            "dir_type": "legacy_attic" if is_legacy else "current_attic",
                            "path": str(d),
                            "has_landed": has_landed,
                            "has_phase_a": has_phase_a,
                        }
                        continue

                results[num] = {
                    "location": "attic",
                    "dir_type": "legacy_attic" if is_legacy else "current_attic",
                    "path": str(d),
                    "has_landed": has_landed,
                    "has_phase_a": has_phase_a,
                }

    return results


def scan_db(family_root: str) -> dict[int, dict]:
    """Query worklog DB for all slots in this family_root."""
    if not _wl:
        return {}
    conn = _wl.connect()
    normalized = str(Path(family_root).resolve())
    rows = conn.execute(
        "SELECT id, slot_number, state, created_at, archived_at "
        "FROM slots WHERE family_root=? OR family_root=?",
        (normalized, family_root),
    ).fetchall()
    result = {}
    for r in rows:
        result[r["slot_number"]] = {
            "id": r["id"],
            "state": r["state"],
            "created_at": r["created_at"],
            "archived_at": r["archived_at"],
        }
    conn.close()
    return result


def reconcile(family_root: Path, apply: bool = False) -> None:
    disk = scan_disk(family_root)
    db = scan_db(str(family_root))

    actions: list[dict] = []

    integer_keys = sorted(k for k in disk if isinstance(k, int))

    for num in integer_keys:
        d = disk[num]
        db_entry = db.get(num)

        # Ghost directory: no .slot file, just remnants
        ghost_key = f"{num}_ghost"
        if ghost_key in disk:
            ghost = disk[ghost_key]
            actions.append({
                "type": "remove_ghost",
                "slot": num,
                "path": ghost["path"],
                "reason": f"ghost remnant (no .slot, real data in {d['path']})",
            })

        # Active legacy slot that should move to slots/
        if d["location"] == "active" and d["dir_type"] == "legacy" and d["has_slot_file"]:
            dest = family_root / "slots" / str(num)
            if not dest.exists():
                actions.append({
                    "type": "move_to_slots",
                    "slot": num,
                    "from": d["path"],
                    "to": str(dest),
                    "reason": "active legacy slot — move to slots/",
                })

        # Active slot without .slot file (ghost)
        if d["location"] == "active" and not d.get("has_slot_file", True):
            if d.get("has_m2_only"):
                actions.append({
                    "type": "remove_ghost",
                    "slot": num,
                    "path": d["path"],
                    "reason": "ghost directory (only .m2, no .slot)",
                })

        # DB says active but disk shows archived
        if db_entry and db_entry["state"] in ("active", "ready") and d["location"] == "attic":
            actions.append({
                "type": "update_db_archived",
                "slot": num,
                "db_state": db_entry["state"],
                "disk_location": d["path"],
                "reason": f"DB says {db_entry['state']} but slot is in attic",
            })

    # Print plan
    if not actions:
        print("Nothing to reconcile — all clean.")
        return

    print(f"{'PLAN' if not apply else 'EXECUTING'}: {len(actions)} actions\n")

    move_count = 0
    ghost_count = 0
    db_update_count = 0

    for a in sorted(actions, key=lambda x: (x["type"], x.get("slot", 0))):
        if a["type"] == "move_to_slots":
            move_count += 1
            print(f"  MOVE  slot {a['slot']:>3}: {a['from']} -> {a['to']}")
            if apply:
                Path(a["to"]).parent.mkdir(parents=True, exist_ok=True)
                if relocate_claude_projects:
                    moved = relocate_claude_projects(Path(a["from"]), Path(a["to"]))
                    if moved:
                        print(f"         claude projects relocated: {moved}")
                shutil.move(a["from"], a["to"])
                src = Path(a["from"])
                if src.exists():
                    shutil.rmtree(str(src), ignore_errors=True)
                print(f"         done")

        elif a["type"] == "remove_ghost":
            ghost_count += 1
            print(f"  GHOST slot {a['slot']:>3}: {a['path']} — {a['reason']}")
            if apply:
                if remove_claude_projects:
                    removed = remove_claude_projects(Path(a["path"]))
                    if removed:
                        print(f"         claude projects removed: {removed}")
                shutil.rmtree(a["path"], ignore_errors=True)
                print(f"         removed")

        elif a["type"] == "update_db_archived":
            db_update_count += 1
            print(f"  DB    slot {a['slot']:>3}: {a['db_state']} -> archived ({a['reason']})")
            if apply and _wl:
                conn = _wl.connect()
                _wl.record_slot_archive(
                    conn, a["slot"], str(family_root),
                    archived_from="unknown",
                    archived_to=a["disk_location"],
                )
                conn.close()
                print(f"         updated")

    print(f"\nSummary: {move_count} moves, {ghost_count} ghost removals, {db_update_count} DB updates")
    if not apply:
        print("\nRe-run with --apply to execute.")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    family_root = Path(sys.argv[1])
    if not family_root.is_dir():
        print(f"ERROR: {family_root} is not a directory")
        return 1

    apply = "--apply" in sys.argv
    reconcile(family_root, apply=apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
