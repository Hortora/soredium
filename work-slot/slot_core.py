"""slot_core.py — Shared utilities, resolution helpers, and constants for slot modules."""

import os
import shutil
import subprocess
import sys
from pathlib import Path


_IDE_ARTIFACTS = {".idea", ".run", ".settings", ".project", ".classpath", ".vscode"}

_REGENERABLE_DIRS = {
    "node_modules", ".gradle", "build", "dist", "target", "out",
    ".next", ".nuxt", ".cache", ".parcel-cache", ".turbo",
    *_IDE_ARTIFACTS,
}

SLOT_DIR_NAME = "slots"
LEGACY_SLOT_DIR_NAME = "worktrees"


class SlotCreationError(Exception):
    pass


def run_cmd(args: list[str], cwd: str | None = None) -> tuple[int, str, str]:
    result = subprocess.run(args, capture_output=True, text=True, cwd=cwd)
    return result.returncode, result.stdout, result.stderr


def _resolve_slots_dir(family_root: Path) -> Path:
    """Return the slots directory, preferring slots/ over legacy worktrees/."""
    new = family_root / SLOT_DIR_NAME
    old = family_root / LEGACY_SLOT_DIR_NAME
    if new.exists():
        return new
    if old.exists():
        return old
    return new


def _resolve_slot_dir_for_number(family_root: Path, slot_num: int) -> Path:
    """Find a specific slot by number, checking slots/ then worktrees/."""
    for name in (SLOT_DIR_NAME, LEGACY_SLOT_DIR_NAME):
        candidate = family_root / name / str(slot_num)
        if candidate.exists():
            return candidate
    return family_root / SLOT_DIR_NAME / str(slot_num)


def _get_family_repo_names(family_root: Path) -> set[str]:
    """Return names of all top-level git directories in the family root."""
    excluded = {"slots", "worktrees", "attic", ".m2"}
    names: set[str] = set()
    if not family_root.is_dir():
        return names
    for entry in family_root.iterdir():
        if not entry.is_dir() or entry.name in excluded or entry.name.startswith("."):
            continue
        if (entry / ".git").exists() or (entry / ".git").is_file():
            names.add(entry.name)
    return names


def is_slot_path(path: str) -> bool:
    """Check if a path is inside a slot directory (not a git/Claude Code worktree)."""
    if "/slots/" in path:
        return True
    if "/worktrees/" in path and "/.claude/worktrees/" not in path and "/.worktrees/" not in path:
        return True
    return False


def is_project_repo(name: str) -> bool:
    if name in (".m2", "attic"):
        return False
    if name == "work" or name.startswith("work-"):
        return False
    return True


def is_workspace_clone(repo_path: Path) -> bool:
    """Detect whether a repo clone is a workspace (not a project repo).

    Primary: .workspace marker file (#239, #255).
    Transition fallback (remove after #255 Phase 3): proj symlink, work-* naming.
    """
    if not repo_path.is_dir():
        return False
    if (repo_path / ".workspace").exists():
        return True
    if (repo_path / "proj").is_symlink():
        return True
    return not is_project_repo(repo_path.name)


def is_worktree(repo_path: Path) -> bool:
    git_path = repo_path / ".git"
    return git_path.is_file()


def resolve_original_repo(repo_path: Path) -> Path:
    if is_worktree(repo_path):
        rc, common_dir, _ = run_cmd(
            ["git", "-C", str(repo_path), "rev-parse", "--git-common-dir"]
        )
        if rc == 0:
            common = Path(common_dir.strip())
            if not common.is_absolute():
                common = (repo_path / common).resolve()
            return common.parent

    for remote in ("local", "origin"):
        rc, url, _ = run_cmd(
            ["git", "-C", str(repo_path), "remote", "get-url", remote]
        )
        if rc == 0 and url.strip():
            origin_path = Path(url.strip())
            if origin_path.is_dir():
                return origin_path.resolve()

    return repo_path


def _get_clone_origin(clone_path: Path) -> str | None:
    """Get the origin URL of a git clone, or None if not a git repo."""
    rc, stdout, _ = run_cmd(["git", "-C", str(clone_path), "remote", "get-url", "origin"])
    return stdout.strip() if rc == 0 else None


def get_slot_repos(slot_dir: Path) -> list[str]:
    return [
        d.name for d in sorted(slot_dir.iterdir())
        if d.is_dir() and (d / ".git").exists()
        and is_project_repo(d.name) and not is_workspace_clone(d)
    ]


def get_all_slot_repos(slot_dir: Path) -> list[str]:
    """All git repos in the slot — project + workspace."""
    return [
        d.name for d in sorted(slot_dir.iterdir())
        if d.is_dir() and (d / ".git").exists()
        and d.name not in (".m2", "attic")
    ]


def _cleanup_remnant_dir(path: Path) -> bool:
    """Remove IDE artifacts and empty directories left after git operations.
    Recurses into subdirectories. Returns True if path no longer exists."""
    if not path.exists():
        return True
    for item in list(path.iterdir()):
        if item.is_dir() and item.name in _IDE_ARTIFACTS:
            shutil.rmtree(str(item), ignore_errors=True)
        elif item.is_dir():
            _cleanup_remnant_dir(item)
    try:
        path.rmdir()
        return True
    except OSError:
        return False


def _escape_slot_cwd(slot_dir: Path, escape_to: Path) -> tuple[bool, Path | None]:
    """If CWD is inside slot_dir, chdir to escape_to.

    Returns (escaped, relative_offset) where relative_offset is the path
    from slot_dir to the original CWD (e.g. Path('platform') if CWD was
    slots/98/platform). Callers use this to compute the equivalent path
    in the archive destination.
    """
    try:
        cwd = Path.cwd().resolve()
        slot_resolved = slot_dir.resolve()
        if cwd == slot_resolved or slot_resolved in cwd.parents:
            relative = cwd.relative_to(slot_resolved)
            os.chdir(escape_to)
            return True, relative
    except OSError:
        pass
    return False, None


def _has_unmerged_content(slot_dir: Path) -> list[str]:
    """Return list of repo names with unmerged branch content vs main."""
    unmerged = []
    for repo_dir in sorted(slot_dir.iterdir()):
        if not repo_dir.is_dir() or not (repo_dir / ".git").exists():
            continue
        rc, stdout, _ = run_cmd(
            ["git", "branch", "--show-current"], cwd=str(repo_dir))
        if rc != 0:
            continue
        branch = stdout.strip()
        if not branch or branch == "main":
            continue
        rc, stdout, _ = run_cmd(
            ["git", "diff", "--stat", f"main...{branch}"], cwd=str(repo_dir))
        if rc == 0 and stdout.strip():
            unmerged.append(repo_dir.name)
    return unmerged
