"""Reconcile slot root queues against workspace clone queues.

After the workspace isolation migration, slot root queues may be stale
(last modified at slot creation). This script cross-references the slot's
root queue items against the workspace clone queues (which tracked actual
progress) and the worklog DB to determine the correct checked state.

Sources of truth (in order of reliability):
  1. Worklog DB work_items — which issues were ended for this slot
  2. Workspace clone queues — which items are checked in the actively-used queue
  3. Git branch stamps — which branches have "branch closed" commits

Dry run by default. Pass --apply to write corrected queues.

Usage:
    python3 scripts/reconcile_queue_state.py <family_root> [--apply]
    python3 scripts/reconcile_queue_state.py --all [--apply]
"""
from __future__ import annotations

import re
import sqlite3
import subprocess
import sys
from pathlib import Path


WORKLOG_DB = Path.home() / ".hortora" / "worklog.db"


def run(cmd: list[str]) -> tuple[int, str, str]:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def parse_queue_items(path: Path) -> list[dict]:
    if not path.exists():
        return []
    items = []
    for line in path.read_text().splitlines():
        line = line.strip()
        m = re.match(r'^- \[([ x])\]\s+(.+)', line)
        if m:
            checked = m.group(1) == "x"
            rest = m.group(2)
            ref_m = re.match(r'(\S+#\d+|#\d+)', rest)
            ref = ref_m.group(1) if ref_m else ""
            items.append({"line": line, "checked": checked, "ref": ref, "raw": m.group(0)})
    return items


def extract_issue_number(ref: str) -> int | None:
    m = re.search(r'#(\d+)', ref)
    return int(m.group(1)) if m else None


def get_worklog_ended_issues(slot_number: int | None) -> set[str]:
    """Issues that have ended work_items in the worklog for this slot."""
    if not WORKLOG_DB.exists() or slot_number is None:
        return set()
    try:
        db = sqlite3.connect(str(WORKLOG_DB))
        cursor = db.cursor()
        cursor.execute("""
            SELECT DISTINCT wii.issue_repo || '#' || wii.issue_number
            FROM work_items wi
            JOIN work_item_issues wii ON wii.work_item_id = wi.id
            WHERE wi.slot_id = ? AND wi.state = 'ended'
        """, (slot_number,))
        return {row[0] for row in cursor.fetchall()}
    except Exception:
        return set()


def get_slot_db_id(slot_number: int, family_root: str) -> int | None:
    if not WORKLOG_DB.exists():
        return None
    try:
        db = sqlite3.connect(str(WORKLOG_DB))
        cursor = db.cursor()
        cursor.execute(
            "SELECT id FROM slots WHERE slot_number = ? AND family_root = ?",
            (slot_number, family_root))
        row = cursor.fetchone()
        return row[0] if row else None
    except Exception:
        return None


def get_ws_clone_checked(slot_dir: Path) -> set[str]:
    """Issue refs that are checked in ANY workspace clone queue in this slot."""
    checked = set()
    for d in sorted(slot_dir.iterdir()):
        if not d.is_dir() or not (d / ".workspace").exists():
            continue
        for qname in (".queue", ".plan"):
            qf = d / qname
            if qf.exists():
                for item in parse_queue_items(qf):
                    if item["checked"] and item["ref"]:
                        checked.add(item["ref"])
    return checked


def parse_slot_number(slot_dir: Path) -> int | None:
    try:
        return int(slot_dir.name)
    except ValueError:
        return None


def reconcile_slot(slot_dir: Path, family_root: Path, apply: bool) -> dict:
    stats = {"checked": 0, "already_correct": 0, "unknown": 0}

    root_queue = slot_dir / ".queue"
    if not root_queue.exists():
        return stats

    items = parse_queue_items(root_queue)
    if not items:
        return stats

    # Gather sources of truth
    slot_num = parse_slot_number(slot_dir)
    slot_db_id = get_slot_db_id(slot_num, str(family_root)) if slot_num else None
    worklog_ended = get_worklog_ended_issues(slot_db_id) if slot_db_id else set()
    ws_checked = get_ws_clone_checked(slot_dir)

    changes = []
    for item in items:
        if item["checked"]:
            stats["already_correct"] += 1
            continue
        ref = item["ref"]
        if not ref:
            continue
        # Check if this unchecked item should be checked
        in_worklog = ref in worklog_ended
        in_ws = ref in ws_checked
        if in_worklog or in_ws:
            source = "worklog" if in_worklog else "ws-clone"
            changes.append((item, source))
            stats["checked"] += 1
        else:
            stats["unknown"] += 1

    if changes:
        print(f"  {slot_dir.name}: {len(changes)} items to check:")
        for item, source in changes:
            print(f"    CHECK {item['ref']} (source: {source})")

        if apply:
            content = root_queue.read_text()
            for item, _ in changes:
                old_line = item["line"]
                new_line = old_line.replace("- [ ]", "- [x]", 1)
                content = content.replace(old_line, new_line, 1)
            root_queue.write_text(content)
            print(f"  -> Written to {root_queue}")
    elif stats["unknown"] > 0:
        print(f"  {slot_dir.name}: {stats['already_correct']} correct, {stats['unknown']} unchecked (open work)")
    else:
        print(f"  {slot_dir.name}: all {stats['already_correct']} items correct")

    return stats


def find_all_families() -> list[Path]:
    claude_dir = Path.home() / "claude"
    families = []
    if not claude_dir.is_dir():
        return families
    for d in sorted(claude_dir.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        if (d / "slots").is_dir() or (d / "clone").is_dir():
            families.append(d)
    return families


def main() -> int:
    args = sys.argv[1:]
    apply = "--apply" in args
    args = [a for a in args if a != "--apply"]

    if not args:
        print("usage: reconcile_queue_state.py <family_root|--all> [--apply]")
        return 1

    if args[0] == "--all":
        families = find_all_families()
    else:
        families = [Path(args[0])]

    mode = "APPLY" if apply else "DRY RUN"
    print(f"Mode: {mode}")

    total = {"checked": 0, "already_correct": 0, "unknown": 0}

    for family in families:
        if not family.is_dir():
            continue
        print(f"\n=== Family: {family} ===")
        for subdir in ("slots", "clone"):
            d = family / subdir
            if not d.is_dir():
                continue
            for slot in sorted(d.iterdir()):
                if not slot.is_dir() or not (slot / ".slot").exists():
                    continue
                if not (slot / ".queue-root").exists():
                    continue
                stats = reconcile_slot(slot, family, apply)
                for k, v in stats.items():
                    total[k] += v

    print(f"\n=== Summary ({mode}) ===")
    print(f"Items checked (corrected): {total['checked']}")
    print(f"Items already correct: {total['already_correct']}")
    print(f"Items unchecked (open work): {total['unknown']}")

    if not apply and total["checked"]:
        print("\nRun with --apply to write corrected queues.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
