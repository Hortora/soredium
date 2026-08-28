#!/usr/bin/env python3
"""Fix gitignore in all active slots retroactively.

Usage:
    python3 fix_active_slots.py [<family-root>]

Removes gitignore entries that hide workspace subdirectories in existing
slot clones. Only affects active slots (not attic).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "work-slot"))
from slot_workspace import _unignore_subdir


def main() -> int:
    if len(sys.argv) > 1:
        family = Path(sys.argv[1])
    else:
        family = Path.home() / "claude" / "casehub"

    worktrees = family / "worktrees"
    if not worktrees.exists():
        print("No worktrees directory found.")
        return 0

    fixed = 0
    for slot_dir in sorted(worktrees.iterdir()):
        if not slot_dir.is_dir() or not slot_dir.name.isdigit():
            continue
        for sub in slot_dir.iterdir():
            if not sub.is_dir() or not (sub / ".git").exists():
                continue
            if not (sub.name == "work" or sub.name.startswith("work-")):
                continue
            gitignore = sub / ".gitignore"
            if not gitignore.exists():
                continue
            lines = gitignore.read_text().splitlines()
            for line in lines:
                stripped = line.strip().strip("/")
                if not stripped or stripped.startswith("#"):
                    continue
                subdir = sub / stripped
                if subdir.is_dir():
                    _unignore_subdir(sub, stripped)
                    print(f"FIXED slot {slot_dir.name}/{sub.name}: removed /{stripped}")
                    fixed += 1

    print(f"TOTAL_FIXED={fixed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
