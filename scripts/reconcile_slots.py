#!/usr/bin/env python3
"""
Reconcile slot filesystem state with worklog DB.

Three phases:
  1. audit    — scan disk + DB, classify divergences
  2. strategy — propose actions for each divergence
  3. execute  — apply approved actions (quarantine, not delete)

Usage:
    python3 scripts/reconcile_slots.py <family-root>              # audit only
    python3 scripts/reconcile_slots.py <family-root> --strategy   # audit + strategy
    python3 scripts/reconcile_slots.py <family-root> --execute    # audit + strategy + execute
"""

import shutil
import sys
from pathlib import Path

_lib = Path.home() / ".claude" / "lib"
if _lib.exists():
    sys.path.insert(0, str(_lib))

_scripts = Path(__file__).resolve().parent
sys.path.insert(0, str(_scripts))

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

SLOT_DIR_NAME = "slots"
LEGACY_SLOT_DIR_NAME = "worktrees"


def _list_dir_contents(path: Path) -> list[str]:
    if not path.exists():
        return []
    return sorted(f.name for f in path.iterdir())


def _infer_disk_state(location: str, has_landed: bool, has_phase_a: bool) -> str:
    if location == "attic":
        return "archived"
    if has_landed:
        return "landed"
    if has_phase_a:
        return "ready"
    return "active"


def _states_compatible(db_state: str, disk_state: str) -> bool:
    if db_state == disk_state:
        return True
    if db_state == "pending" and disk_state == "active":
        return True
    if db_state == "ready" and disk_state in ("active", "ready"):
        return True
    return False


def _scan_disk(family_root: Path) -> dict[int, dict]:
    results: dict[int, dict] = {}
    for dir_name in (SLOT_DIR_NAME, LEGACY_SLOT_DIR_NAME):
        base = family_root / dir_name
        if not base.exists():
            continue
        for d in base.iterdir():
            if not d.is_dir() or not d.name.isdigit() or d.name == "attic":
                continue
            num = int(d.name)
            if num in results:
                continue
            results[num] = {
                "location": "active",
                "path": str(d),
                "has_slot_file": (d / ".slot").exists(),
                "has_landed": (d / ".landed").exists(),
                "has_phase_a": (d / ".phase-a-complete").exists(),
                "contents": _list_dir_contents(d),
            }
        attic = base / "attic"
        if attic.exists():
            for d in attic.iterdir():
                if not d.is_dir() or not d.name.isdigit():
                    continue
                num = int(d.name)
                if num in results and results[num]["has_slot_file"]:
                    continue
                results[num] = {
                    "location": "attic",
                    "path": str(d),
                    "has_slot_file": (d / ".slot").exists(),
                    "has_landed": (d / ".landed").exists(),
                    "has_phase_a": (d / ".phase-a-complete").exists(),
                    "contents": _list_dir_contents(d),
                }
    return results


def _scan_db(family_root: str) -> dict[int, dict]:
    if not _wl:
        return {}
    conn = _wl.connect()
    normalized = _wl._norm(family_root)
    rows = conn.execute(
        "SELECT id, slot_number, state, created_at, archived_at "
        "FROM slots WHERE family_root=? OR family_root=?",
        (normalized, family_root),
    ).fetchall()
    conn.close()
    return {
        r["slot_number"]: {
            "id": r["id"],
            "state": r["state"],
            "created_at": r["created_at"],
            "archived_at": r["archived_at"],
        }
        for r in rows
    }


def audit(family_root: Path) -> list[dict]:
    """Phase 1: scan disk and DB, classify all divergences."""
    disk = _scan_disk(family_root)
    db = _scan_db(str(family_root))
    divergences = []
    all_nums = sorted(set(disk.keys()) | set(db.keys()))

    for num in all_nums:
        d = disk.get(num)
        db_entry = db.get(num)

        if d and not d["has_slot_file"] and d["location"] == "active":
            divergences.append({
                "slot": num,
                "class": "ghost",
                "disk_path": d["path"],
                "disk_contents": d["contents"],
                "db_state": db_entry["state"] if db_entry else None,
                "detail": f"directory with no .slot file, contains: {d['contents']}",
            })
            continue

        if db_entry and not d:
            if db_entry["state"] == "purged":
                continue
            divergences.append({
                "slot": num,
                "class": "db-only",
                "db_state": db_entry["state"],
                "db_created": db_entry.get("created_at", ""),
                "detail": f"DB says {db_entry['state']} but no directory on disk",
            })
            continue

        if d and not db_entry:
            divergences.append({
                "slot": num,
                "class": "disk-only",
                "disk_path": d["path"],
                "disk_location": d["location"],
                "has_landed": d.get("has_landed", False),
                "detail": f"directory at {d['location']} but no DB record",
            })
            continue

        if d and db_entry:
            disk_state = _infer_disk_state(
                d["location"], d.get("has_landed", False),
                d.get("has_phase_a", False))
            if not _states_compatible(db_entry["state"], disk_state):
                divergences.append({
                    "slot": num,
                    "class": "state-mismatch",
                    "disk_path": d["path"],
                    "disk_state": disk_state,
                    "db_state": db_entry["state"],
                    "detail": f"DB={db_entry['state']}, disk={disk_state}",
                })

    return divergences


