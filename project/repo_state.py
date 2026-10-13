"""repo_state.py — classify repos at pipeline entry.

Single source of truth for repo disposition. All pipeline code classifies
repos here instead of probing git at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from git_util import git


class RepoType(Enum):
    PROJECT = "project"
    WORKSPACE = "workspace"
    CLONE = "clone"


class RepoDisposition(Enum):
    HAS_WORK = "has_work"
    EMPTY_BRANCH = "empty_branch"
    NO_BRANCH = "no_branch"
    ALREADY_LANDED = "already_landed"


@dataclass(frozen=True)
class RepoState:
    path: Path
    name: str
    repo_type: RepoType
    disposition: RepoDisposition
    branch: str | None
    commits_ahead: int
    is_dirty: bool
    has_remote: bool
    remote_branch_exists: bool
    landing_sha: str | None
    has_upstream: bool
    push_remote: str
    canonical_path: Path | None
    is_slot_clone: bool


def classify_repo(
    path: Path,
    branch: str,
    base_branch: str,
    repo_type: RepoType,
) -> RepoState | None:
    git_check = git(path, "rev-parse", "--git-dir")
    if git_check.returncode != 0:
        return None

    has_branch_result = git(path, "branch", "--list", branch)
    branch_exists = (
        has_branch_result.returncode == 0
        and bool(has_branch_result.stdout.strip())
    )

    commits_ahead = 0
    if branch_exists:
        count_result = git(path, "rev-list", "--count", f"{base_branch}..{branch}")
        if count_result.returncode == 0 and count_result.stdout.strip():
            commits_ahead = int(count_result.stdout.strip())

    dirty_result = git(path, "status", "--porcelain")
    is_dirty = dirty_result.returncode == 0 and bool(dirty_result.stdout.strip())

    origin_result = git(path, "remote", "get-url", "origin")
    has_remote = origin_result.returncode == 0

    remote_branch_exists = False
    if has_remote and branch_exists:
        ls_result = git(path, "ls-remote", "--heads", "origin", branch)
        remote_branch_exists = (
            ls_result.returncode == 0
            and bool(ls_result.stdout.strip())
        )

    already_landed = False
    landing_sha: str | None = None
    if branch_exists:
        ancestor_result = git(
            path, "merge-base", "--is-ancestor", branch, base_branch,
        )
        if ancestor_result.returncode == 0:
            already_landed = True
            if commits_ahead > 0:
                sha_result = git(path, "rev-parse", base_branch)
                if sha_result.returncode == 0:
                    landing_sha = sha_result.stdout.strip()

    upstream_result = git(path, "remote", "get-url", "upstream")
    has_upstream = upstream_result.returncode == 0

    local_result = git(path, "remote", "get-url", "local")
    is_slot_clone = local_result.returncode == 0
    canonical_path: Path | None = None
    if is_slot_clone:
        raw = local_result.stdout.strip()
        if raw:
            canonical_path = Path(raw)

    if is_slot_clone:
        push_remote = "local"
    elif has_upstream:
        push_remote = "upstream"
    else:
        push_remote = "origin"

    if not branch_exists:
        disposition = RepoDisposition.NO_BRANCH
    elif already_landed:
        disposition = RepoDisposition.ALREADY_LANDED
    elif commits_ahead == 0:
        disposition = RepoDisposition.EMPTY_BRANCH
    else:
        disposition = RepoDisposition.HAS_WORK

    return RepoState(
        path=path,
        name=path.name,
        repo_type=repo_type,
        disposition=disposition,
        branch=branch if branch_exists else None,
        commits_ahead=commits_ahead,
        is_dirty=is_dirty,
        has_remote=has_remote,
        remote_branch_exists=remote_branch_exists,
        landing_sha=landing_sha,
        has_upstream=has_upstream,
        push_remote=push_remote,
        canonical_path=canonical_path,
        is_slot_clone=is_slot_clone,
    )


def classify_repos(
    project: Path,
    workspace: Path,
    branch: str,
    base_branch: str,
    slot_path: Path | None = None,
) -> list[RepoState]:
    if slot_path is not None:
        from slot_io import parse_slot
        info = parse_slot(slot_path)
        if info is None:
            return []
        repos = []
        for name in info.repos:
            repo_dir = slot_path / name
            if not repo_dir.is_dir():
                continue
            state = classify_repo(repo_dir, branch, base_branch, RepoType.CLONE)
            if state is not None:
                repos.append(state)
        return repos

    result = []
    for path, rtype in [(project, RepoType.PROJECT), (workspace, RepoType.WORKSPACE)]:
        state = classify_repo(path, branch, base_branch, rtype)
        if state is not None:
            result.append(state)
    return result


@dataclass(frozen=True)
class RepoContext:
    state: RepoState
    tree_sha: str
    main_tree_sha: str
    remote_synced: bool
    lifecycle_state: str | None


def build_repo_context(
    state: RepoState,
    base_branch: str,
    conn=None,
    work_item_id: int | None = None,
) -> RepoContext:
    tree_sha = ""
    if state.branch:
        result = git(state.path, "rev-parse", f"{state.branch}^{{tree}}")
        if result.returncode == 0:
            tree_sha = result.stdout.strip()

    main_result = git(state.path, "rev-parse", f"{base_branch}^{{tree}}")
    main_tree_sha = main_result.stdout.strip() if main_result.returncode == 0 else ""

    local_main = git(state.path, "rev-parse", base_branch)
    origin_main = git(state.path, "rev-parse", f"origin/{base_branch}")
    remote_synced = (
        local_main.returncode == 0
        and origin_main.returncode == 0
        and local_main.stdout.strip() == origin_main.stdout.strip()
    )

    lifecycle_state = None
    if conn is not None and work_item_id is not None:
        try:
            import sys as _sys
            _lib = str(Path.home() / ".claude" / "lib")
            if _lib not in _sys.path:
                _sys.path.insert(0, _lib)
            import worklog
            lifecycle_state = worklog.get_lifecycle_state(conn, work_item_id)
        except Exception:
            pass

    return RepoContext(
        state=state,
        tree_sha=tree_sha,
        main_tree_sha=main_tree_sha,
        remote_synced=remote_synced,
        lifecycle_state=lifecycle_state,
    )


def build_repo_contexts(
    repos: list[RepoState],
    base_branch: str,
    conn=None,
    work_item_id: int | None = None,
) -> list[RepoContext]:
    return [build_repo_context(r, base_branch, conn, work_item_id)
            for r in repos]
