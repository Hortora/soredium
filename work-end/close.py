"""Atomic close ceremony for work-end.

Single entry point: close(workspace) → CloseResult.
Reads .queue and git state; lands branches, stamps, advances queue.
Each step is idempotent — re-running after failure picks up from
committed state.
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_project_dir = str(Path(__file__).resolve().parent.parent / "project")
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)
_slot_dir = str(Path(__file__).resolve().parent.parent / "work-slot")
if _slot_dir not in sys.path:
    sys.path.insert(0, _slot_dir)

from queue_io import read_queue, write_queue, Queue, QueueItem


LIFECYCLE_FILES = [
    "JOURNAL.md", ".close-state", ".execute-progress",
    ".land-ledger.jsonl", ".artifacts-promoted", ".squash-plan",
    ".close-progress", ".close-report.json",
    ".close-log.jsonl", ".wrap-log.jsonl", ".work-progress",
]


@dataclass(frozen=True)
class CloseTarget:
    repo: Path
    branch: str
    base_branch: str
    transport: str
    canonical: Optional[Path]
    push_target: str
    mirror_target: str
    is_workspace: bool


@dataclass
class CloseResult:
    success: bool
    errors: list[str] = field(default_factory=list)
    landed: dict = field(default_factory=dict)
    next_item: Optional[QueueItem] = None
    rescued: dict = field(default_factory=dict)


# --- git helpers ---

def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True,
    )


def _branch_exists(repo: Path, branch: str) -> bool:
    result = _git(repo, "rev-parse", "--verify", f"refs/heads/{branch}")
    return result.returncode == 0


def _has_commits_ahead(repo: Path, branch: str, base: str) -> bool:
    result = _git(repo, "rev-list", "--count", f"{base}..{branch}")
    if result.returncode != 0:
        return False
    count = result.stdout.strip()
    return count.isdigit() and int(count) > 0


# --- resolve ---

def discover_repo_topology(workspace: Path) -> list[tuple]:
    """Return list of (repo, base_branch, transport, canonical, push_target, mirror_target).

    Non-slot: project repo (via proj/ symlink) + workspace.
    Slot: all slot repos via slot_core.
    Fork model: upstream remote → push_target='upstream', mirror='origin'.
    """
    from slot_core import get_slot_repos, resolve_canonical_repo, is_workspace_clone

    slot_repos = _get_slot_repos_if_slot(workspace)
    if slot_repos:
        results = []
        for repo_path in slot_repos:
            canonical = resolve_canonical_repo(repo_path)
            base = _get_base_branch(repo_path)
            push, mirror = _detect_fork_model(repo_path)
            transport = "two-hop" if canonical != repo_path else "direct"
            results.append((repo_path, base, transport,
                            canonical if transport == "two-hop" else None,
                            push, mirror))
        return results

    results = []
    project = _resolve_project(workspace)
    if project:
        base = _get_base_branch(project)
        push, mirror = _detect_fork_model(project)
        results.append((project, base, "direct", None, push, mirror))

    if workspace != project:
        base = _get_base_branch(workspace)
        push, mirror = _detect_fork_model(workspace)
        results.append((workspace, base, "direct", None, push, mirror))

    return results


def _get_slot_repos_if_slot(workspace: Path) -> list[Path]:
    """Return slot repo Paths if workspace is inside a slot, else empty list."""
    try:
        from slot_core import get_slot_repos, is_workspace_clone
        slot_dir = workspace.parent
        if not (slot_dir / ".slot").exists():
            return []
        repo_names = get_slot_repos(slot_dir)
        return [slot_dir / name for name in repo_names]
    except (ImportError, Exception):
        return []


def _resolve_project(workspace: Path) -> Optional[Path]:
    """Resolve the project repo from workspace's proj/ symlink."""
    proj_link = workspace / "proj"
    if proj_link.is_symlink():
        return proj_link.resolve()
    return None


def _get_base_branch(repo: Path) -> str:
    for candidate in ("main", "master"):
        if _branch_exists(repo, candidate):
            return candidate
    return "main"


def _detect_fork_model(repo: Path) -> tuple[str, str]:
    result = _git(repo, "remote")
    if result.returncode != 0:
        return ("origin", "")
    remotes = result.stdout.strip().split("\n")
    if "upstream" in remotes:
        return ("upstream", "origin")
    return ("origin", "")


def discover_active_branches(workspace: Path, queue: Queue) -> list[str]:
    """Return branches to close. queue.branch + slot siblings."""
    branches = []
    if queue.state.branch:
        branches.append(queue.state.branch)

    slot_repos = _get_slot_repos_if_slot(workspace)
    for repo_path in slot_repos:
        current = _current_branch(repo_path)
        if current and current != "main" and current not in branches:
            branches.append(current)

    return branches