def strategy(divergences: list[dict]) -> list[dict]:
    """Phase 2: propose an action for each divergence."""
    actions = []
    for d in divergences:
        cls = d["class"]
        if cls == "ghost":
            actions.append({
                "slot": d["slot"],
                "action": "quarantine",
                "source": d["disk_path"],
                "detail": f"move to quarantine/ — contents: {d.get('disk_contents', [])}",
                "risk": "low",
            })
        elif cls == "db-only":
            actions.append({
                "slot": d["slot"],
                "action": "remove_db_record",
                "db_state": d["db_state"],
                "detail": f"remove stale DB record (was {d['db_state']})",
                "risk": "low",
            })
        elif cls == "disk-only":
            actions.append({
                "slot": d["slot"],
                "action": "backfill_db",
                "disk_path": d["disk_path"],
                "disk_location": d["disk_location"],
                "detail": "create DB record from disk state",
                "risk": "medium" if d.get("has_landed") else "low",
            })
        elif cls == "state-mismatch":
            actions.append({
                "slot": d["slot"],
                "action": "update_db_state",
                "new_state": d["disk_state"],
                "old_state": d["db_state"],
                "detail": f"update DB from {d['db_state']} to {d['disk_state']}",
                "risk": "low",
            })
    return actions


def execute(actions: list[dict], family_root: Path) -> list[dict]:
    """Phase 3: apply approved actions. Returns results."""
    results = []
    for a in actions:
        try:
            if a["action"] == "quarantine":
                quarantine_dir = family_root / "slots" / "quarantine"
                quarantine_dir.mkdir(parents=True, exist_ok=True)
                dest = quarantine_dir / str(a["slot"])
                if dest.exists():
                    results.append({"slot": a["slot"], "action": a["action"],
                                    "status": "skipped", "detail": "quarantine dest exists"})
                    continue
                shutil.move(a["source"], str(dest))
                results.append({"slot": a["slot"], "action": a["action"], "status": "done"})

            elif a["action"] == "remove_db_record":
                if _wl:
                    conn = _wl.connect()
                    normalized = _wl._norm(str(family_root))
                    try:
                        conn.execute(
                            "DELETE FROM slots WHERE slot_number=? AND family_root=?",
                            (a["slot"], normalized),
                        )
                        conn.commit()
                        results.append({"slot": a["slot"], "action": a["action"], "status": "done"})
                    except Exception:
                        conn.rollback()
                        conn.execute(
                            "UPDATE slots SET state='purged' WHERE slot_number=? AND family_root=?",
                            (a["slot"], normalized),
                        )
                        conn.commit()
                        results.append({"slot": a["slot"], "action": a["action"],
                                        "status": "done", "note": "FK constraint — marked purged"})
                    conn.close()

            elif a["action"] == "backfill_db":
                if _wl:
                    conn = _wl.connect()
                    state = "archived" if a["disk_location"] == "attic" else "active"
                    normalized = _wl._norm(str(family_root))
                    conn.execute(
                        "INSERT INTO slots (slot_number, family_root, state, created_at) "
                        "VALUES (?, ?, ?, ?)",
                        (a["slot"], normalized, state, _wl._now()),
                    )
                    conn.commit()
                    conn.close()
                results.append({"slot": a["slot"], "action": a["action"], "status": "done"})

            elif a["action"] == "update_db_state":
                if _wl:
                    conn = _wl.connect()
                    normalized = _wl._norm(str(family_root))
                    if a["new_state"] == "archived":
                        conn.execute(
                            "UPDATE slots SET state='archived', archived_at=? "
                            "WHERE slot_number=? AND family_root=?",
                            (_wl._now(), a["slot"], normalized),
                        )
                    else:
                        conn.execute(
                            "UPDATE slots SET state=? WHERE slot_number=? AND family_root=?",
                            (a["new_state"], a["slot"], normalized),
                        )
                    conn.commit()
                    conn.close()
                results.append({"slot": a["slot"], "action": a["action"], "status": "done"})

        except Exception as e:
            results.append({"slot": a["slot"], "action": a["action"],
                            "status": "error", "detail": str(e)})
    return results


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    family_root = Path(sys.argv[1])
    if not family_root.is_dir():
        print(f"ERROR: {family_root} is not a directory")
        return 1

    phase = "audit"
    if "--execute" in sys.argv:
        phase = "execute"
    elif "--strategy" in sys.argv:
        phase = "strategy"

    divergences = audit(family_root)
    if not divergences:
        print("Nothing to reconcile — all clean.")
        return 0

    print(f"AUDIT: {len(divergences)} divergence(s) found\n")
    for d in divergences:
        print(f"  SLOT {d['slot']:>3}  class={d['class']}  {d['detail']}")
    print()

    if phase == "audit":
        print("Run with --strategy to see proposed actions.")
        return 0

    actions = strategy(divergences)
    print(f"STRATEGY: {len(actions)} action(s) proposed\n")
    for a in actions:
        print(f"  SLOT {a['slot']:>3}  {a['action']}  risk={a['risk']}  {a['detail']}")
    print()

    if phase == "strategy":
        print("Run with --execute to apply.")
        return 0

    results = execute(actions, family_root)
    print(f"EXECUTE: {len(results)} action(s) applied\n")
    for r in results:
        status_detail = f"  ({r['detail']})" if r.get("detail") else ""
        print(f"  SLOT {r['slot']:>3}  {r['action']}  {r['status']}{status_detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
