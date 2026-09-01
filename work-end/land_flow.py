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
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

_lib = Path.home() / ".claude" / "lib"
if _lib.exists():
    sys.path.insert(0, str(_lib))
try:
    import worklog as _wl
except ImportError:
    _wl = None


def _record_worklog_end(branch: str, repo_path: str, landed_sha: str) -> None:
    if not _wl:
        return
    try:
        conn = _wl.connect()
        _wl.record_work_end(conn, branch, repo_path, landed_sha=landed_sha)
        conn.close()
    except Exception:
        pass


def _record_rebase_failure(repo_path: str, branch: str,
                           commit_count: int, main_ahead: int,
                           error_detail: str) -> None:
    if not _wl:
        return
    try:
        conn = _wl.connect()
        _wl.record_close_event(
            conn, "rebase_failed", "close", branch,
            repo_path=repo_path,
            commit_count=commit_count, main_ahead=main_ahead,
            error_detail=error_detail[:500],
        )
        conn.close()
    except Exception:
        pass


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


SOURCE_EXTENSIONS = (
    ".java", ".kt", ".xml", ".yaml", ".yml", ".json",
    ".properties", ".sql", ".py", ".ts", ".tsx", ".js",
    ".jsx", ".css", ".scss", ".html",
)


def _verify_content_landed(desc: RepoDescriptor, branch: str) -> str | None:
    """Return error string if branch source content is not on base_branch."""
    result = _git(desc.repo_path, "diff", "--name-only",
                  f"{desc.base_branch}...{branch}")
    if result.returncode != 0:
        return f"diff_failed repo={desc.repo_path.name}"
    source_files = [f for f in result.stdout.strip().split("\n")
                    if f and any(f.endswith(ext) for ext in SOURCE_EXTENSIONS)]
    if not source_files:
        return None
    diff = _git(desc.repo_path, "diff", desc.base_branch, branch,
                "--", *source_files)
    if diff.returncode == 0 and diff.stdout.strip():
        missing = [f for f in _git(desc.repo_path, "diff", "--name-only",
                   desc.base_branch, branch, "--", *source_files)
                   .stdout.strip().split("\n") if f]
        return f"content_not_landed repo={desc.repo_path.name} files={len(missing)}"
    return None


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
    slot_dir: Path, branch: str = "", base_branch: str = "main",
) -> list[RepoDescriptor]:
    """Build RepoDescriptor batch for a slot. Project repos first.

    When branch is specified, only includes repos that have that branch.
    Repos without the branch are reported as skipped.
    """
    descriptors: list[RepoDescriptor] = []
    for entry in sorted(slot_dir.iterdir()):
        if not entry.is_dir() or not (entry / ".git").exists():
            continue
        if entry.name in (".m2", "attic"):
            continue

        if branch:
            has_branch = _git(entry, "branch", "--list", branch)
            if has_branch.returncode != 0 or not has_branch.stdout.strip():
                print(f"SKIP_REPO={entry.name} reason=no_branch branch={branch}")
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


def _is_slot_clone(repo_path: Path) -> bool:
    r = _git(repo_path, "remote", "get-url", "local")
    return r.returncode == 0


def _resolve_original_from_local(repo_path: Path) -> Path:
    r = _git(repo_path, "remote", "get-url", "local")
    if r.returncode == 0:
        return Path(r.stdout.strip())
    return repo_path


