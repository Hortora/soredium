"""Workspace discovery, symlink management, and CLAUDE.md replication for slots."""

import os
import shutil
from pathlib import Path

from slot_core import (
    run_cmd, is_workspace_clone, get_slot_repos, resolve_original_repo,
    SlotCreationError,
)


def validate_slot_wksp(slot_dir: Path, repo_names: list[str] | None = None) -> list[str]:
    """Validate wksp/ symlinks in slot repo clones.
    Returns list of failure descriptions (empty = all OK)."""
    failures: list[str] = []
    names = repo_names if repo_names is not None else get_slot_repos(slot_dir)
    for repo_name in names:
        clone = slot_dir / repo_name
        if not clone.is_dir() or not (clone / ".git").exists():
            continue
        original = resolve_original_repo(clone)
        original_wksp = original / "wksp"
        if not original_wksp.is_symlink():
            continue
        clone_wksp = clone / "wksp"
        if not clone_wksp.is_symlink():
            failures.append(f"{repo_name}: wksp/ symlink missing")
        elif not clone_wksp.resolve().exists():
            failures.append(f"{repo_name}: wksp/ symlink dangling -> {clone_wksp.resolve()}")
    return failures


def resolve_workspace_source(repo_path: Path) -> tuple[Path, str] | None:
    wksp = repo_path / "wksp"
    if not wksp.is_symlink():
        return None
    target = wksp.resolve()
    if not target.is_dir():
        return None

    target_str = str(target)
    if "/slots/" in target_str or "/worktrees/" in target_str:
        return None

    rc, stdout, _ = run_cmd(["git", "-C", str(target), "rev-parse", "--show-toplevel"])
    if rc != 0:
        return None
    ws_root = Path(stdout.strip())

    rc, url_out, _ = run_cmd(["git", "-C", str(ws_root), "remote", "get-url", "origin"])
    if rc == 0 and url_out.strip():
        name = Path(url_out.strip().rstrip("/")).stem
        return ws_root, name

    parent_name = ws_root.parent.name
    return ws_root, f"wsp-{parent_name}-{ws_root.name}"


def discover_workspace(repo_path: Path) -> tuple[Path, str] | None:
    """Fallback workspace discovery when wksp symlink is missing."""
    repo_name = repo_path.name
    family_name = repo_path.parent.name

    candidates: list[Path] = []

    public_ws = Path.home() / "claude" / "public" / family_name / repo_name
    if public_ws.is_dir():
        candidates.append(public_ws)

    for sibling in repo_path.parent.iterdir():
        if not sibling.is_dir() or sibling == repo_path:
            continue
        proj = sibling / "proj"
        if proj.is_symlink():
            try:
                if proj.resolve() == repo_path.resolve():
                    candidates.append(sibling)
            except OSError:
                pass

    for candidate in candidates:
        rc, stdout, _ = run_cmd(["git", "-C", str(candidate), "rev-parse", "--show-toplevel"])
        if rc != 0:
            continue
        ws_root = Path(stdout.strip())
        rc, url_out, _ = run_cmd(["git", "-C", str(ws_root), "remote", "get-url", "origin"])
        if rc == 0 and url_out.strip():
            name = Path(url_out.strip().rstrip("/")).stem
            return ws_root, name
        return ws_root, f"wsp-{family_name}-{repo_name}"

    return None


def _unignore_subdir(ws_clone: Path, subdir_name: str) -> None:
    """Remove a gitignore entry that hides a workspace subdirectory in a slot clone."""
    gitignore = ws_clone / ".gitignore"
    if not gitignore.exists():
        return
    lines = gitignore.read_text().splitlines()
    patterns_to_remove = {f"/{subdir_name}", subdir_name, f"/{subdir_name}/"}
    filtered = [line for line in lines if line.strip() not in patterns_to_remove]
    if len(filtered) != len(lines):
        gitignore.write_text("\n".join(filtered) + "\n" if filtered else "")


def repoint_wksp(repo_worktree: Path, ws_subdir: Path) -> None:
    repo_str = str(repo_worktree)
    if "/slots/" not in repo_str and "/worktrees/" not in repo_str:
        raise SlotCreationError(
            f"repoint_wksp_on_original repo={repo_worktree}: "
            f"Refusing to modify wksp symlink in a non-slot directory. "
            f"This would corrupt the original repo's workspace link.")
    wksp = repo_worktree / "wksp"
    if wksp.is_symlink() or wksp.exists():
        wksp.unlink()
    rel = os.path.relpath(ws_subdir, repo_worktree)
    wksp.symlink_to(rel)


def create_proj_symlink(ws_subdir: Path, repo_worktree: Path) -> None:
    proj = ws_subdir / "proj"
    if proj.is_symlink() or proj.exists():
        proj.unlink()
    rel = os.path.relpath(repo_worktree, ws_subdir)
    proj.symlink_to(rel)


def replicate_claude_md(repo_path: Path, ws_subdir: Path, repo_worktree: Path) -> None:
    orig_wksp = repo_path / "wksp"
    if not orig_wksp.is_symlink():
        return
    orig_ws_target = orig_wksp.resolve()
    orig_claude = orig_ws_target / "CLAUDE.md"
    if not orig_claude.exists():
        return

    ws_claude = ws_subdir / "CLAUDE.md"
    proj_claude = repo_worktree / "CLAUDE.md"

    if orig_claude.is_symlink():
        if not ws_claude.exists():
            ws_claude.symlink_to("proj/CLAUDE.md")
    else:
        if not ws_claude.exists():
            shutil.copy2(str(orig_claude), str(ws_claude))
        if not proj_claude.exists():
            proj_claude.symlink_to("wksp/CLAUDE.md")
