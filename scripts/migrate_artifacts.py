#!/usr/bin/env python3
"""
Migrate artifacts to canonical locations.

Project repos: root blog/, adr/, specs/ → docs/blog/, docs/adr/, docs/specs/
               docs/superpowers/specs/ → docs/specs/
               docs/superpowers/plans/ → docs/plans/

Workspace repos: docs/adr/, docs/specs/, docs/blog/ → root adr/, specs/, blog/
                 docs/superpowers/specs/ → root specs/
                 docs/superpowers/plans/ → root plans/

Usage:
    python3 migrate_artifacts.py <repo_path> --mode project|workspace [--dry-run]
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo)] + list(args),
        capture_output=True, text=True,
    )


def git_mv(repo: Path, src: Path, dst: Path) -> bool:
    dst.parent.mkdir(parents=True, exist_ok=True)
    result = git(repo, "mv", str(src.relative_to(repo)), str(dst.relative_to(repo)))
    return result.returncode == 0


def collect_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    files = []
    for item in sorted(directory.rglob("*")):
        if item.is_file():
            files.append(item)
    return files


def merge_dir(repo: Path, src_dir: Path, dst_dir: Path, dry_run: bool) -> int:
    moved = 0
    for src_file in collect_files(src_dir):
        rel = src_file.relative_to(src_dir)
        dst_file = dst_dir / rel
        if dst_file.exists():
            print(f"  SKIP (exists): {rel}")
            continue
        if dry_run:
            print(f"  MOVE: {src_file.relative_to(repo)} → {dst_file.relative_to(repo)}")
            moved += 1
        else:
            if git_mv(repo, src_file, dst_file):
                print(f"  MOVED: {src_file.relative_to(repo)} → {dst_file.relative_to(repo)}")
                moved += 1
            else:
                print(f"  FAIL: {src_file.relative_to(repo)}")
    return moved


def remove_empty_dirs(repo: Path, directory: Path, dry_run: bool) -> None:
    if not directory.is_dir():
        return
    for item in sorted(directory.rglob("*"), reverse=True):
        if item.is_dir() and not any(item.iterdir()):
            if dry_run:
                print(f"  RMDIR: {item.relative_to(repo)}")
            else:
                item.rmdir()
                print(f"  RMDIR: {item.relative_to(repo)}")
    if directory.is_dir() and not any(directory.iterdir()):
        if dry_run:
            print(f"  RMDIR: {directory.relative_to(repo)}")
        else:
            directory.rmdir()
            print(f"  RMDIR: {directory.relative_to(repo)}")


def migrate_project(repo: Path, dry_run: bool) -> int:
    total = 0

    for artifact in ("blog", "adr", "specs"):
        root_dir = repo / artifact
        docs_dir = repo / "docs" / artifact
        if root_dir.is_dir() and collect_files(root_dir):
            print(f"\n  {artifact}/ → docs/{artifact}/")
            total += merge_dir(repo, root_dir, docs_dir, dry_run)
            if not dry_run:
                remove_empty_dirs(repo, root_dir, dry_run)

    sp_specs = repo / "docs" / "superpowers" / "specs"
    if sp_specs.is_dir() and collect_files(sp_specs):
        print(f"\n  docs/superpowers/specs/ → docs/specs/")
        total += merge_dir(repo, sp_specs, repo / "docs" / "specs", dry_run)

    sp_plans = repo / "docs" / "superpowers" / "plans"
    if sp_plans.is_dir() and collect_files(sp_plans):
        print(f"\n  docs/superpowers/plans/ → docs/plans/")
        total += merge_dir(repo, sp_plans, repo / "docs" / "plans", dry_run)

    sp_dir = repo / "docs" / "superpowers"
    if sp_dir.is_dir():
        if not dry_run:
            remove_empty_dirs(repo, sp_dir, dry_run)
        else:
            print(f"\n  RMDIR: docs/superpowers/ (after moves)")

    return total


def migrate_workspace(repo: Path, dry_run: bool) -> int:
    total = 0

    for artifact in ("blog", "adr", "specs"):
        docs_dir = repo / "docs" / artifact
        root_dir = repo / artifact
        if docs_dir.is_dir() and collect_files(docs_dir):
            print(f"\n  docs/{artifact}/ → {artifact}/")
            total += merge_dir(repo, docs_dir, root_dir, dry_run)
            if not dry_run:
                remove_empty_dirs(repo, docs_dir, dry_run)

    sp_specs = repo / "docs" / "superpowers" / "specs"
    if sp_specs.is_dir() and collect_files(sp_specs):
        print(f"\n  docs/superpowers/specs/ → specs/")
        total += merge_dir(repo, sp_specs, repo / "specs", dry_run)

    sp_plans = repo / "docs" / "superpowers" / "plans"
    if sp_plans.is_dir() and collect_files(sp_plans):
        print(f"\n  docs/superpowers/plans/ → plans/")
        total += merge_dir(repo, sp_plans, repo / "plans", dry_run)

    sp_dir = repo / "docs" / "superpowers"
    if sp_dir.is_dir():
        if not dry_run:
            remove_empty_dirs(repo, sp_dir, dry_run)
        else:
            print(f"\n  RMDIR: docs/superpowers/ (after moves)")

    return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo_path", type=Path)
    parser.add_argument("--mode", choices=["project", "workspace"], required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    repo = args.repo_path.resolve()
    if not (repo / ".git").exists() and not (repo / ".git").is_file():
        print(f"ERROR: {repo} is not a git repository")
        return 1

    branch = git(repo, "branch", "--show-current")
    current = branch.stdout.strip()
    print(f"Repo: {repo}")
    print(f"Branch: {current}")
    print(f"Mode: {args.mode}")

    if args.dry_run:
        print("DRY RUN — no changes will be made\n")

    status = git(repo, "status", "--short")
    if status.stdout.strip():
        print(f"WARNING: working tree not clean:\n{status.stdout}")

    if args.mode == "project":
        total = migrate_project(repo, args.dry_run)
    else:
        total = migrate_workspace(repo, args.dry_run)

    if total == 0:
        print("\nNothing to migrate.")
        return 0

    if not args.dry_run:
        git(repo, "add", "-A")
        result = git(repo, "commit", "-m",
                     f"chore: migrate artifacts to canonical locations Refs Hortora/soredium#203")
        if result.returncode == 0:
            print(f"\nCommitted: {total} files migrated")
        else:
            print(f"\nCommit failed: {result.stderr}")
            return 1
    else:
        print(f"\nWould migrate: {total} files")

    return 0


if __name__ == "__main__":
    sys.exit(main())
