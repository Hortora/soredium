"""Alignment detector: reads project and workspace repo state, reports divergence.

Pure detection — changes nothing.

States: on_base, aligned, workspace_behind, workspace_dirty, workspace_other,
project_behind, unrecorded_branch, queue_mismatch, detached, unreadable.
A caller may repair only workspace_behind and unrecorded_branch; every other
state but on_base and aligned is a decision for the user. Used by work-start, work-resume, and the
work router to decide what to do when repos disagree about which branch is active.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from git_util import git
from branch_base import base_of
from queue_io import read_queue


@dataclass(frozen=True)
class Alignment:
    state: str
    project_branch: str
    workspace_branch: str
    queue_branch: str
    detail: str


def _is_repo(repo: Path) -> bool:
    return git(repo, "rev-parse", "--git-dir").returncode == 0


def _current_branch(repo: Path) -> str:
    """The checked-out branch, "" when HEAD is detached (a rebase or bisect in
    progress, or a commit checked out directly)."""
    result = git(repo, "symbolic-ref", "--short", "-q", "HEAD")
    return result.stdout.strip() if result.returncode == 0 else ""


def _is_dirty(repo: Path) -> bool:
    """Uncommitted or untracked files other than the proj/wksp links. A status
    that cannot be read counts as dirty: nothing may be switched on a guess."""
    result = git(repo, "status", "--porcelain")
    if result.returncode != 0:
        return True
    for line in result.stdout.splitlines():
        path = line[3:].strip()
        if path in ("proj", "wksp") or path.startswith("proj/") or path.startswith("wksp/"):
            continue
        if path:
            return True
    return False


def _queue_branch(workspace: Path) -> str:
    queue = read_queue(workspace)
    if queue is None:
        return ""
    return queue.state.branch


def detect(project: Path, workspace: Path, base_branch: str = "main") -> Alignment:
    for label, repo in (("project", project), ("workspace", workspace)):
        if not _is_repo(repo):
            return Alignment("unreadable", "", "", "",
                             f"the {label} at {repo} is not a git repository")

    proj_br = _current_branch(project)
    wksp_br = _current_branch(workspace)
    q_br = _queue_branch(workspace)

    detached = [label for label, br in (("project", proj_br), ("workspace", wksp_br))
                if not br]
    if detached:
        return Alignment("detached", proj_br, wksp_br, q_br,
                         f"{' and '.join(detached)} not on a branch: a rebase or "
                         f"other operation may be in progress")

    if proj_br == base_branch and wksp_br == base_branch:
        return Alignment("on_base", proj_br, wksp_br, q_br,
                         "both repos on the base branch")

    if proj_br == wksp_br and proj_br != base_branch:
        missing = [label for label, repo in (("project", project), ("workspace", workspace))
                   if not base_of(repo, proj_br)]
        if missing:
            return Alignment("unrecorded_branch", proj_br, wksp_br, q_br,
                             f"branch {proj_br} has no recorded base in the "
                             f"{' or the '.join(missing)} repo")

        if q_br and q_br != proj_br:
            return Alignment("queue_mismatch", proj_br, wksp_br, q_br,
                             f"repos on {proj_br} but queue names {q_br}")

        return Alignment("aligned", proj_br, wksp_br, q_br,
                         f"both repos on {proj_br}, base recorded")

    if proj_br != base_branch and wksp_br == base_branch:
        dirty = _is_dirty(workspace)
        if dirty:
            return Alignment("workspace_dirty", proj_br, wksp_br, q_br,
                             f"project on {proj_br}, workspace on {base_branch} with uncommitted changes")
        return Alignment("workspace_behind", proj_br, wksp_br, q_br,
                         f"project on {proj_br}, workspace still on {base_branch}")

    if wksp_br != base_branch and proj_br == base_branch:
        return Alignment("project_behind", proj_br, wksp_br, q_br,
                         f"workspace on {wksp_br}, project still on {base_branch}")

    return Alignment("workspace_other", proj_br, wksp_br, q_br,
                     f"project on {proj_br}, workspace on {wksp_br}")