def build_branch_batch(
    project_path: Path,
    workspace_path: Path | None,
    branch: str,
    base_branch: str = "main",
) -> list[RepoDescriptor]:
    """Build RepoDescriptor batch for branch mode. Auto-detects slot clones."""
    if _is_slot_clone(project_path):
        original = _resolve_original_from_local(project_path)
        push_target = _resolve_local_push_remote(project_path)
        descs = [
            RepoDescriptor(
                repo_path=project_path,
                original_path=original,
                push_target=push_target,
                base_branch=base_branch,
                is_workspace=False,
                transport=Transport.TWO_HOP,
            ),
        ]
    else:
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
        ws_push_target = _detect_push_target(workspace_path) or ""
        if result.returncode == 0 and result.stdout.strip():
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
        lines = status.stdout.strip().splitlines()
        has_unmerged = any(line[:2] in unmerged for line in lines)
        if has_unmerged:
            return f"unmerged_conflict path={original}"
        has_tracked_changes = any(not line.startswith("??") for line in lines)
        if has_tracked_changes:
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
            # Local push succeeded — work is landed.  GitHub push failed
            # (network, permissions, etc.) — treat as warning, not blocker.
            status.error = "github_push_failed"
            status.pushed = True
            _write_progress(progress_file, key, "pushed")
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
) -> bool:
    """Stamp a branch as closed. Returns True on success, False on failure."""
    key = _progress_key(desc, branch)
    repo_name = desc.repo_path.name

    tip = _git(desc.repo_path, "log", "-1", "--format=%s", branch)
    if tip.returncode == 0 and tip.stdout.strip().startswith("chore: branch closed"):
        _write_progress(progress_file, key, "stamped")
        return True

    if tip.returncode != 0:
        print(f"STAMP_WARN={repo_name} reason=branch_tip_unreadable branch={branch}")
        return False

    co = _git(desc.repo_path, "checkout", branch)
    if co.returncode != 0:
        _git(desc.repo_path, "stash", "push", "-u", "-m", "work-end: stash before stamp")
        co2 = _git(desc.repo_path, "checkout", branch)
        if co2.returncode != 0:
            print(f"STAMP_FAIL={repo_name} reason=checkout_failed branch={branch}")
            return False

    issue_match = re.match(r"issue-(\d+)", branch)
    issue_ref = f"  Refs #{issue_match.group(1)}" if issue_match else ""

    commit = _git(
        desc.repo_path, "commit", "--allow-empty",
        "-m", f"chore: branch closed — landed as {landed_sha} on {desc.base_branch}{issue_ref}",
    )
    if commit.returncode != 0:
        print(f"STAMP_FAIL={repo_name} reason=commit_failed detail={commit.stderr.strip()}")
        return False

    if desc.transport == Transport.TWO_HOP:
        push = _git(desc.repo_path, "push", "origin", branch, "--force-with-lease", "--no-verify")
    else:
        push_remote = desc.push_target
        has_upstream = _git(desc.repo_path, "remote", "get-url", "upstream")
        if has_upstream.returncode == 0:
            push_remote = "origin"
        push = None
        if push_remote:
            push = _git(desc.repo_path, "push", push_remote, branch, "--force-with-lease", "--no-verify")

    if push and push.returncode != 0:
        print(f"STAMP_WARN={repo_name} reason=stamp_push_failed detail={push.stderr.strip()}")

    _write_progress(progress_file, key, "stamped")
    _record_worklog_end(branch, str(desc.repo_path), landed_sha)
    return True


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

    # Step 1: Preflight (skip workspace — stamp only, no push needed)
    print("STAGE=preflight")
    for desc in active:
        if desc.is_workspace:
            continue
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

    # Step 2: Rebase (skip workspace — stamp only)
    for attempt in range(1, 4):
        print(f"STAGE=rebase ATTEMPT={attempt}")
        rebase_ok = True
        failed_desc = None
        for desc in active:
            if desc.is_workspace:
                continue
            if not _rebase_repo(desc, branch):
                rebase_ok = False
                failed_desc = desc
                break
        if rebase_ok:
            print("STAGE=rebase STATUS=pass")
            break
        if attempt == 3:
            assert failed_desc is not None
            branch_count = _git(failed_desc.repo_path, "rev-list", "--count", f"{failed_desc.base_branch}..{branch}")
            main_count = _git(failed_desc.repo_path, "rev-list", "--count", f"{branch}..{failed_desc.base_branch}")
            _record_rebase_failure(
                repo_path=str(failed_desc.repo_path),
                branch=branch,
                commit_count=int(branch_count.stdout.strip()) if branch_count.returncode == 0 else 0,
                main_ahead=int(main_count.stdout.strip()) if main_count.returncode == 0 else 0,
                error_detail="rebase_conflict_after_3_retries",
            )
            result.repos.append(RepoStatus(
                repo_path=failed_desc.repo_path, error="rebase_conflict",
            ))
            result.success = False
            print("STAGE=rebase STATUS=fail")
            return result

    # Step 3: Merge + Push (project repos only — workspace uses selective promotion)
    print("STAGE=push")
    landed_shas: dict[str, str] = {}
    failed_repos: list[str] = []

    for desc in active:
        if desc.is_workspace:
            result.repos.append(RepoStatus(
                repo_path=desc.repo_path, merged=True, pushed=True,
            ))
            continue
        if desc.transport == Transport.TWO_HOP:
            status = _merge_and_push_two_hop(desc, branch, progress_file)
        else:
            status = _merge_and_push_direct(desc, branch, progress_file)
        result.repos.append(status)
        if status.error:
            if status.error == "github_push_failed" and status.pushed:
                # Local push succeeded — record landed SHA, warn instead of fail
                landed_shas[desc.repo_path.name] = status.landed_sha
                print(f"PUSH_WARN={desc.repo_path.name} error={status.error}")
            else:
                failed_repos.append(desc.repo_path.name)
                print(f"PUSH_FAIL={desc.repo_path.name} error={status.error}")
        else:
            landed_shas[desc.repo_path.name] = status.landed_sha

    if failed_repos:
        result.success = False
        print(f"STAGE=push STATUS=partial failed={','.join(failed_repos)}")
    else:
        print("STAGE=push STATUS=pass")

    # Step 3b: Verify content landed (postcondition)
    print("STAGE=verify_content")
    for desc in active:
        if desc.is_workspace:
            continue
        if desc.repo_path.name in failed_repos:
            continue
        err = _verify_content_landed(desc, branch)
        if err:
            result.repos.append(RepoStatus(
                repo_path=desc.repo_path, error="content_not_landed",
            ))
            result.success = False
            print(f"CONTENT_NOT_LANDED={desc.repo_path.name}")
    if not result.success:
        print("STAGE=verify_content STATUS=fail")
        return result
    print("STAGE=verify_content STATUS=pass")

    # Step 4: Stamp all feature branches (even if some repos failed push —
    # repos that pushed successfully still need stamping)
    print("STAGE=stamp")
    stamp_failures: list[str] = []
    for desc in active:
        repo_name = desc.repo_path.name
        if repo_name in failed_repos:
            print(f"STAMP_SKIP={repo_name} reason=push_failed")
            continue
        sha = landed_shas.get(repo_name, "")
        if desc.is_workspace and not sha:
            proj_sha = next((s for s in landed_shas.values()), "unknown")
            sha = proj_sha
        ok = _stamp_repo(desc, branch, sha, progress_file)
        for s in result.repos:
            if s.repo_path == desc.repo_path and not s.skipped:
                s.stamped = ok
        if not ok:
            stamp_failures.append(repo_name)

    if stamp_failures:
        result.success = False
        print(f"STAGE=stamp STATUS=partial failed={','.join(stamp_failures)}")
    else:
        print("STAGE=stamp STATUS=pass")

    return result
