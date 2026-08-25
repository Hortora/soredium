#!/usr/bin/env python3
"""Shared land flow for work-end convergence.

Provides a parameterized flow for landing branches in both slot mode
(two-hop: clone -> original -> remote) and branch mode (direct push).
The flow is topology-agnostic; adapters construct RepoDescriptor batches
that the flow processes uniformly.
"""

import os
import re
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Transport(Enum):
    DIRECT = "direct"
    TWO_HOP = "two-hop"


@dataclass
class RepoDescriptor:
    repo_path: Path
    original_path: Path
    push_target: str
    base_branch: str
    is_workspace: bool
    transport: Transport
    mirror_target: str = ""


@dataclass
class RepoStatus:
    repo_path: Path
    merged: bool = False
    pushed: bool = False
    stamped: bool = False
    landed_sha: str = ""
    skipped: bool = False
    error: str = ""


@dataclass
class LandResult:
    repos: list[RepoStatus] = field(default_factory=list)
    success: bool = True
    rescued: dict[str, str] = field(default_factory=dict)


def _git(repo: Path | str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, timeout=60,
    )


def _read_progress(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip()
    return result


def _write_progress(path: Path, key: str, value: str) -> None:
    progress = _read_progress(path)
    progress[key] = value
    lines = [f"{k}={v}" for k, v in progress.items()]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text("\n".join(lines) + "\n")
    os.replace(tmp, path)


def _progress_key(desc: RepoDescriptor, branch: str) -> str:
    return f"{desc.repo_path.name}:{branch}"


# ---------------------------------------------------------------------------
# Adapter helpers
# ---------------------------------------------------------------------------

def _resolve_original(repo_path: Path) -> Path:
    """Resolve the original repo for a slot clone via remotes."""
    for remote in ("local", "origin"):
        result = _git(repo_path, "remote", "get-url", remote)
        if result.returncode == 0 and result.stdout.strip():
            p = Path(result.stdout.strip())
            if p.is_dir():
                return p.resolve()
    return repo_path


def _resolve_local_push_remote(repo_path: Path) -> str:
    """Determine which remote points at the original (local first)."""
    result = _git(repo_path, "remote", "get-url", "local")
    if result.returncode == 0:
        return "local"
    result = _git(repo_path, "remote", "get-url", "origin")
    if result.returncode == 0 and Path(result.stdout.strip()).is_dir():
        return "origin"
    return ""


def _detect_push_target(repo_path: Path) -> str:
    """Detect the push target remote (upstream for fork model, origin for direct)."""
    result = _git(repo_path, "remote", "get-url", "upstream")
    if result.returncode == 0:
        return "upstream"
    result = _git(repo_path, "remote", "get-url", "origin")
    if result.returncode == 0:
        return "origin"
    return ""


def _detect_mirror_target(repo_path: Path) -> str:
    """Detect the fork remote for mirroring (fork model only)."""
    has_upstream = _git(repo_path, "remote", "get-url", "upstream")
    if has_upstream.returncode == 0:
        has_origin = _git(repo_path, "remote", "get-url", "origin")
        if has_origin.returncode == 0:
            return "origin"
    return ""


# ---------------------------------------------------------------------------
# Adapters
# ---------------------------------------------------------------------------

def build_slot_batch(
    slot_dir: Path, base_branch: str = "main",
) -> list[RepoDescriptor]:
    """Build RepoDescriptor batch for a slot. Project repos first."""
    descriptors: list[RepoDescriptor] = []
    for entry in sorted(slot_dir.iterdir()):
        if not entry.is_dir() or not (entry / ".git").exists():
            continue
        if entry.name in (".m2", "attic"):
            continue

        is_ws = (entry / ".workspace").exists()
        original = _resolve_original(entry)
        push_target = _resolve_local_push_remote(entry)

        descriptors.append(RepoDescriptor(
            repo_path=entry,
            original_path=original,
            push_target=push_target,
            base_branch=base_branch,
            is_workspace=is_ws,
            transport=Transport.TWO_HOP,
        ))

    return sorted(descriptors, key=lambda d: d.is_workspace)


def build_branch_batch(
    project_path: Path,
    workspace_path: Path | None,
    branch: str,
    base_branch: str = "main",
) -> list[RepoDescriptor]:
    """Build RepoDescriptor batch for branch mode."""
    push_target = _detect_push_target(project_path)
    mirror_target = _detect_mirror_target(project_path)

    descs = [
        RepoDescriptor(
            repo_path=project_path,
            original_path=project_path,
            push_target=push_target,
            base_branch=base_branch,
            is_workspace=False,
            transport=Transport.DIRECT,
            mirror_target=mirror_target,
        ),
    ]

    if workspace_path:
        result = _git(workspace_path, "branch", "--list", branch)
        ws_push_target = _detect_push_target(workspace_path)
        if result.returncode == 0 and result.stdout.strip() and ws_push_target:
            descs.append(RepoDescriptor(
                repo_path=workspace_path,
                original_path=workspace_path,
                push_target=ws_push_target,
                base_branch=base_branch,
                is_workspace=True,
                transport=Transport.DIRECT,
            ))

    return descs


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

def _preflight_two_hop(desc: RepoDescriptor) -> str | None:
    """Sync original repo's main with remote. Returns error string or None."""
    original = desc.original_path
    if not original.is_dir():
        return f"original_not_found path={original}"

    status = _git(original, "status", "--porcelain")
    if status.returncode == 0 and status.stdout.strip():
        unmerged = {"UU", "AA", "DD", "AU", "UA", "DU", "UD"}
        has_unmerged = any(
            line[:2] in unmerged for line in status.stdout.strip().splitlines()
        )
        if has_unmerged:
            return f"unmerged_conflict path={original}"
        cur = _git(original, "branch", "--show-current")
        if cur.returncode == 0 and cur.stdout.strip() == "main":
            return f"dirty_worktree path={original}"

    has_origin = _git(original, "remote", "get-url", "origin")
    if has_origin.returncode != 0:
        return None

    _git(original, "fetch", "origin", "main")
    behind_r = _git(original, "rev-list", "main..origin/main", "--count")
    behind = int(behind_r.stdout.strip()) if behind_r.returncode == 0 and behind_r.stdout.strip() else 0
    ahead_r = _git(original, "rev-list", "origin/main..main", "--count")
    ahead = int(ahead_r.stdout.strip()) if ahead_r.returncode == 0 and ahead_r.stdout.strip() else 0

    if behind > 0 and ahead > 0:
        return f"diverged_main path={original} ahead={ahead} behind={behind}"

    if ahead > 0:
        push = _git(original, "push", "origin", "main", "--no-verify")
        if push.returncode != 0:
            return f"cannot_push_original path={original}"
        print(f"SYNC=pushed repo={desc.repo_path.name} commits={ahead}")

    if behind > 0:
        cur = _git(original, "branch", "--show-current")
        cur_branch = cur.stdout.strip() if cur.returncode == 0 else ""
        if cur_branch == "main":
            _git(original, "rebase", "origin/main")
        else:
            _git(original, "fetch", "origin", "main:main")
        print(f"SYNC=pulled repo={desc.repo_path.name} commits={behind}")

    return None


def _preflight_direct(desc: RepoDescriptor) -> tuple[str | None, dict]:
    """Check remote and rescue local-only commits. Returns (error, metadata)."""
    metadata: dict[str, str] = {}

    result = _git(desc.repo_path, "remote", "get-url", desc.push_target)
    if result.returncode != 0:
        return f"no_remote push_target={desc.push_target}", metadata

    _git(desc.repo_path, "fetch", desc.push_target, desc.base_branch)

    cur = _git(desc.repo_path, "branch", "--show-current")
    cur_branch = cur.stdout.strip() if cur.returncode == 0 else ""

    if cur_branch != desc.base_branch:
        _git(desc.repo_path, "checkout", desc.base_branch)

    local_only = _git(
        desc.repo_path, "rev-list",
        f"{desc.push_target}/{desc.base_branch}..{desc.base_branch}",
    )
    if local_only.returncode == 0 and local_only.stdout.strip():
        count = len(local_only.stdout.strip().splitlines())
        rescue_name = f"rescue-{desc.repo_path.name}"
        _git(desc.repo_path, "branch", rescue_name, desc.base_branch)
        _git(desc.repo_path, "reset", "--hard", f"{desc.push_target}/{desc.base_branch}")
        metadata["rescued"] = rescue_name
        print(f"LOCAL_COMMITS={count} RESCUED_TO={rescue_name}")

    return None, metadata


# ---------------------------------------------------------------------------
# Rebase
# ---------------------------------------------------------------------------

def _rebase_repo(desc: RepoDescriptor, branch: str) -> bool:
    """Rebase feature branch onto base_branch. Returns True on success."""
    _git(desc.repo_path, "checkout", branch)

    if desc.transport == Transport.TWO_HOP:
        has_upstream = _git(desc.repo_path, "remote", "get-url", "upstream")
        fetch_remote = "upstream" if has_upstream.returncode == 0 else "origin"
    else:
        fetch_remote = desc.push_target

    _git(desc.repo_path, "fetch", fetch_remote, desc.base_branch)
    result = _git(desc.repo_path, "rebase", f"{fetch_remote}/{desc.base_branch}")
    if result.returncode != 0:
        _git(desc.repo_path, "rebase", "--abort")
        return False
    return True


# ---------------------------------------------------------------------------
# Merge + Push
# ---------------------------------------------------------------------------

def _merge_and_push_two_hop(
    desc: RepoDescriptor, branch: str, progress_file: Path,
) -> RepoStatus:
    status = RepoStatus(repo_path=desc.repo_path)
    key = _progress_key(desc, branch)

    _git(desc.repo_path, "checkout", desc.base_branch)
    _git(desc.repo_path, "fetch", "origin", desc.base_branch)
    ff = _git(desc.repo_path, "merge", "--ff-only", f"origin/{desc.base_branch}")
    if ff.returncode != 0:
        _git(desc.repo_path, "merge", f"origin/{desc.base_branch}", "--no-edit")

    merge = _git(desc.repo_path, "merge", "--ff-only", branch)
    if merge.returncode != 0:
        merge = _git(desc.repo_path, "merge", branch, "--no-edit")
        if merge.returncode != 0:
            status.error = "merge_failed"
            return status
    status.merged = True
    _write_progress(progress_file, key, "merged")

    if desc.is_workspace:
        _strip_scaffold_from_merge(desc.repo_path)

    sha_r = _git(desc.repo_path, "rev-parse", desc.base_branch)
    landed_sha = sha_r.stdout.strip() if sha_r.returncode == 0 else "unknown"
    status.landed_sha = landed_sha

    push = _git(desc.repo_path, "push", desc.push_target, desc.base_branch, "--no-verify")
    if push.returncode != 0:
        status.error = "local_push_failed"
        return status

    orig_sha = _git(desc.original_path, "rev-parse", desc.base_branch)
    if orig_sha.returncode != 0 or orig_sha.stdout.strip() != landed_sha:
        status.error = "local_verify_failed"
        return status

    has_origin = _git(desc.original_path, "remote", "get-url", "origin")
    if has_origin.returncode == 0:
        remote_push = _git(desc.original_path, "push", "origin", desc.base_branch, "--no-verify")
        if remote_push.returncode != 0:
            status.error = "github_push_failed"
            return status
        ls = _git(desc.original_path, "ls-remote", "origin", desc.base_branch)
        if ls.returncode == 0 and ls.stdout.strip():
            remote_sha = ls.stdout.split()[0]
            if remote_sha != landed_sha:
                status.error = "github_verify_failed"
                return status

    status.pushed = True
    _write_progress(progress_file, key, "pushed")
    return status


SCAFFOLD_FILES = [".plan", "JOURNAL.md", ".execute-progress",
                  ".land-ledger.jsonl", ".artifacts-promoted",
                  ".close-progress", ".close-progress.done",
                  ".close-log.jsonl", ".close-report.json",
                  ".meta", ".epic"]


def _strip_scaffold_from_merge(repo_path: Path) -> None:
    to_remove = [f for f in SCAFFOLD_FILES if (repo_path / f).exists()]
    if not to_remove:
        return
    rm = _git(repo_path, "rm", "-f", "--", *to_remove)
    if rm.returncode == 0:
        _git(repo_path, "commit", "--amend", "--no-edit")


def _merge_and_push_direct(
    desc: RepoDescriptor, branch: str, progress_file: Path,
) -> RepoStatus:
    status = RepoStatus(repo_path=desc.repo_path)
    key = _progress_key(desc, branch)

    pre_merge = _git(desc.repo_path, "rev-parse", "HEAD")
    pre_merge_sha = pre_merge.stdout.strip() if pre_merge.returncode == 0 else ""

    co = _git(desc.repo_path, "checkout", desc.base_branch)
    if co.returncode != 0:
        status.error = "checkout_failed"
        return status

    merge = _git(desc.repo_path, "merge", "--ff-only", branch)
    if merge.returncode != 0:
        status.error = "merge_failed"
        return status
    status.merged = True
    _write_progress(progress_file, key, "merged")

    if desc.is_workspace:
        _strip_scaffold_from_merge(desc.repo_path)

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        push = _git(desc.repo_path, "push", desc.push_target, desc.base_branch, "--no-verify")
        if push.returncode == 0:
            break
        if attempt == max_retries:
            if pre_merge_sha:
                _git(desc.repo_path, "reset", "--hard", pre_merge_sha)
            status.error = "push_failed"
            return status
        _git(desc.repo_path, "fetch", desc.push_target, desc.base_branch)
        rebase = _git(desc.repo_path, "rebase", f"{desc.push_target}/{desc.base_branch}")
        if rebase.returncode != 0:
            _git(desc.repo_path, "rebase", "--abort")
            if pre_merge_sha:
                _git(desc.repo_path, "reset", "--hard", pre_merge_sha)
            status.error = "push_retry_rebase_failed"
            return status

    sha_r = _git(desc.repo_path, "rev-parse", "HEAD")
    landed_sha = sha_r.stdout.strip() if sha_r.returncode == 0 else ""
    status.landed_sha = landed_sha
    status.pushed = True
    _write_progress(progress_file, key, "pushed")

    _git(desc.repo_path, "fetch", desc.push_target, desc.base_branch)
    verify = _git(
        desc.repo_path, "merge-base", "--is-ancestor",
        landed_sha, f"{desc.push_target}/{desc.base_branch}",
    )
    if verify.returncode != 0:
        print(f"PUSH_VERIFY_WARN=landed SHA {landed_sha[:12]} not confirmed")

    if desc.mirror_target:
        mirror = _git(desc.repo_path, "push", desc.mirror_target, desc.base_branch, "--force-with-lease")
        if mirror.returncode != 0:
            print(f"MIRROR_WARN=push to {desc.mirror_target} failed")
        else:
            print(f"MIRRORED_TO={desc.mirror_target}/{desc.base_branch}")

    return status


# ---------------------------------------------------------------------------
# Stamp
# ---------------------------------------------------------------------------

def _stamp_repo(
    desc: RepoDescriptor, branch: str, landed_sha: str, progress_file: Path,
) -> None:
    key = _progress_key(desc, branch)

    tip = _git(desc.repo_path, "log", "-1", "--format=%s", branch)
    if tip.returncode == 0 and tip.stdout.strip().startswith("chore: branch closed"):
        _write_progress(progress_file, key, "stamped")
        return

    _git(desc.repo_path, "checkout", branch)

    issue_match = re.match(r"issue-(\d+)", branch)
    issue_ref = f"  Refs #{issue_match.group(1)}" if issue_match else ""

    _git(
        desc.repo_path, "commit", "--allow-empty",
        "-m", f"chore: branch closed — landed as {landed_sha} on {desc.base_branch}{issue_ref}",
    )

    if desc.transport == Transport.TWO_HOP:
        _git(desc.repo_path, "push", "origin", branch, "--force-with-lease")
    else:
        push_remote = desc.push_target
        has_upstream = _git(desc.repo_path, "remote", "get-url", "upstream")
        if has_upstream.returncode == 0:
            push_remote = "origin"
        if push_remote:
            _git(desc.repo_path, "push", push_remote, branch, "--force-with-lease")

    _write_progress(progress_file, key, "stamped")


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------

def land_batch(
    descriptors: list[RepoDescriptor],
    branch: str,
    progress_file: Path,
) -> LandResult:
    """Execute the shared land flow for a batch of repos.

    Steps: preflight -> rebase -> merge+push -> stamp.
    Project repos land before workspace repos.
    """
    progress = _read_progress(progress_file)
    result = LandResult()

    sorted_descs = sorted(descriptors, key=lambda d: d.is_workspace)

    active: list[RepoDescriptor] = []
    for desc in sorted_descs:
        key = _progress_key(desc, branch)
        if progress.get(key) == "stamped":
            result.repos.append(RepoStatus(
                repo_path=desc.repo_path,
                merged=True, pushed=True, stamped=True, skipped=True,
            ))
        else:
            active.append(desc)

    if not active:
        return result

    # Step 1: Preflight
    print("STAGE=preflight")
    for desc in active:
        if desc.transport == Transport.TWO_HOP:
            err = _preflight_two_hop(desc)
            if err:
                result.repos.append(RepoStatus(repo_path=desc.repo_path, error=err))
                result.success = False
                print("STAGE=preflight STATUS=fail")
                return result
        else:
            err, meta = _preflight_direct(desc)
            if err:
                result.repos.append(RepoStatus(repo_path=desc.repo_path, error=err))
                result.success = False
                print("STAGE=preflight STATUS=fail")
                return result
            if "rescued" in meta:
                result.rescued[desc.repo_path.name] = meta["rescued"]
    print("STAGE=preflight STATUS=pass")

    # Step 2: Rebase
    for attempt in range(1, 4):
        print(f"STAGE=rebase ATTEMPT={attempt}")
        rebase_ok = True
        failed_desc = None
        for desc in active:
            if not _rebase_repo(desc, branch):
                rebase_ok = False
                failed_desc = desc
                break
        if rebase_ok:
            print("STAGE=rebase STATUS=pass")
            break
        if attempt == 3:
            assert failed_desc is not None
            result.repos.append(RepoStatus(
                repo_path=failed_desc.repo_path, error="rebase_conflict",
            ))
            result.success = False
            print("STAGE=rebase STATUS=fail")
            return result

    # Step 3: Merge + Push (project first, then workspace)
    print("STAGE=push")
    landed_shas: dict[str, str] = {}
    has_failure = False

    for desc in active:
        if desc.transport == Transport.TWO_HOP:
            status = _merge_and_push_two_hop(desc, branch, progress_file)
        else:
            status = _merge_and_push_direct(desc, branch, progress_file)
        result.repos.append(status)
        if status.error:
            has_failure = True
        else:
            landed_shas[desc.repo_path.name] = status.landed_sha

    if has_failure:
        result.success = False
        print("STAGE=push STATUS=fail")
        return result
    print("STAGE=push STATUS=pass")

    # Step 4: Stamp all feature branches
    for desc in active:
        sha = landed_shas.get(desc.repo_path.name, "unknown")
        _stamp_repo(desc, branch, sha, progress_file)
        for s in result.repos:
            if s.repo_path == desc.repo_path and not s.skipped:
                s.stamped = True

    return result
