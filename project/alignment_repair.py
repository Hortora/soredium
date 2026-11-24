"""Repair alignment states that are safe to repair without asking.

  workspace_behind   the project is on a working branch and the workspace is
                     still, cleanly, on the base branch: the workspace joins it.
  unrecorded_branch  both repos are on the branch but no base was recorded for
                     it, because it was made by hand: the base is recorded.
  project_behind     the workspace is on a branch and the project is on the base
                     branch: if the workspace is clean, it is checked out to the
                     base branch. The stale branch is preserved. apply_alignment
                     gates this: when the queue names the workspace branch as
                     active work, the repair is blocked and a decision returned.

Everything else `alignment.detect` reports is a decision for the user. A repair
goes through branch_base, the same code create-branches uses, so a repaired
branch is indistinguishable from one `work start` made.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import branch_base
from alignment import Alignment, _is_dirty
from git_util import git

REPAIRABLE = ("workspace_behind", "unrecorded_branch", "project_behind")


@dataclass(frozen=True)
class Repair:
    ok: bool
    actions: tuple[str, ...] = ()
    reason: str = ""     # why it was not repaired
    detail: str = ""


def _local_branches(repo: Path) -> list[str]:
    out = git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads").stdout
    return [b for b in out.split("\n") if b]


def _is_ancestor(repo: Path, older: str, newer: str) -> bool:
    return git(repo, "merge-base", "--is-ancestor", older, newer).returncode == 0


def adoptable_base(repo: Path, branch: str, base_branch: str) -> tuple[str, str]:
    """(base sha, "") when `branch` plainly forks from `base_branch`, else ("", why).

    It does not when another working branch sits between the two: the branch was
    stacked by hand, and recording the base branch as its origin would later land
    the other branch's commits as its own.
    """
    fork = git(repo, "merge-base", f"refs/heads/{branch}", f"refs/heads/{base_branch}")
    sha = fork.stdout.strip()
    if fork.returncode != 0 or not sha:
        return "", f"{branch} shares no history with {base_branch} in {repo.name}"
    tip = git(repo, "rev-parse", f"refs/heads/{branch}").stdout.strip()
    for other in _local_branches(repo):
        if other in (branch, base_branch):
            continue
        other_tip = git(repo, "rev-parse", f"refs/heads/{other}").stdout.strip()
        if other_tip in (sha, tip):
            continue
        if _is_ancestor(repo, other_tip, tip) and not _is_ancestor(repo, other_tip, sha):
            return "", (f"{branch} is built on {other} in {repo.name}; "
                        f"its origin cannot be recorded without knowing which")
    return sha, ""


def _adopt(repo: Path, branch: str, base_branch: str) -> tuple[bool, str]:
    if branch_base.base_of(repo, branch):
        return True, ""
    sha, why = adoptable_base(repo, branch, base_branch)
    if not sha:
        return False, why
    branch_base.record(repo, branch, sha)
    return True, f"recorded base of {branch} in {repo.name}"


def repair(found: Alignment, project: Path, workspace: Path, base_branch: str = "main") -> Repair:
    if found.state not in REPAIRABLE:
        return Repair(False, reason="not_repairable", detail=found.detail)
    project, workspace = Path(project), Path(workspace)

    if found.state == "project_behind":
        return _repair_project_behind(found, workspace, base_branch)

    branch = found.project_branch
    actions: list[str] = []

    # Check everything that can refuse before changing anything.
    if not branch_base.base_of(project, branch):
        sha, why = adoptable_base(project, branch, base_branch)
        if not sha:
            return Repair(False, reason="origin_unclear", detail=why)
    workspace_has_branch = branch_base.branch_exists(workspace, branch)
    if workspace_has_branch and not branch_base.base_of(workspace, branch):
        sha, why = adoptable_base(workspace, branch, base_branch)
        if not sha:
            return Repair(False, reason="origin_unclear", detail=why)

    if found.state == "workspace_behind":
        if workspace_has_branch:
            result = git(workspace, "checkout", "-q", branch)
            if result.returncode != 0:
                return Repair(False, reason="checkout_refused",
                              detail=" ".join((result.stderr or result.stdout).split()))
            actions.append(f"checked out {branch} in {workspace.name}")
        else:
            ok, detail = branch_base.cut(workspace, branch, base_branch)
            if not ok:
                return Repair(False, reason="cut_refused", detail=detail)
            actions.append(f"created {branch} in {workspace.name} from {detail}")

    for repo in (project, workspace):
        ok, detail = _adopt(repo, branch, base_branch)
        if not ok:
            return Repair(False, tuple(actions), reason="origin_unclear", detail=detail)
        if detail:
            actions.append(detail)
    return Repair(True, tuple(actions))


def _repair_project_behind(found: Alignment, workspace: Path,
                           base_branch: str) -> Repair:
    """Workspace on a stale branch, project on main: check workspace out to main."""
    if _is_dirty(workspace):
        return Repair(False, reason="workspace_dirty",
                      detail=f"workspace on {found.workspace_branch} with uncommitted changes")
    result = git(workspace, "checkout", "-q", base_branch)
    if result.returncode != 0:
        return Repair(False, reason="checkout_refused",
                      detail=" ".join((result.stderr or result.stdout).split()))
    return Repair(True, (f"checked out {base_branch} in {workspace.name} "
                         f"(was on stale {found.workspace_branch})",))
