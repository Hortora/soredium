"""Restructure slot/clone workspaces: one wksp/ per root, not per project.

For each slot/clone:
  1. Create wksp/ at the slot root (git-inited, no remotes)
  2. Replace each project clone's wksp/ dir with a symlink to ../wksp
  3. Copy any CLAUDE.md from the first project clone's old wksp/ to the root wksp/

Dry run by default. Pass --apply to execute.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def run(cmd):
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
    clones = []
    for d in sorted(slot_dir.iterdir()):
        if not d.is_dir() or not (d / ".git").exists():
            continue
        if d.name in (".m2", "attic", "wksp"):
            continue
        if (d / ".workspace").exists():
            continue
        clones.append(d)
    return clones


def _primary_repo(slot_dir: Path) -> str | None:
    slot_file = slot_dir / ".slot"
    if not slot_file.exists():
        return None
    in_repos = False
    for line in slot_file.read_text().splitlines():
        if line.strip() == "## Repos":
            in_repos = True
            continue
        if in_repos and line.startswith("- "):
            repo = line[2:].strip().split()[0]
            if "(primary)" in line or not any(l.startswith("- ") for l in slot_file.read_text().splitlines()[slot_file.read_text().splitlines().index(line)+1:] if l.startswith("- ")):
                pass
            return repo
        if in_repos and line.startswith("##"):
            break
    return None


def restructure_slot(slot_dir: Path, apply: bool) -> dict:
    stats = {"root_created": 0, "symlinks_created": 0, "dirs_removed": 0}

    project_clones = find_project_clones(slot_dir)
    if not project_clones:
        return stats

    root_wksp = slot_dir / "wksp"

    # Find primary repo from .slot file
    primary = _primary_repo(slot_dir)
    primary_clone = slot_dir / primary if primary else project_clones[0]

    if root_wksp.is_dir() and (root_wksp / ".git").exists():
        print(f"    root wksp/ already exists")
    elif root_wksp.is_symlink():
        print(f"    root wksp is a symlink — skipping")
        return stats
    else:
        print(f"    CREATE root wksp/ (proj -> {primary_clone.name})")
        stats["root_created"] = 1
        if apply:
            root_wksp.mkdir(exist_ok=True)
            run(["git", "init", "-q", str(root_wksp)])
            run(["git", "-C", str(root_wksp), "commit", "--allow-empty", "-m", "init workspace"])
            rc, branch, _ = run(["git", "-C", str(primary_clone), "symbolic-ref", "-q", "--short", "HEAD"])
            if rc == 0 and branch and branch not in ("main", "master"):
                run(["git", "-C", str(root_wksp), "checkout", "-b", branch])
            (root_wksp / ".workspace").write_text(f"project: {primary_clone}\n")
            proj = root_wksp / "proj"
            if not proj.exists():
                proj.symlink_to(os.path.relpath(primary_clone, root_wksp))

    for pc in project_clones:
        pc_wksp = pc / "wksp"

        if pc_wksp.is_symlink():
            target = os.readlink(str(pc_wksp))
            if target == "../wksp":
                continue
            print(f"    {pc.name}/wksp: symlink to {target} — repointing to ../wksp")
            stats["symlinks_created"] += 1
            if apply:
                pc_wksp.unlink()
                pc_wksp.symlink_to("../wksp")
        elif pc_wksp.is_dir() and (pc_wksp / ".git").exists():
            print(f"    {pc.name}/wksp: dir -> rename to wksp.old, symlink to ../wksp")
            stats["dirs_removed"] += 1
            stats["symlinks_created"] += 1
            if apply:
                claude_md = pc_wksp / "CLAUDE.md"
                root_claude = root_wksp / "CLAUDE.md"
                if claude_md.exists() and not root_claude.exists():
                    shutil.copy2(str(claude_md), str(root_claude))
                pc_wksp_old = pc / "wksp.old"
                pc_wksp.rename(pc_wksp_old)
                pc_wksp.symlink_to("../wksp")
        elif not pc_wksp.exists():
            print(f"    {pc.name}/wksp: creating symlink to ../wksp")
            stats["symlinks_created"] += 1
            if apply:
                pc_wksp.symlink_to("../wksp")

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
        args = ["--all"]

    if args[0] == "--all":
        families = find_all_families()
    else:
        families = [Path(args[0])]

    mode = "APPLY" if apply else "DRY RUN"
    print(f"Mode: {mode}")

    total = {"root_created": 0, "symlinks_created": 0, "dirs_removed": 0}

    for family in families:
        if not family.is_dir():
            continue
        slots = find_slot_dirs(family)
        print(f"\n=== Family: {family} ({len(slots)} slots) ===")
        for slot in slots:
            print(f"\n  Slot: {slot.name}")
            stats = restructure_slot(slot, apply)
            for k, v in stats.items():
                total[k] += v

    print(f"\n=== Summary ({mode}) ===")
    print(f"Root workspaces created: {total['root_created']}")
    print(f"Per-project dirs replaced with symlinks: {total['dirs_removed']}")
    print(f"Symlinks created/updated: {total['symlinks_created']}")

    if not apply and any(total.values()):
        print("\nRun with --apply to execute.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
