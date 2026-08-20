#!/usr/bin/env python3
"""Migrate old-structure slots (family workspace clone) to per-repo workspaces.

Standalone function callable from any lifecycle boundary: session start,
work-end, wrap/handover. Idempotent with resume via .migration-progress.

Part of #255 Phase 2: active slot migration.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "work-slot"))
from slot_manager import (
    get_slot_repos, is_workspace_clone, resolve_workspace_source,
    repoint_wksp, create_proj_symlink,
)


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def _get_branch(repo_path: Path) -> str:
    r = _run(["git", "-C", str(repo_path), "branch", "--show-current"])
    return r.stdout.strip() if r.returncode == 0 else ""


def _find_old_workspace_clones(slot_dir: Path) -> list[Path]:
    """Find family workspace clones (old structure) in a slot."""
    clones = []
    for child in sorted(slot_dir.iterdir()):
        if not child.is_dir() or not (child / ".git").exists():
            continue
        if child.name in (".m2", "attic"):
            continue
        if is_workspace_clone(child) and (child.name == "work" or child.name.startswith("work-")):
            clones.append(child)
    return clones


def needs_migration(slot_dir: Path) -> bool:
    return len(_find_old_workspace_clones(slot_dir)) > 0


def _read_progress(slot_dir: Path) -> set[str]:
    progress_file = slot_dir / ".migration-progress"
    if not progress_file.exists():
        return set()
    done = set()
    for line in progress_file.read_text().splitlines():
        if "=complete" in line:
            done.add(line.split("=")[0].strip())
    return done


def _record_progress(slot_dir: Path, repo_name: str) -> None:
    progress_file = slot_dir / ".migration-progress"
    with open(progress_file, "a") as f:
        f.write(f"{repo_name}=complete\n")


def _resolve_original_workspace(repo_name: str, family_root: Path) -> tuple[Path, str] | None:
    """Find the original workspace repo for a project by following the
    original project's wksp symlink (not the slot clone's)."""
    original_project = family_root / repo_name
    if not original_project.is_dir():
        return None
    return resolve_workspace_source(original_project)


def _replay_branch_commits(family_ws_clone: Path, subdir_name: str,
                           new_ws_clone: Path, branch: str) -> list[str]:
    """Replay commits from the family workspace clone's subdir into the
    new per-repo workspace clone using format-patch --relative."""
    errors = []

    with tempfile.TemporaryDirectory() as patch_dir:
        r = _run([
            "git", "-C", str(family_ws_clone), "format-patch",
            f"--relative={subdir_name}/",
            f"main..{branch}",
            "--output-directory", patch_dir,
            "--", f"{subdir_name}/",
        ])

        patches = sorted(Path(patch_dir).glob("*.patch"))
        if not patches:
            return errors

        r = _run(["git", "-C", str(new_ws_clone), "am"] + [str(p) for p in patches])
        if r.returncode != 0:
            _run(["git", "-C", str(new_ws_clone), "am", "--abort"])
            errors.append(f"git am failed for {subdir_name}: {r.stderr.strip()}")

    return errors


def migrate_slot(slot_dir: Path, family_root: Path,
                 dry_run: bool = False) -> dict:
    result = {"status": "", "repos_migrated": [], "errors": []}

    old_ws_clones = _find_old_workspace_clones(slot_dir)
    if not old_ws_clones:
        result["status"] = "already_migrated"
        return result

    project_repos = get_slot_repos(slot_dir)
    done = _read_progress(slot_dir)
    branch = _get_branch(old_ws_clones[0])

    pending = [r for r in project_repos if r not in done]
    if not pending:
        result["status"] = "already_migrated"
        return result

    if dry_run:
        result["status"] = "would_migrate"
        result["repos_migrated"] = pending
        return result

    for repo_name in pending:
        ws_info = _resolve_original_workspace(repo_name, family_root)
        if not ws_info:
            result["errors"].append(f"{repo_name}: no workspace found")
            continue

        ws_source, ws_slot_name = ws_info
        new_ws_dir = slot_dir / ws_slot_name

        if new_ws_dir.exists() and (new_ws_dir / ".git").exists():
            new_branch = _get_branch(new_ws_dir)
            if new_branch == branch:
                _record_progress(slot_dir, repo_name)
                result["repos_migrated"].append(repo_name)
                continue

        if new_ws_dir.exists():
            import shutil
            shutil.rmtree(new_ws_dir)

        r = _run(["git", "clone", "--shared", "--branch", "main",
                   str(ws_source), str(new_ws_dir)])
        if r.returncode != 0:
            result["errors"].append(f"{repo_name}: clone failed: {r.stderr.strip()}")
            continue

        r = _run(["git", "-C", str(new_ws_dir), "checkout", "-b", branch])
        if r.returncode != 0:
            result["errors"].append(f"{repo_name}: branch create failed")
            continue

        for old_ws in old_ws_clones:
            subdir = old_ws / repo_name
            if subdir.is_dir() and not subdir.is_symlink():
                errs = _replay_branch_commits(old_ws, repo_name, new_ws_dir, branch)
                result["errors"].extend(errs)
                break

        (new_ws_dir / ".workspace").touch()

        repoint_wksp(slot_dir / repo_name, new_ws_dir)
        create_proj_symlink(new_ws_dir, slot_dir / repo_name)

        for old_ws in old_ws_clones:
            old_subdir = old_ws / repo_name
            if old_subdir.is_dir() and not old_subdir.is_symlink():
                import shutil
                shutil.rmtree(old_subdir)
                rel = os.path.relpath(new_ws_dir, old_ws)
                old_subdir.symlink_to(rel)

        _record_progress(slot_dir, repo_name)
        result["repos_migrated"].append(repo_name)

    for old_ws in old_ws_clones:
        r = _run(["git", "-C", str(old_ws), "add", "-A"])
        r2 = _run(["git", "-C", str(old_ws), "diff", "--cached", "--quiet"])
        if r2.returncode != 0:
            _run(["git", "-C", str(old_ws), "commit", "-m",
                  "chore: migration — subdirs replaced with symlinks to per-repo clones"])

    result["status"] = "migrated"
    return result


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: migrate_slot_workspace.py <slot-dir> <family-root> [--dry-run]")
        sys.exit(1)
    slot = Path(sys.argv[1])
    family = Path(sys.argv[2])
    dry = "--dry-run" in sys.argv
    res = migrate_slot(slot, family, dry_run=dry)
    print(f"Status: {res['status']}")
    if res["repos_migrated"]:
        print(f"Migrated: {', '.join(res['repos_migrated'])}")
    if res["errors"]:
        for e in res["errors"]:
            print(f"Error: {e}")