def _current_branch(repo: Path) -> str:
    result = _git(repo, "branch", "--show-current")
    return result.stdout.strip() if result.returncode == 0 else ""


def resolve(workspace: Path) -> list[CloseTarget]:
    """Determine what to close. Returns a CloseTarget per repo×branch with commits."""
    queue = read_queue(workspace)
    if queue is None:
        return []

    branches = discover_active_branches(workspace, queue)
    topology = discover_repo_topology(workspace)
    targets = []

    for branch in branches:
        for repo, base, transport, canonical, push, mirror in topology:
            if _branch_exists(repo, branch) and _has_commits_ahead(repo, branch, base):
                is_ws = (repo.resolve() == workspace.resolve())
                targets.append(CloseTarget(
                    repo=repo, branch=branch, base_branch=base,
                    transport=transport, canonical=canonical,
                    push_target=push, mirror_target=mirror,
                    is_workspace=is_ws,
                ))

    return targets


# --- preflight ---

def _is_dirty(repo: Path) -> bool:
    result = _git(repo, "status", "--porcelain")
    return bool(result.stdout.strip()) if result.returncode == 0 else False


def _remote_reachable(repo: Path, remote: str) -> bool:
    result = _git(repo, "remote", "get-url", remote)
    if result.returncode != 0:
        return False
    url = result.stdout.strip()
    if Path(url).is_dir():
        return True
    result = _git(repo, "ls-remote", "--exit-code", remote)
    return result.returncode == 0


def _commits_ahead_of_remote(repo: Path, base: str, remote: str) -> int:
    result = _git(repo, "rev-list", "--count", f"{remote}/{base}..{base}")
    if result.returncode != 0:
        return 0
    count = result.stdout.strip()
    return int(count) if count.isdigit() else 0


def _create_branch_at(repo: Path, name: str, ref: str) -> None:
    _git(repo, "branch", name, ref)


def _reset_to_remote(repo: Path, base: str, remote: str) -> None:
    _git(repo, "reset", "--hard", f"{remote}/{base}")


def preflight(targets: list[CloseTarget]) -> dict:
    """Verify preconditions before mutating. Returns {errors, rescued}."""
    errors: list[str] = []
    rescued: dict[str, str] = {}

    for t in targets:
        if _is_dirty(t.repo):
            errors.append(f"{t.repo.name}: uncommitted changes")
        if not _branch_exists(t.repo, t.base_branch):
            errors.append(f"{t.repo.name}: no {t.base_branch} branch")
        if not _remote_reachable(t.repo, t.push_target):
            pass

        local_only = _commits_ahead_of_remote(t.repo, t.base_branch, t.push_target)
        if local_only > 0:
            rescue_name = f"rescue-{t.repo.name}"
            _create_branch_at(t.repo, rescue_name, t.base_branch)
            _reset_to_remote(t.repo, t.base_branch, t.push_target)
            rescued[t.repo.name] = rescue_name

    return {"errors": errors, "rescued": rescued}


# --- land ---

def _checkout(repo: Path, branch: str) -> None:
    _git(repo, "checkout", branch)


def _pull(repo: Path, remote: str, branch: str) -> None:
    result = _git(repo, "remote")
    if result.returncode != 0 or remote not in result.stdout:
        return
    _git(repo, "fetch", remote, branch)
    _git(repo, "reset", "--hard", f"{remote}/{branch}")


def _merge_base(repo: Path, a: str, b: str) -> str:
    result = _git(repo, "merge-base", a, b)
    return result.stdout.strip() if result.returncode == 0 else ""


def _is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    result = _git(repo, "merge-base", "--is-ancestor", ancestor, descendant)
    return result.returncode == 0


def _rev_parse(repo: Path, ref: str) -> str:
    result = _git(repo, "rev-parse", ref)
    return result.stdout.strip() if result.returncode == 0 else ""


def _diff_stat(repo: Path, a: str, b: str) -> str:
    result = _git(repo, "diff", "--stat", a, b,
                  "--", ".", ":(exclude).close-progress",
                  ":(exclude).close-state", ":(exclude)JOURNAL.md",
                  ":(exclude).execute-progress", ":(exclude).land-ledger.jsonl",
                  ":(exclude).artifacts-promoted", ":(exclude).squash-plan",
                  ":(exclude).close-report.json", ":(exclude).close-log.jsonl",
                  ":(exclude).wrap-log.jsonl", ":(exclude).work-progress")
    return result.stdout.strip() if result.returncode == 0 else ""


