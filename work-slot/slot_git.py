"""Git clone infrastructure for slot management.

Clone creation, remote configuration, hooks, alternates, worktree migration.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from slot_core import (
    run_cmd, is_worktree, resolve_original_repo,
    _REGENERABLE_DIRS, _IDE_ARTIFACTS, get_all_slot_repos,
    _cleanup_remnant_dir, SLOT_DIR_NAME, LEGACY_SLOT_DIR_NAME,
)

_work_end = Path(__file__).parent.parent / "work-end"
if _work_end.exists():
    sys.path.insert(0, str(_work_end))
try:
    from common import detect_topology as _detect_topology
except ImportError:
    _detect_topology = None


def configure_slot_remotes(clone_path: Path, original_path: Path) -> dict[str, str]:
    """Reconfigure clone remotes: local=clone-source, origin=fork, upstream=blessed."""
    if _detect_topology is None:
        return {"origin": "", "upstream": "", "local": str(original_path)}

    fork_remote, blessed_remote = _detect_topology(str(original_path))
    if not fork_remote:
        return {"origin": "", "upstream": "", "local": str(original_path)}

    rc, fork_url, _ = run_cmd(
        ["git", "-C", str(original_path), "remote", "get-url", fork_remote])
    if rc != 0:
        return {"origin": "", "upstream": "", "local": str(original_path)}
    fork_url = fork_url.strip()

    run_cmd(["git", "-C", str(clone_path), "remote", "rename", "origin", "local"])
    run_cmd(["git", "-C", str(clone_path), "remote", "add", "origin", fork_url])
    run_cmd(["git", "-C", str(clone_path), "fetch", "origin"])
    run_cmd(["git", "-C", str(clone_path), "branch",
             "--set-upstream-to=origin/main", "main"])

    upstream_url = ""
    if blessed_remote:
        rc, blessed_url, _ = run_cmd(
            ["git", "-C", str(original_path), "remote", "get-url", blessed_remote])
        if rc == 0:
            upstream_url = blessed_url.strip()
            run_cmd(["git", "-C", str(clone_path), "remote", "add",
                     "upstream", upstream_url])

    return {"origin": fork_url, "upstream": upstream_url, "local": str(original_path)}


def configure_update_instead(original_path: Path) -> None:
    """Set receive.denyCurrentBranch=updateInstead on original repo."""
    run_cmd(["git", "-C", str(original_path), "config",
             "receive.denyCurrentBranch", "updateInstead"])


def install_post_commit_hook(clone_path: Path) -> None:
    """Install a post-commit hook that pushes to origin after every commit."""
    hooks_dir = clone_path / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_file = hooks_dir / "post-commit"
    if hook_file.exists():
        return
    hook_file.write_text("#!/bin/sh\ngit push -u origin HEAD 2>/dev/null || true\n")
    hook_file.chmod(0o755)


def sync_main(repo_path: str) -> None:
    """Fetch remote-tracking refs so git clone --shared sees latest main.

    Does NOT rebase or modify the local branch — the source repo may be
    on a feature branch. git clone --shared --branch main reads from
    origin/main (remote-tracking ref), not the local main branch.
    """
    rc, _, _ = run_cmd(["git", "-C", repo_path, "fetch", "origin"])
    if rc != 0:
        print(f"WARN=fetch_failed repo={repo_path}")
        return
    rc, _, _ = run_cmd(["git", "-C", repo_path, "remote", "get-url", "upstream"])
    if rc == 0:
        run_cmd(["git", "-C", repo_path, "fetch", "upstream"])


def _exclude_symlinks(clone_path: Path) -> None:
    exclude_file = clone_path / ".git" / "info" / "exclude"
    exclude_file.parent.mkdir(parents=True, exist_ok=True)
    entries = {"wksp", "proj", ".claude"}
    if exclude_file.exists():
        existing_lines = {
            line.strip() for line in exclude_file.read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        }
        entries -= existing_lines
    if entries:
        with open(exclude_file, "a") as f:
            for entry in sorted(entries):
                f.write(f"{entry}\n")


def _symlink_gitignored_assets(source_repo: Path, clone_dest: Path) -> list[str]:
    """Symlink gitignored asset directories from source into clone.
    Skips regenerable directories (node_modules, build output, IDE artifacts)."""
    linked: list[str] = []
    for entry in sorted(source_repo.iterdir()):
        if entry.name == ".git" or not entry.is_dir():
            continue
        if entry.name in _REGENERABLE_DIRS:
            continue
        clone_entry = clone_dest / entry.name
        if clone_entry.exists() or clone_entry.is_symlink():
            continue
        rc, _, _ = run_cmd(["git", "-C", str(source_repo), "check-ignore", "-q", entry.name])
        if rc == 0:
            clone_entry.symlink_to(str(entry.resolve()))
            linked.append(entry.name)
    return linked


def _repack_broken_alternates(slot_dir: Path, family_root: Path) -> int:
    """Scan sibling slots for git alternates referencing slot_dir; repack to sever."""
    slot_prefix = str(slot_dir) + "/"
    slots_root = slot_dir.parent
    repacked = 0

    for sibling in sorted(slots_root.iterdir()):
        if not sibling.is_dir() or sibling.name == "attic" or sibling == slot_dir:
            continue
        for repo_dir in sorted(sibling.iterdir()):
            alt_file = repo_dir / ".git" / "objects" / "info" / "alternates"
            if not alt_file.exists():
                continue
            lines = alt_file.read_text().strip().splitlines()
            remaining = [ln for ln in lines if not ln.startswith(slot_prefix)]
            if len(remaining) == len(lines):
                continue
            rc, _, err = run_cmd(
                ["git", "repack", "-a", "-d", "-l"],
                cwd=str(repo_dir),
            )
            if rc != 0:
                print(f"WARN=repack_failed repo={repo_dir} err={err.strip()}")
                continue
            if remaining:
                alt_file.write_text("\n".join(remaining) + "\n")
            else:
                alt_file.unlink()
            repacked += 1
            print(f"REPACKED={repo_dir.relative_to(slots_root)} (severed alternate to slot {slot_dir.name})")

    return repacked


def _migrate_worktree_to_clone(worktree_path: Path) -> bool:
    """Migrate a single worktree to a git clone --shared. Returns True on success."""
    branch_rc, branch_out, _ = run_cmd(
        ["git", "-C", str(worktree_path), "branch", "--show-current"]
    )
    branch = branch_out.strip() if branch_rc == 0 else ""
    if not branch:
        return False

    original = resolve_original_repo(worktree_path)
    if original == worktree_path:
        return False

    status_rc, status_out, _ = run_cmd(
        ["git", "-C", str(worktree_path), "status", "--short"]
    )
    if status_rc == 0 and status_out.strip():
        run_cmd(["git", "-C", str(worktree_path), "add", "-A"])
        run_cmd(["git", "-C", str(worktree_path), "commit", "-m", "WIP: pre-migration"])

    with tempfile.TemporaryDirectory() as tmpdir:
        clone_tmp = Path(tmpdir) / worktree_path.name
        rc, _, stderr = run_cmd([
            "git", "clone", "--shared", str(original), str(clone_tmp),
        ])
        if rc != 0:
            print(f"WARN=migration_clone_failed path={worktree_path} stderr={stderr.strip()}")
            return False

        rc, _, _ = run_cmd(["git", "-C", str(clone_tmp), "checkout", branch])
        if rc != 0:
            rc, _, _ = run_cmd(["git", "-C", str(clone_tmp), "checkout", "-b", branch, f"origin/{branch}"])
            if rc != 0:
                print(f"WARN=migration_branch_failed path={worktree_path} branch={branch}")
                return False

        orig_rc, orig_tree, _ = run_cmd(
            ["git", "-C", str(worktree_path), "rev-parse", "HEAD^{tree}"]
        )
        clone_rc, clone_tree, _ = run_cmd(
            ["git", "-C", str(clone_tmp), "rev-parse", "HEAD^{tree}"]
        )
        if orig_rc != 0 or clone_rc != 0 or orig_tree.strip() != clone_tree.strip():
            print(f"WARN=migration_tree_mismatch path={worktree_path}")
            return False

        rc, _, stderr = run_cmd(["git", "-C", str(original), "worktree", "remove", "--force", str(worktree_path)])
        if worktree_path.exists():
            _cleanup_remnant_dir(worktree_path)
        if rc != 0 and worktree_path.exists():
            print(f"WARN=migration_worktree_remove_failed path={worktree_path} stderr={stderr.strip()}")
            return False

        shutil.move(str(clone_tmp), str(worktree_path))
        _exclude_symlinks(worktree_path)

    return True


def ensure_clone_layout(slot_dir: Path) -> int:
    """Migrate any worktree repos in a slot to git clone --shared. Returns count migrated."""
    migrated = 0
    for sub in slot_dir.iterdir():
        if sub.is_dir() and (sub / ".git").exists() and is_worktree(sub):
            if _migrate_worktree_to_clone(sub):
                migrated += 1
                print(f"MIGRATED={sub.name}")
    return migrated
