#!/usr/bin/env python3
"""Recover artifacts lost to gitignore bug #148.

For each slot (active or archived), finds artifacts in gitignored workspace
subdirectories and copies them to the project repo's docs/ directory.

Usage:
    python3 recover_slot_artifacts.py [--dry-run] [<family-root> ...]

Modes:
    --dry-run   Show what would be recovered without making changes (default)
    --apply     Actually copy files and commit

Output:
    RECOVERED=<count>
    For each: RECOVER=<src> → <dst>
"""

import shutil
import subprocess
import sys
from pathlib import Path

ARTIFACT_DIRS = {"specs", "blog", "adr", "plans"}
INHERITED_BLOGS = {
    "2026-07-21-virtual-threads-retire-the-reactive-tier.md",
    "2026-07-21-mdp01-trust-workbench.md",
}


def find_workspace_clones(slot_dir: Path) -> list[Path]:
    clones = []
    if not slot_dir.exists():
        return clones
    for sub in slot_dir.iterdir():
        if not sub.is_dir() or not (sub / ".git").exists():
            continue
        if sub.name == "work" or sub.name.startswith("work-"):
            clones.append(sub)
    return clones


def check_gitignore_hides(ws_clone: Path) -> list[str]:
    gitignore = ws_clone / ".gitignore"
    if not gitignore.exists():
        return []
    hidden = []
    for line in gitignore.read_text().splitlines():
        stripped = line.strip().strip("/")
        if not stripped or stripped.startswith("#"):
            continue
        subdir = ws_clone / stripped
        if subdir.is_dir():
            hidden.append(stripped)
    return hidden


def find_lost_artifacts(ws_clone: Path, hidden_dirs: list[str]) -> list[dict]:
    lost = []
    for hidden in hidden_dirs:
        base = ws_clone / hidden
        for artifact_type in ARTIFACT_DIRS:
            artifact_dir = base / artifact_type
            if not artifact_dir.is_dir():
                continue
            for f in artifact_dir.rglob("*.md"):
                if f.name == "INDEX.md":
                    continue
                if f.name in INHERITED_BLOGS:
                    continue
                rel = str(f.relative_to(ws_clone))
                result = subprocess.run(
                    ["git", "-C", str(ws_clone), "ls-files", rel],
                    capture_output=True, text=True,
                )
                if not result.stdout.strip():
                    lost.append({
                        "src": f,
                        "type": artifact_type,
                        "subdir": hidden,
                        "rel": rel,
                    })
    return lost


def find_project_repo(family_root: Path, subdir_name: str) -> Path | None:
    candidate = family_root / subdir_name
    if candidate.is_dir() and (candidate / ".git").exists():
        return candidate
    return None


def resolve_dest(project_repo: Path, artifact_type: str, src: Path) -> Path:
    standard = project_repo / "docs" / artifact_type
    legacy = project_repo / "docs" / "superpowers" / artifact_type
    if legacy.is_dir() and not standard.is_dir():
        return legacy / src.name
    return standard / src.name


def recover_slot(slot_dir: Path, family_root: Path, dry_run: bool) -> list[dict]:
    recoveries = []
    ws_clones = find_workspace_clones(slot_dir)

    for ws_clone in ws_clones:
        hidden = check_gitignore_hides(ws_clone)
        if not hidden:
            continue
        lost = find_lost_artifacts(ws_clone, hidden)
        for item in lost:
            project_repo = find_project_repo(family_root, item["subdir"])
            if not project_repo:
                continue

            dest = resolve_dest(project_repo, item["type"], item["src"])
            if dest.exists():
                continue

            recoveries.append({
                "src": item["src"],
                "dst": dest,
                "type": item["type"],
                "project": item["subdir"],
            })

            if not dry_run:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(item["src"]), str(dest))

    return recoveries


def commit_recoveries(project_repos: dict[str, list[Path]], family_root: Path) -> int:
    committed = 0
    for project_name, files in project_repos.items():
        repo = family_root / project_name
        if not repo.is_dir():
            continue
        for f in files:
            rel = str(f.relative_to(repo))
            subprocess.run(
                ["git", "-C", str(repo), "add", rel],
                capture_output=True,
            )
        result = subprocess.run(
            ["git", "-C", str(repo), "commit", "-m",
             f"docs: recover {len(files)} artifacts from gitignored slot workspaces  Refs #148"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            committed += len(files)
            print(f"COMMITTED={project_name} files={len(files)}")
    return committed


def main() -> int:
    dry_run = "--apply" not in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    if args:
        family_roots = [Path(p) for p in args]
    else:
        family_roots = [
            Path.home() / "claude" / "casehub",
            Path.home() / "claude" / "hortora",
        ]

    all_recoveries: list[dict] = []
    by_project: dict[str, list[Path]] = {}

    for family_root in family_roots:
        worktrees = family_root / "worktrees"
        if not worktrees.exists():
            continue

        for slot_dir in sorted(worktrees.iterdir()):
            if not slot_dir.is_dir() or not slot_dir.name.isdigit():
                continue
            recoveries = recover_slot(slot_dir, family_root, dry_run)
            all_recoveries.extend(recoveries)
            for r in recoveries:
                by_project.setdefault(r["project"], []).append(r["dst"])

        attic = worktrees / "attic"
        if attic.exists():
            for slot_dir in sorted(attic.iterdir()):
                if not slot_dir.is_dir() or not slot_dir.name.isdigit():
                    continue
                recoveries = recover_slot(slot_dir, family_root, dry_run)
                all_recoveries.extend(recoveries)
                for r in recoveries:
                    by_project.setdefault(r["project"], []).append(r["dst"])

    if not all_recoveries:
        print("RECOVERED=0")
        print("All artifacts already in project repos or no recoverable items.")
        return 0

    mode = "DRY_RUN" if dry_run else "APPLIED"
    print(f"MODE={mode}")
    print(f"RECOVERABLE={len(all_recoveries)}")
    print()

    by_type: dict[str, int] = {}
    for r in all_recoveries:
        by_type[r["type"]] = by_type.get(r["type"], 0) + 1
        print(f"RECOVER={r['src']} → {r['dst']}")

    print()
    for t, c in sorted(by_type.items()):
        print(f"  {t}: {c}")

    if not dry_run:
        print()
        committed = commit_recoveries(by_project, family_roots[0])
        print(f"TOTAL_COMMITTED={committed}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