def branch_already_landed(repo: Path, branch: str, base: str) -> bool:
    if _is_ancestor(repo, branch, base):
        return True
    diff = _diff_stat(repo, branch, base)
    return diff == ""


def _find_landed_sha(repo: Path, branch: str, base: str) -> str:
    if _is_ancestor(repo, branch, base):
        return _rev_parse(repo, base)
    return _rev_parse(repo, base)


def _read_squash_plan(repo: Path) -> Optional[str]:
    plan_path = repo / ".squash-plan"
    if plan_path.exists():
        return plan_path.read_text().strip()
    return None


def strip_lifecycle_files(repo: Path, branch: str, files: list[str]) -> None:
    _checkout(repo, branch)
    removed = False
    for f in files:
        fpath = repo / f
        if fpath.exists():
            _git(repo, "rm", "-f", f)
            removed = True
    if removed:
        _git(repo, "commit", "-m", "chore: strip lifecycle files before merge")


def strip_lifecycle_files_from_tree(repo: Path, branch: str, files: list[str]) -> None:
    _checkout(repo, branch)
    removed = False
    for f in files:
        fpath = repo / f
        if fpath.exists():
            _git(repo, "rm", "-f", f)
            removed = True
    if removed:
        _git(repo, "commit", "-m", "chore: strip leaked lifecycle files")


def rebase_onto_base(repo: Path, branch: str, base: str, push_target: str) -> None:
    _checkout(repo, branch)
    _git(repo, "fetch", push_target, base)
    remote_base = f"{push_target}/{base}"

    result = _git(repo, "rev-parse", "--verify", remote_base)
    if result.returncode != 0:
        remote_base = base

    if _is_ancestor(repo, remote_base, "HEAD"):
        return

    for attempt in range(3):
        result = _git(repo, "rebase", remote_base)
        if result.returncode == 0:
            return
        _git(repo, "rebase", "--abort")

    raise RuntimeError(
        f"Rebase failed after 3 attempts: {repo.name}:{branch} onto {base}")


def squash_merge(repo: Path, branch: str, base: str,
                 squash_msg: Optional[str] = None) -> str:
    _checkout(repo, branch)
    merge_base_sha = _merge_base(repo, base, branch)

    _git(repo, "reset", "--soft", merge_base_sha)

    if squash_msg is None:
        result = _git(repo, "log", "--format=%s", f"{merge_base_sha}..HEAD")
        msgs = result.stdout.strip().splitlines() if result.returncode == 0 else []
        squash_msg = "\n".join(msgs) if msgs else "squash: combined commits"

    _git(repo, "commit", "-m", squash_msg)
    squash_sha = _rev_parse(repo, "HEAD")

    _checkout(repo, base)
    result = _git(repo, "merge", "--ff-only", branch)
    if result.returncode != 0:
        _git(repo, "merge", branch)

    return squash_sha


def _merge_no_ff(repo: Path, branch: str) -> str:
    result = _git(repo, "merge", "--no-ff", branch,
                  "-m", f"Merge branch '{branch}'")
    if result.returncode != 0:
        raise RuntimeError(f"Non-ff merge failed: {repo.name}:{branch}")
    return _rev_parse(repo, "HEAD")


def _push(repo: Path, remote: str, branch: str,
          force_with_lease: bool = False) -> None:
    args = ["push", remote, branch]
    if force_with_lease:
        args.insert(1, "--force-with-lease")
    _git(repo, *args)


def _push_two_hop(repo: Path, canonical: Path) -> None:
    result = _git(repo, "remote", "get-url", "local")
    if result.returncode != 0:
        return
    _git(repo, "push", "local", "main")


def verify_content_landed(repo: Path, branch: str, base: str) -> None:
    result = _git(repo, "diff", "--stat", base, branch,
                  "--", ".", *[f":(exclude){f}" for f in LIFECYCLE_FILES])
    if result.returncode == 0 and result.stdout.strip():
        raise RuntimeError(
            f"Content from {branch} not fully landed on {base}: "
            f"{result.stdout.strip()}")


def land(target: CloseTarget) -> str:
    if branch_already_landed(target.repo, target.branch, target.base_branch):
        return _find_landed_sha(target.repo, target.branch, target.base_branch)

    if target.is_workspace and target.transport == "two-hop":
        return ""

    squash_msg = _read_squash_plan(target.repo) if not target.is_workspace else None

    _checkout(target.repo, target.base_branch)

    if target.is_workspace:
        strip_lifecycle_files(target.repo, target.branch, LIFECYCLE_FILES)
        _checkout(target.repo, target.base_branch)
        sha = _merge_no_ff(target.repo, target.branch)
    else:
        try:
            rebase_onto_base(target.repo, target.branch, target.base_branch,
                             target.push_target)
        except RuntimeError:
            _checkout(target.repo, target.base_branch)
            raise
        sha = squash_merge(target.repo, target.branch,
                           target.base_branch, squash_msg)

    strip_lifecycle_files_from_tree(target.repo, target.base_branch, LIFECYCLE_FILES)

    return sha


