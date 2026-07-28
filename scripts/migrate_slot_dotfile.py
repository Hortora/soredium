#!/usr/bin/env python3
"""Rename SLOT.md to .slot across all slot directories.

SLOT.md files live on disk in slot root directories (worktrees/N/ and
worktrees/attic/N/), outside any git repo. Migration is a simple rename.

Usage:
    python3 scripts/migrate_slot_dotfile.py          # dry-run
    python3 scripts/migrate_slot_dotfile.py --apply   # rename files
"""
import argparse
import os
from pathlib import Path


def find_slot_md_files(search_root: Path) -> list[Path]:
    results = []
    for dirpath, _, filenames in os.walk(search_root):
        if ".git" in dirpath:
            continue
        if "SLOT.md" in filenames:
            results.append(Path(dirpath) / "SLOT.md")
    return sorted(results)


def migrate(search_root: Path, apply: bool) -> None:
    files = find_slot_md_files(search_root)
    if not files:
        print("No SLOT.md files found.")
        return

    print(f"Found {len(files)} SLOT.md file(s):\n")
    for f in files:
        target = f.parent / ".slot"
        rel = f.relative_to(search_root)
        if apply:
            f.rename(target)
            print(f"  ✓ {rel} → .slot")
        else:
            print(f"  {rel} → .slot (dry-run)")

    if not apply:
        print(f"\nDry run — {len(files)} file(s) would be renamed.")
        print("Run with --apply to rename.")
    else:
        print(f"\nDone — {len(files)} file(s) renamed.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Rename SLOT.md to .slot")
    parser.add_argument("--apply", action="store_true", help="Actually rename")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.home() / "claude",
        help="Search root (default: ~/claude)",
    )
    args = parser.parse_args()
    migrate(args.root, args.apply)


if __name__ == "__main__":
    main()
