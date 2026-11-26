"""Disconnect workspace clones in existing slots and clones.

For each project clone that has a wksp symlink pointing to a sibling workspace
clone, replace it with a local wksp/ directory (git-inited, no remotes).

The old workspace clones stay on disk but are no longer referenced.

Dry run by default. Pass --apply to execute.

Usage:
    python3 scripts/disconnect_workspace_clones.py <family_root> [--apply]
    python3 scripts/disconnect_workspace_clones.py --all [--apply]
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str]) -> tuple[int, str, str]:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def find_slot_dirs(family_root: Path) -> list[Path]:
    found = []
    for subdir in ("slots", "clone"):
        d = family_root / subdir
        if not d.is_dir():
            continue
        for entry in sorted(d.iterdir()):
            if entry.is_dir() and (entry / ".slot").is_file():
                found.append(entry)
    return found


def find_project_clones(slot_dir: Path) -> list[Path]:
    """Project clones: dirs with .git that do NOT have .workspace marker."""
    clones = []
    for d in sorted(slot_dir.iterdir()):
        if not d.is_dir() or not (d / ".git").exists():
            continue
        if d.name in (".m2", "attic"):
            continue
        if (d / ".workspace").exists():
            continue
        clones.append(d)
    return clones


def disconnect_project(project_clone: Path, slot_dir: Path, apply: bool) -> bool:
    """Replace wksp symlink with a local wksp/ directory.

    Returns True if a change was made (or would be made in dry run).
    """
    wksp = project_clone / "wksp"

    # Already a directory (not a symlink) — already disconnected
    if wksp.is_dir() and not wksp.is_symlink():
        return False

    # No wksp at all — create a fresh one
    if not wksp.exists() and not wksp.is_symlink():
        print(f"  CREATE wksp/ -> {project_clone.name}")
        if apply:
            _create_local_workspace(project_clone, wksp)
        return True

    # wksp is a symlink — check if it points to a workspace clone
    if wksp.is_symlink():
        target = wksp.resolve()
        # Check if target is a workspace clone (sibling dir with .workspace marker)
        if target.is_dir() and (target / ".workspace").exists():
            print(f"  DISCONNECT {project_clone.name}/wksp -> {target.name}")
            if apply:
                wksp.unlink()
                _create_local_workspace(project_clone, wksp)
            return True
        # Symlink points elsewhere (e.g. canonical workspace in canonical repo) — leave it
        return False

    return False


def _create_local_workspace(project_clone: Path, wksp: Path) -> None:
    """Create a local wksp/ directory with git init, proj symlink, and CLAUDE.md."""
    wksp.mkdir(exist_ok=True)
    run(["git", "init", "-q", str(wksp)])

    # Initial commit so the repo is not bare
    run(["git", "-C", str(wksp), "commit", "--allow-empty", "-m", "init workspace"])

    # Check out matching branch if project clone is on one
    rc, branch, _ = run(["git", "-C", str(project_clone), "symbolic-ref", "-q", "--short", "HEAD"])
    if rc == 0 and branch and branch != "main" and branch != "master":
        run(["git", "-C", str(wksp), "checkout", "-b", branch])

    # .workspace marker
    (wksp / ".workspace").touch()

    # proj symlink -> parent (the project clone)
    proj = wksp / "proj"
    if not proj.exists():
        proj.symlink_to("..")

    # Exclude wksp from project clone's git
    exclude_file = project_clone / ".git" / "info" / "exclude"
    exclude_file.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude_file.read_text() if exclude_file.exists() else ""
    if "wksp" not in existing:
        with open(exclude_file, "a") as f:
            f.write("wksp\n")

    # Copy CLAUDE.md from the old workspace if it exists alongside
    slot_dir = project_clone.parent
    old_ws_dirs = [d for d in slot_dir.iterdir()
                   if d.is_dir() and d.name.startswith("wsp-") and (d / ".workspace").exists()]
    for old_ws in old_ws_dirs:
        old_claude = old_ws / "CLAUDE.md"
        if old_claude.exists():
            shutil.copy2(str(old_claude), str(wksp / "CLAUDE.md"))
            break


def remove_workspace_remotes(slot_dir: Path, apply: bool) -> int:
    """Remove local remote and updateInstead from workspace clones so they
    can't accidentally push even if something references them."""
    count = 0
    for d in sorted(slot_dir.iterdir()):
        if not d.is_dir() or not (d / ".workspace").exists():
            continue
        if not (d / ".git").exists():
            continue
        rc, remotes, _ = run(["git", "-C", str(d), "remote"])
        if rc == 0 and "local" in remotes.split():
            print(f"  REMOVE remote 'local' from {d.name}")
            if apply:
                run(["git", "-C", str(d), "remote", "remove", "local"])
            count += 1
    return count


def migrate_slot(slot_dir: Path, apply: bool) -> dict:
    stats = {"disconnected": 0, "created": 0, "remotes_removed": 0}

    project_clones = find_project_clones(slot_dir)
    for pc in project_clones:
        result = disconnect_project(pc, slot_dir, apply)
        if result:
            wksp = pc / "wksp"
            if wksp.is_symlink():
                stats["disconnected"] += 1
            else:
                stats["created"] += 1

    stats["remotes_removed"] = remove_workspace_remotes(slot_dir, apply)
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
        print("usage: disconnect_workspace_clones.py <family_root|--all> [--apply]")
        return 1

    if args[0] == "--all":
        families = find_all_families()
    else:
        families = [Path(args[0])]

    mode = "APPLY" if apply else "DRY RUN"
    print(f"Mode: {mode}")

    total = {"disconnected": 0, "created": 0, "remotes_removed": 0}

    for family in families:
        if not family.is_dir():
            print(f"WARNING: {family} not found, skipping")
            continue
        slots = find_slot_dirs(family)
        print(f"\n=== Family: {family} ({len(slots)} slots) ===")
        for slot in slots:
            print(f"\n  Slot: {slot.name}")
            stats = migrate_slot(slot, apply)
            for k, v in stats.items():
                total[k] += v

    print(f"\n=== Summary ({mode}) ===")
    print(f"wksp symlinks disconnected: {total['disconnected']}")
    print(f"wksp dirs created (no prior wksp): {total['created']}")
    print(f"Workspace clone remotes removed: {total['remotes_removed']}")

    if not apply and any(total.values()):
        print("\nRun with --apply to execute.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