# --- stamp ---

def _is_stamp_commit(repo: Path, branch: str) -> bool:
    result = _git(repo, "log", "-1", "--format=%s", branch)
    if result.returncode != 0:
        return False
    return result.stdout.strip().startswith("chore: branch closed")


def stamp(target: CloseTarget, landed_sha: str) -> None:
    if _is_stamp_commit(target.repo, target.branch):
        return

    _checkout(target.repo, target.branch)
    _git(target.repo, "commit", "--allow-empty",
         "-m", f"chore: branch closed — landed as {landed_sha} on {target.base_branch}")


# --- advance ---

def advance(workspace: Path, expected_issue: str) -> Optional[QueueItem]:
    queue = read_queue(workspace)
    if queue is None:
        return None

    active = queue.active_item()
    if active is None or active.ref != expected_issue:
        return queue.active_item()

    queue.complete_active()
    if queue.has_next():
        queue.activate_next()
        queue.set_status("active")
    else:
        queue.set_status("drained")
    write_queue(workspace, queue)
    return queue.active_item()


def commit_and_push_queue(workspace: Path, closing_issue: str) -> None:
    if not (workspace / ".queue").exists():
        return
    _git(workspace, "add", ".queue")
    _git(workspace, "commit", "-m", f"chore: advance queue — completed {closing_issue}")


# --- elevate ---

def elevate_queue(workspace: Path, slot_root: Optional[Path]) -> None:
    if not slot_root:
        return
    ws_queue = workspace / ".queue"
    slot_queue = slot_root / ".queue"
    if not ws_queue.exists():
        return
    if slot_queue.exists():
        return
    import shutil
    shutil.copy2(str(ws_queue), str(slot_queue))


# --- checkout ---

def checkout_all(targets: list[CloseTarget]) -> None:
    for target in targets:
        _checkout(target.repo, target.base_branch)


# --- close-state ---

def _generate_session_id() -> str:
    import secrets
    return secrets.token_hex(3)


def _write_close_state(workspace: Path, data: dict) -> None:
    lines = [f"{k}: {v}" for k, v in data.items()]
    (workspace / ".close-state").write_text("\n".join(lines) + "\n")


def _remove_close_state(workspace: Path) -> None:
    state_path = workspace / ".close-state"
    if state_path.exists():
        state_path.unlink()


def _read_close_state(workspace: Path) -> Optional[dict]:
    state_path = workspace / ".close-state"
    if not state_path.exists():
        return None
    data = {}
    for line in state_path.read_text().splitlines():
        if ": " in line:
            key, _, val = line.partition(": ")
            data[key.strip()] = val.strip()
    return data


def _detect_slot_root(workspace: Path) -> Optional[Path]:
    slot_dir = workspace.parent
    if (slot_dir / ".slot").exists():
        return slot_dir
    return None


# --- close orchestration ---

def close(workspace: Path) -> CloseResult:
    targets = resolve(workspace)

    if not targets:
        return CloseResult(
            success=False,
            errors=["no targets found — branch may not exist or has no commits"],
        )

    queue = read_queue(workspace)
    active = queue.active_item() if queue else None
    closing_issue = active.ref if active else ""

    pre = preflight(targets)
    if pre["errors"]:
        return CloseResult(success=False, errors=pre["errors"])

    session_id = _generate_session_id()
    _write_close_state(workspace, {
        "step": "landing",
        "closing_issue": closing_issue,
        "session_id": session_id,
        "repos": ", ".join(f"{t.repo.name}:{t.branch}" for t in targets),
    })

    try:
        landed: dict[CloseTarget, str] = {}
        for target in targets:
            sha = land(target)
            landed[target] = sha

        for target, sha in landed.items():
            stamp(target, sha)

        slot_root = _detect_slot_root(workspace)

        if slot_root:
            next_item = advance(workspace, closing_issue)
            elevate_queue(workspace, slot_root)
            checkout_all(targets)
        else:
            checkout_all(targets)
            next_item = advance(workspace, closing_issue)
            commit_and_push_queue(workspace, closing_issue)

        _remove_close_state(workspace)
        return CloseResult(
            success=True,
            landed={t.repo.name: sha for t, sha in landed.items()},
            next_item=next_item,
            rescued=pre["rescued"],
        )
    except Exception:
        checkout_all(targets)
        raise
