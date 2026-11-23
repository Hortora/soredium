"""Read-only survey of every area in a family root."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from project.git_util import git


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class RepoInfo:
    name: str
    path: Path
    role: str  # "project" | "workspace"


@dataclass
class Area:
    kind: str  # "canonical" | "slot" | "clone" | "attic"
    path: Path
    slot_number: int | None = None
    repo_name: str | None = None
    repos: list[RepoInfo] = field(default_factory=list)
    project_repo: RepoInfo | None = None
    workspace_repo: RepoInfo | None = None


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def _is_workspace(path: Path) -> bool:
    return (path / ".workspace").exists() or path.name.startswith("wsp-")


def _pair_workspace(project_name: str, family_root: Path) -> Path | None:
    wsp = family_root / f"wsp-{project_name}"
    if wsp.is_dir() and (wsp / ".git").exists():
        return wsp
    for child in sorted(family_root.iterdir()):
        if not child.is_dir() or not (child / ".git").exists():
            continue
        if _is_workspace(child):
            proj_link = child / "proj"
            if proj_link.is_symlink():
                target = proj_link.resolve()
                if target.name == project_name:
                    return child
    return None


def _discover_repos_in_area(area_dir: Path) -> tuple[list[RepoInfo], RepoInfo | None, RepoInfo | None]:
    repos: list[RepoInfo] = []
    project_repo = None
    workspace_repo = None
    for child in sorted(area_dir.iterdir()):
        if not child.is_dir() or not (child / ".git").exists():
            continue
        if child.name in ("slots", "clone", "attic"):
            continue
        if _is_workspace(child):
            ri = RepoInfo(name=child.name, path=child, role="workspace")
            repos.append(ri)
            workspace_repo = ri
        else:
            ri = RepoInfo(name=child.name, path=child, role="project")
            repos.append(ri)
            if project_repo is None:
                project_repo = ri
    return repos, project_repo, workspace_repo


def discover_areas(family_root: Path) -> list[Area]:
    canonicals: list[Area] = []
    slots: list[Area] = []
    clones: list[Area] = []
    attics: list[Area] = []

    skip_dirs = {"slots", "clone", "attic", ".git"}
    workspace_paths: set[Path] = set()

    for child in sorted(family_root.iterdir()):
        if not child.is_dir() or child.name in skip_dirs:
            continue
        if not (child / ".git").exists():
            continue
        if _is_workspace(child):
            workspace_paths.add(child)
            continue
        wsp_path = _pair_workspace(child.name, family_root)
        project_ri = RepoInfo(name=child.name, path=child, role="project")
        workspace_ri = None
        all_repos = [project_ri]
        if wsp_path:
            workspace_ri = RepoInfo(name=wsp_path.name, path=wsp_path, role="workspace")
            all_repos.append(workspace_ri)
            workspace_paths.add(wsp_path)
        canonicals.append(Area(
            kind="canonical", path=child,
            repos=all_repos, project_repo=project_ri,
            workspace_repo=workspace_ri,
        ))

    slots_dir = family_root / "slots"
    if slots_dir.is_dir():
        for child in sorted(slots_dir.iterdir(), key=lambda p: (not p.name.isdigit(), p.name)):
            if child.name == "attic":
                continue
            if not child.is_dir() or not (child / ".slot").exists():
                continue
            repos, proj, wsp = _discover_repos_in_area(child)
            num = int(child.name) if child.name.isdigit() else None
            slots.append(Area(
                kind="slot", path=child, slot_number=num,
                repos=repos, project_repo=proj, workspace_repo=wsp,
            ))

    clone_dir = family_root / "clone"
    if clone_dir.is_dir():
        for child in sorted(clone_dir.iterdir()):
            if not child.is_dir() or not (child / ".permanent").exists():
                continue
            repos, proj, wsp = _discover_repos_in_area(child)
            clones.append(Area(
                kind="clone", path=child, repo_name=child.name,
                repos=repos, project_repo=proj, workspace_repo=wsp,
            ))

    attic_dir = slots_dir / "attic" if slots_dir.is_dir() else None
    if attic_dir and attic_dir.is_dir():
        for child in sorted(attic_dir.iterdir(), key=lambda p: (not p.name.isdigit(), p.name)):
            if not child.is_dir() or not (child / ".slot").exists():
                continue
            repos, proj, wsp = _discover_repos_in_area(child)
            num = int(child.name) if child.name.isdigit() else None
            attics.append(Area(
                kind="attic", path=child, slot_number=num,
                repos=repos, project_repo=proj, workspace_repo=wsp,
            ))

    return canonicals + slots + clones + attics


# ---------------------------------------------------------------------------
# Read-only git helpers
# ---------------------------------------------------------------------------

def follow_state_readonly(clone_repo: Path, canon_repo: Path, base: str) -> str:
    clone_result = git(clone_repo, "rev-parse", "--verify", f"refs/heads/{base}")
    canon_result = git(canon_repo, "rev-parse", "--verify", f"refs/heads/{base}")
    if clone_result.returncode != 0 or canon_result.returncode != 0:
        return "unknown"
    clone_sha = clone_result.stdout.strip()
    canon_sha = canon_result.stdout.strip()
    if clone_sha == canon_sha:
        return "current"
    result = git(clone_repo, "merge-base", clone_sha, canon_sha)
    merge_base = result.stdout.strip()
    if not merge_base:
        return "diverged"
    if merge_base == clone_sha:
        return "fast-forward"
    if merge_base == canon_sha:
        return "ahead"
    return "diverged"


def ahead_readonly(repo: Path, canon_repo: Path, base: str, branch: str) -> int:
    result = git(canon_repo, "rev-parse", "--verify", f"refs/heads/{base}")
    if result.returncode != 0:
        return 0
    canon_sha = result.stdout.strip()
    result = git(repo, "rev-list", "--count", f"{canon_sha}..refs/heads/{branch}")
    count = result.stdout.strip()
    return int(count) if count.isdigit() else 0


def entries_on_ref(repo: Path, ref: str, blog_dir: str = "docs/blog") -> set[str]:
    result = git(repo, "ls-tree", "-r", "--name-only", ref, "--", blog_dir)
    if result.returncode != 0:
        return set()
    return {line for line in result.stdout.strip().splitlines() if line}


def entry_content_from_ref(repo: Path, ref: str, path: str) -> str:
    result = git(repo, "show", f"{ref}:{path}")
    return result.stdout if result.returncode == 0 else ""


def parse_frontmatter_from_text(text: str) -> dict[str, Any] | None:
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        return yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return None
