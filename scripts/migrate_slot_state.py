#!/usr/bin/env python3
"""
Migrate .slot files to include a state: field.

Scans all active and archived slots for a given family root,
determines the correct state from disk signals and DB, and writes
the state: field to each .slot file.

Usage:
    python3 scripts/migrate_slot_state.py <family-root>              # dry-run
    python3 scripts/migrate_slot_state.py <family-root> --apply      # apply changes
"""

import sys
from pathlib import Path

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
    from slot_metadata import set_slot_state
except ImportError:
    set_slot_state = None

SLOT_DIR_NAMES = ("slots", "worktrees")


def _read_existing_state(slot_dir: Path) -> str | None:
    slot_file = slot_dir / ".slot"
    if not slot_file.exists():
        return None
    for line in slot_file.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("state:") or stripped.startswith("status:"):
            return stripped.split(":", 1)[1].strip()
    return None


def _infer_state(slot_dir: Path, location: str, db_state: str | None) -> str:
    """Determine correct state from disk signals and DB."""
    if location == "attic":
        return "archived"
    if (slot_dir / ".landed").exists():
        return "landed"
    if (slot_dir / ".phase-a-complete").exists():
        return "ready"
    if db_state in ("paused",):
        return "paused"
    if db_state in ("stale",):
        return "stale"
    if db_state in ("abandoned",):
        return "abandoned"
    return "active"


def _get_db_states(family_root: str) -> dict[int, str]:
    if not _wl:
        return {}
    conn = _wl.connect()
    normalized = _wl._norm(family_root)
    rows = conn.execute(
        "SELECT slot_number, state FROM slots "
        "WHERE family_root=? OR family_root=?",
        (normalized, family_root),
    ).fetchall()
    conn.close()
    return {r["slot_number"]: r["state"] for r in rows}


def migrate(family_root: Path, apply: bool = False) -> dict:
    db_states = _get_db_states(str(family_root))
    results = {"updated": 0, "already_set": 0, "no_slot_file": 0, "corrected": 0}

    for dir_name in SLOT_DIR_NAMES:
        base = family_root / dir_name
        if not base.exists():
            continue

        for d in sorted(base.iterdir()):
            if not d.is_dir() or not d.name.isdigit():
                continue
            num = int(d.name)
            _process_slot(d, num, "active", db_states, apply, results)

        attic = base / "attic"
        if attic.exists():
            for d in sorted(attic.iterdir()):
                if not d.is_dir() or not d.name.isdigit():
                    continue
                num = int(d.name)
                _process_slot(d, num, "attic", db_states, apply, results)

    return results


def _process_slot(slot_dir: Path, num: int, location: str,
                  db_states: dict[int, str], apply: bool,
                  results: dict) -> None:
    slot_file = slot_dir / ".slot"
    if not slot_file.exists():
        results["no_slot_file"] += 1
        return

    existing = _read_existing_state(slot_dir)
    db_state = db_states.get(num)
    correct = _infer_state(slot_dir, location, db_state)

    if existing == correct:
        results["already_set"] += 1
        return

    action = "UPDATE" if existing else "ADD"
    if existing and existing != correct:
        action = "CORRECT"
        results["corrected"] += 1

    prefix = "WOULD_" if not apply else ""
    old_part = f" (was: {existing})" if existing else ""
    print(f"  {prefix}{action} slot {num:>3} [{location}]: state: {correct}{old_part}")

    if apply and set_slot_state:
        set_slot_state(slot_dir, correct)
    results["updated"] += 1


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    family_root = Path(sys.argv[1])
    if not family_root.is_dir():
        print(f"ERROR: {family_root} is not a directory")
        return 1

    apply = "--apply" in sys.argv
    mode = "APPLYING" if apply else "DRY RUN"
    print(f"Migrating .slot state fields ({mode})...\n")

    results = migrate(family_root, apply=apply)

    print(f"\nSummary: {results['updated']} {'updated' if apply else 'to update'}, "
          f"{results['corrected']} corrected, "
          f"{results['already_set']} already set, "
          f"{results['no_slot_file']} missing .slot file")

    if not apply and results["updated"] > 0:
        print("\nRun with --apply to write changes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
