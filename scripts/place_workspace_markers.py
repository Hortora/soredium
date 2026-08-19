#!/usr/bin/env python3
"""Place .workspace markers on all workspace clones across all slots.

Walks active and archived slots, identifies workspace clones using
current detection (name-based + proj symlink), and places .workspace
marker files. Idempotent — safe to run repeatedly.

Part of #255 Phase 1: detection bootstrap.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "work-slot"))
from slot_manager import is_project_repo


def place_markers(family_root: Path, include_attic: bool = True) -> dict:
    result = {"placed": 0, "already_marked": 0, "skipped": 0}
    slots_dir = family_root / "slots"
    if not slots_dir.is_dir():
        return result

    slot_dirs: list[Path] = []
    for entry in sorted(slots_dir.iterdir()):
        if entry.name == "attic":
            if include_attic and entry.is_dir():
                for archived in sorted(entry.iterdir()):
                    if archived.is_dir():
                        slot_dirs.append(archived)
            continue
        if entry.is_dir():
            slot_dirs.append(entry)

    for slot_dir in slot_dirs:
        for child in sorted(slot_dir.iterdir()):
            if not child.is_dir() or not (child / ".git").exists():
                continue
            if child.name in (".m2", "attic"):
                continue
            marker = child / ".workspace"
            if marker.exists():
                result["already_marked"] += 1
                continue
            if not is_project_repo(child.name) or (child / "proj").is_symlink():
                marker.touch()
                result["placed"] += 1
            else:
                result["skipped"] += 1

    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: place_workspace_markers.py <family-root>")
        sys.exit(1)
    root = Path(sys.argv[1])
    res = place_markers(root)
    print(f"Placed: {res['placed']}, Already marked: {res['already_marked']}, Skipped: {res['skipped']}")
