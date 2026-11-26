"""Migrate slots and canonical workspaces to the no-workspace-clone model.

Three actions:
  1. Add .queue-root to every slot that lacks it
  2. Remove receive.denyCurrentBranch=updateInstead from canonical workspace repos
  3. Clean stale slot state (.pause-stack, .work-progress) from canonical workspaces

Dry run by default. Pass --apply to execute.

Usage:
    python3 scripts/migrate_workspace_isolation.py <family_root> [--apply]
    python3 scripts/migrate_workspace_isolation.py --all [--apply]
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def run(cmd: list[str]) -> tuple[int, str, str]:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def find_slots(family_root: Path) -> list[Path]:
    slots_dir = family_root / "slots"
    found = []
    if slots_dir.is_dir():
        for d in sorted(slots_dir.iterdir()):
            if d.is_dir() and (d / ".slot").is_file():
                found.append(d)
    clone_dir = family_root / "clone"
    if clone_dir.is_dir():
        for d in sorted(clone_dir.iterdir()):
            if d.is_dir() and (d / ".slot").is_file():
                found.append(d)
    return found


def find_workspace_canonicals(family_root: Path) -> list[Path]:
    """Find canonical workspace repos by following wksp symlinks from canonical project repos."""
    found = []
    for d in sorted(family_root.iterdir()):
        if not d.is_dir() or d.name in ("slots", "clone", "attic", ".git"):
            continue
        wksp = d / "wksp"
        if wksp.is_symlink():
            target = wksp.resolve()
            if target.is_dir() and (target / ".git").exists():
                if target not in found:
                    found.append(target)
    return found


def add_queue_root(slot_dir: Path, apply: bool) -> bool:
    marker = slot_dir / ".queue-root"
    if marker.exists():
        return False
    print(f"  ADD .queue-root -> {slot_dir}")
    if apply:
        marker.write_text(f"# Isolate queue to slot root\ncreated_by: migrate_workspace_isolation\n")
    return True


def remove_update_instead(ws_canonical: Path, apply: bool) -> bool:
    rc, val, _ = run(["git", "-C", str(ws_canonical), "config", "--get",
                      "receive.denyCurrentBranch"])
    if rc != 0 or val != "updateInstead":
        return False
    print(f"  REMOVE updateInstead -> {ws_canonical}")
    if apply:
        run(["git", "-C", str(ws_canonical), "config", "--unset",
             "receive.denyCurrentBranch"])
    return True


def clean_stale_state(ws_canonical: Path, apply: bool) -> list[str]:
    cleaned = []
    for name in (".pause-stack", ".work-progress", ".close-state",
                 ".wrap-log.jsonl", ".land-ledger.jsonl"):
        f = ws_canonical / name
        if f.exists():
            print(f"  CLEAN {name} -> {ws_canonical}")
            if apply:
                f.unlink()
            cleaned.append(name)
    return cleaned


def clean_backup_refs(ws_canonical: Path, apply: bool) -> int:
    rc, refs, _ = run(["git", "-C", str(ws_canonical), "for-each-ref",
                       "--format=%(refname)", "refs/backup/"])
    if rc != 0 or not refs:
        return 0
    ref_list = refs.splitlines()
    count = len(ref_list)
    if count:
        print(f"  CLEAN {count} backup refs -> {ws_canonical}")
        if apply:
            for ref in ref_list:
                run(["git", "-C", str(ws_canonical), "update-ref", "-d", ref])
    return count


def migrate_family(family_root: Path, apply: bool) -> dict:
    stats = {"slots_updated": 0, "updateInstead_removed": 0,
             "files_cleaned": 0, "refs_cleaned": 0}

    print(f"\n=== Family: {family_root} ===")

    # 1. Add .queue-root to slots
    slots = find_slots(family_root)
    print(f"\nSlots: {len(slots)}")
    for slot in slots:
        if add_queue_root(slot, apply):
            stats["slots_updated"] += 1

    # 2. Remove updateInstead from workspace canonicals
    ws_canonicals = find_workspace_canonicals(family_root)
    print(f"\nWorkspace canonicals: {len(ws_canonicals)}")
    for ws in ws_canonicals:
        if remove_update_instead(ws, apply):
            stats["updateInstead_removed"] += 1

    # 3. Clean stale state from workspace canonicals
    for ws in ws_canonicals:
        cleaned = clean_stale_state(ws, apply)
        stats["files_cleaned"] += len(cleaned)
        refs = clean_backup_refs(ws, apply)
        stats["refs_cleaned"] += refs

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
    for d in sorted((claude_dir / "public").iterdir()) if (claude_dir / "public").is_dir() else []:
        if d.is_dir() and not d.name.startswith("."):
            if (d / "slots").is_dir() or (d / "clone").is_dir():
                families.append(d)
    return families


def main() -> int:
    args = sys.argv[1:]
    apply = "--apply" in args
    args = [a for a in args if a != "--apply"]

    if not args:
        print("usage: migrate_workspace_isolation.py <family_root|--all> [--apply]")
        return 1

    if args[0] == "--all":
        families = find_all_families()
        if not families:
            print("No families found")
            return 1
    else:
        families = [Path(args[0])]

    mode = "APPLY" if apply else "DRY RUN"
    print(f"Mode: {mode}")

    total = {"slots_updated": 0, "updateInstead_removed": 0,
             "files_cleaned": 0, "refs_cleaned": 0}

    for family in families:
        if not family.is_dir():
            print(f"WARNING: {family} not found, skipping")
            continue
        stats = migrate_family(family, apply)
        for k, v in stats.items():
            total[k] += v

    print(f"\n=== Summary ({mode}) ===")
    print(f"Slots with .queue-root added: {total['slots_updated']}")
    print(f"updateInstead removed: {total['updateInstead_removed']}")
    print(f"Stale files cleaned: {total['files_cleaned']}")
    print(f"Backup refs cleaned: {total['refs_cleaned']}")

    if not apply and any(total.values()):
        print("\nRun with --apply to execute these changes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
