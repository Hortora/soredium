#!/usr/bin/env python3
"""
branch_create.py — Externalized git operations for work-start

Subcommands:

    create-branches <project> <workspace> branch=<name> [base=<base>]
        Create matching branches in project and workspace atomically.
        Project branch from current HEAD (or <base> if provided).
        If project fails: abort, no cleanup.
        If workspace fails: delete project branch, abort.
        Output: CREATED=yes

    commit-scaffold <workspace> branch=<name>
        Stage and commit .plan and JOURNAL.md, then push.
        Output: COMMITTED=yes, PUSHED=yes|no

    sync-main <project> <workspace> [base=<branch>]
        Sync local main with remote before branch creation.
        Detects fork model (upstream, fork, or single remote) and
        applies the correct fetch/merge-or-rebase/push sequence.
        Merges instead of rebasing when local commits are already
        pushed to origin — preserves SHAs that feature branches
        reference.
        Non-fatal — network errors warn but don't fail.
        Output: SYNCED=yes MODEL=upstream|fork|single [WARN=...]

Exit codes:
    0  success
    1  error
"""

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


def run_git(repo: str, *args: str) -> tuple[bool, str]:
    """Run git command. Returns (success, stdout)."""
    try:
        result = subprocess.run(
            ["git", "-C", repo] + list(args),
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0, result.stdout.strip()
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# Library API — typed interface for command layer
# ---------------------------------------------------------------------------

@dataclass
class CreateResult:
    branch: str
    project_created: bool
    workspace_created: bool
    error: str | None = None


def create_branches_typed(project: str, workspace: str, branch: str,
                          base: str | None = None) -> CreateResult:
    """Create branches in project and workspace atomically. Returns typed result."""
    if base:
        ok, err = run_git(project, "checkout", "-b", branch, base)
    else:
        ok, err = run_git(project, "checkout", "-b", branch)

    if not ok:
        return CreateResult(branch, False, False, f"project_branch_failed:{err}")

    ok, err = run_git(workspace, "checkout", "-b", branch)
    if not ok:
        run_git(project, "checkout", "-")
        run_git(project, "branch", "-D", branch)
        return CreateResult(branch, False, False, f"workspace_branch_failed:{err}")

    return CreateResult(branch, True, True)


# ---------------------------------------------------------------------------
# CLI entry points (print KEY=value output)
# ---------------------------------------------------------------------------

def create_branches(project: str, workspace: str, branch: str, base: str | None) -> int:
    """Create branches in project and workspace atomically."""
    result = create_branches_typed(project, workspace, branch, base)
    if result.error:
        print(f"ERROR={result.error}")
        return 1
    print("CREATED=yes")
    return 0


def commit_scaffold(workspace: str, branch: str) -> int:
    """Commit scaffold files and push."""
    import os

    ws_path = Path(workspace)
    ws_init = Path(__file__).parent.parent / "workspace-init"
    if str(ws_init) not in sys.path:
        sys.path.insert(0, str(ws_init))
    try:
        from workspace_create import validate_workspace_location
        loc_err = validate_workspace_location(ws_path)
        if loc_err:
            print("ERROR=nested_workspace")
            print(f"ERROR_DETAIL={loc_err}")
            return 1
    except ImportError:
        pass

    current_ok, current_branch = run_git(workspace, "branch", "--show-current")
    if current_ok and current_branch != branch:
        print(f"ERROR=wrong_branch")
        print(f"ERROR_DETAIL=workspace is on '{current_branch}', expected '{branch}'")
        return 1

    files_to_add = [".plan", "JOURNAL.md"]
    ok, _ = run_git(workspace, "add", *files_to_add)
    if not ok:
        print("ERROR=add_failed")
        return 1

    commit_msg = f"init({branch}): scaffold workspace branch"
    ok, _ = run_git(workspace, "commit", "-m", commit_msg)
    if not ok:
        print("ERROR=commit_failed")
        return 1

    push_ok, _ = run_git(workspace, "push", "-u", "origin", branch)

    print("COMMITTED=yes")
    print(f"PUSHED={'yes' if push_ok else 'no'}")
    return 0


def _rev_count(repo: str, range_spec: str) -> int:
    ok, out = run_git(repo, "rev-list", "--count", range_spec)
    if ok and out.strip():
        return int(out.strip())
    return 0


def _has_shared_fork_commits(repo: str, blessed_remote: str,
                             origin_remote: str, base: str) -> int:
    """Count commits on origin that aren't on the blessed remote.

    These are fork-only commits already pushed. Rebase would rewrite
    them with new SHAs, breaking any branch based on the old SHAs.
    """
    return _rev_count(repo, f"{blessed_remote}/{base}..{origin_remote}/{base}")


def _get_patch_ids(repo: str, rev_range: str) -> dict[str, str]:
    """Map patch-id -> commit SHA for commits in the given range."""
    ok, log_out = run_git(repo, "log", "--format=%H", rev_range)
    if not ok or not log_out.strip():
        return {}
    result = {}
    for sha in log_out.strip().splitlines():
        sha = sha.strip()
        if not sha:
            continue
        diff_proc = subprocess.run(
            ["git", "-C", repo, "diff-tree", "-p", sha],
            capture_output=True, text=True,
        )
        if diff_proc.returncode != 0 or not diff_proc.stdout.strip():
            continue
        pid_proc = subprocess.run(
            ["git", "patch-id", "--stable"],
            input=diff_proc.stdout,
            capture_output=True, text=True,
        )
        if pid_proc.returncode == 0 and pid_proc.stdout.strip():
            parts = pid_proc.stdout.strip().split()
            if len(parts) >= 1:
                result[parts[0]] = sha
    return result


def _find_duplicate_commits(repo: str, local_range: str,
                            remote_range: str) -> list[tuple[str, str, str]]:
    """Find commits with identical content on both sides of a merge.

    Two-stage: message pre-filter (fast) then patch-id confirmation (precise).
    Returns [(local_sha, remote_sha, subject)] for confirmed duplicates.
    """
    ok, local_log = run_git(repo, "log", "--format=%H %s", local_range)
    if not ok or not local_log.strip():
        return []
    ok, remote_log = run_git(repo, "log", "--format=%H %s", remote_range)
    if not ok or not remote_log.strip():
        return []

    def parse_log(raw: str) -> list[tuple[str, str]]:
        entries = []
        for line in raw.strip().splitlines():
            parts = line.split(" ", 1)
            if len(parts) == 2:
                entries.append((parts[0], parts[1]))
        return entries

    local_commits = parse_log(local_log)
    remote_commits = parse_log(remote_log)

    remote_by_subject: dict[str, list[str]] = {}
    for sha, subj in remote_commits:
        remote_by_subject.setdefault(subj, []).append(sha)

    candidates = []
    for local_sha, subj in local_commits:
        if subj in remote_by_subject:
            for remote_sha in remote_by_subject[subj]:
                candidates.append((local_sha, remote_sha, subj))

    if not candidates:
        return []

    local_patches = _get_patch_ids(repo, local_range)
    remote_patches = _get_patch_ids(repo, remote_range)

    local_sha_to_pid = {sha: pid for pid, sha in local_patches.items()}
    remote_sha_to_pid = {sha: pid for pid, sha in remote_patches.items()}

    confirmed = []
    for local_sha, remote_sha, subj in candidates:
        local_pid = local_sha_to_pid.get(local_sha)
        remote_pid = remote_sha_to_pid.get(remote_sha)
        if local_pid and remote_pid and local_pid == remote_pid:
            confirmed.append((local_sha, remote_sha, subj))

    return confirmed


def _rebase_dropping(repo: str, blessed_remote: str, base: str,
                     drop_shas: set[str]) -> bool:
    """Rebase onto blessed, dropping commits whose SHAs are in drop_shas."""
    import os
    import tempfile

    if not drop_shas:
        ok, _ = run_git(repo, "rebase", f"{blessed_remote}/{base}")
        return ok

    short_shas = set()
    for sha in drop_shas:
        short_shas.add(sha[:7])

    fd, script_path = tempfile.mkstemp(suffix=".py")
    os.close(fd)
    with open(script_path, "w") as f:
        f.write("import sys\n")
        f.write(f"drops = {short_shas!r}\n")
        f.write("path = sys.argv[1]\n")
        f.write("with open(path) as fh: lines = fh.readlines()\n")
        f.write("kept = []\n")
        f.write("for line in lines:\n")
        f.write("    parts = line.split()\n")
        f.write("    if len(parts) >= 2 and parts[0] == 'pick':\n")
        f.write("        if any(parts[1].startswith(s) for s in drops):\n")
        f.write("            continue\n")
        f.write("    kept.append(line)\n")
        f.write("with open(path, 'w') as fh: fh.writelines(kept)\n")

    env = dict(os.environ)
    env["GIT_SEQUENCE_EDITOR"] = f"python3 {script_path}"
    try:
        proc = subprocess.run(
            ["git", "-C", repo, "rebase", "-i", f"{blessed_remote}/{base}"],
            capture_output=True, text=True, env=env,
        )
        return proc.returncode == 0
    finally:
        os.unlink(script_path)


def _sync_repo(repo: str, blessed_remote: str, origin_remote: str,
               base: str, warnings: list[str], label: str) -> str:
    """Sync a single repo. Returns 'merged', 'rebased', 'fast-forward', 'reconciled', or 'skipped'."""
    ok, _ = run_git(repo, "fetch", blessed_remote)
    if not ok:
        warnings.append(f"fetch_{label}_failed")
        return "skipped"

    if origin_remote != blessed_remote:
        run_git(repo, "fetch", origin_remote)

    local_range = f"{blessed_remote}/{base}..{base}"
    remote_range = f"{base}..{blessed_remote}/{base}"
    duplicates = _find_duplicate_commits(repo, local_range, remote_range)

    if duplicates:
        for local_sha, remote_sha, subj in duplicates:
            print(f"DUPLICATE_DETAIL={local_sha[:12]}:{remote_sha[:12]}:{subj[:60]}")
        print(f"DUPLICATE_COMMITS={len(duplicates)} repo={Path(repo).name}")

        blessed_patches = _get_patch_ids(repo, remote_range)
        local_patches = _get_patch_ids(repo, local_range)
        drop_shas = {sha for pid, sha in local_patches.items()
                     if pid in blessed_patches}

        ok = _rebase_dropping(repo, blessed_remote, base, drop_shas)
        if not ok:
            run_git(repo, "rebase", "--abort")
            warnings.append(f"reconcile_{label}_failed")
            return "skipped"

        if origin_remote != blessed_remote:
            run_git(repo, "push", origin_remote, base, "--force-with-lease", "--no-verify")

        print(f"RECONCILED={len(drop_shas)} repo={Path(repo).name}")
        print(f"STRATEGY=reconcile repo={Path(repo).name}")
        return "reconciled"

    if origin_remote != blessed_remote:
        shared = _has_shared_fork_commits(repo, blessed_remote, origin_remote, base)
        if shared > 0:
            print(f"MERGE_REASON=shared_on_origin={shared} repo={Path(repo).name}")
            ok, _ = run_git(repo, "merge", f"{blessed_remote}/{base}", "--no-edit")
            if not ok:
                run_git(repo, "merge", "--abort")
                warnings.append(f"merge_{label}_failed")
                return "skipped"
            ok, _ = run_git(repo, "push", origin_remote, base, "--no-verify")
            if not ok:
                warnings.append(f"push_{label}_failed")
            print(f"STRATEGY=merge repo={Path(repo).name}")
            return "merged"

    ok, _ = run_git(repo, "rebase", f"{blessed_remote}/{base}")
    if not ok:
        run_git(repo, "rebase", "--abort")
        warnings.append(f"rebase_{label}_failed")
        return "skipped"

    if origin_remote != blessed_remote:
        ok, _ = run_git(repo, "push", origin_remote, base, "--force-with-lease", "--no-verify")
        if not ok:
            warnings.append(f"push_{label}_failed")

    behind = _rev_count(repo, f"{base}..{blessed_remote}/{base}")
    strategy = "fast-forward" if behind == 0 else "rebase"
    print(f"STRATEGY={strategy} repo={Path(repo).name}")
    return strategy


def _verify_sync(repo: str, blessed_remote: str, base: str,
                 warnings: list[str], label: str) -> None:
    """Post-sync verification: local main must contain all blessed commits."""
    behind = _rev_count(repo, f"{base}..{blessed_remote}/{base}")
    if behind > 0:
        warnings.append(f"verify_{label}_behind={behind}")
        print(f"VERIFY_FAIL={label} behind_blessed={behind} repo={Path(repo).name}")


def _check_orphaned_branches(repo: str, base: str, pre_sync_sha: str,
                             warnings: list[str], label: str) -> None:
    """Check if any feature branches lost their merge-base with main."""
    ok, branches = run_git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/")
    if not ok:
        return
    for branch in branches.splitlines():
        branch = branch.strip()
        if not branch or branch == base:
            continue
        ok, merge_base = run_git(repo, "merge-base", branch, base)
        if not ok:
            continue
        ok, is_ancestor = run_git(repo, "merge-base", "--is-ancestor", merge_base.strip(), base)
        if not ok:
            warnings.append(f"orphaned_branch_{label}={branch}")
            print(f"WARN=orphaned_branch repo={Path(repo).name} branch={branch}")


def sync_main(project: str, workspace: str, base: str) -> int:
    """Sync local base branch with remote before branch creation."""
    warnings: list[str] = []

    has_upstream, _ = run_git(project, "remote", "get-url", "upstream")
    has_fork, _ = run_git(project, "remote", "get-url", "fork")

    pre_sha_ok, pre_sync_sha = run_git(project, "rev-parse", base)

    if has_upstream:
        model = "upstream"
        _sync_repo(project, "upstream", "origin", base, warnings, "upstream")
    elif has_fork:
        model = "fork"
        _sync_repo(project, "origin", "fork", base, warnings, "fork")
    else:
        model = "single"
        _sync_repo(project, "origin", "origin", base, warnings, "origin")

    blessed = "upstream" if has_upstream else "origin"
    _verify_sync(project, blessed, base, warnings, "project")

    if pre_sha_ok:
        _check_orphaned_branches(project, base, pre_sync_sha, warnings, "project")

    if has_upstream:
        fork_ahead = _rev_count(project, f"upstream/{base}..origin/{base}")
        upstream_ahead = _rev_count(project, f"origin/{base}..upstream/{base}")
        if fork_ahead > 0:
            print(f"DRIFT=fork_ahead={fork_ahead}")
        if upstream_ahead > 0:
            print(f"DRIFT=upstream_ahead={upstream_ahead}")
        if fork_ahead > 10 or upstream_ahead > 10:
            warnings.append("significant_drift")

    _sync_repo(workspace, "origin", "origin", "main", warnings, "workspace")
    _verify_sync(workspace, "origin", "main", warnings, "workspace")

    synced = "yes" if not warnings else "partial"
    print(f"SYNCED={synced}")
    print(f"MODEL={model}")
    for w in warnings:
        print(f"WARN={w}")
    return 0


def parse_kv_args(args: list[str]) -> dict[str, str]:
    """Parse key=value arguments into dict."""
    result: dict[str, str] = {}
    for arg in args:
        if "=" in arg:
            key, _, val = arg.partition("=")
            result[key] = val
    return result


def main() -> int:
    if len(sys.argv) < 2:
        print("ERROR=missing_subcommand")
        return 1

    cmd = sys.argv[1]

    if cmd == "create-branches":
        if len(sys.argv) < 4:
            print("ERROR=missing_args")
            return 1
        project = sys.argv[2]
        workspace = sys.argv[3]
        kv = parse_kv_args(sys.argv[4:])
        branch = kv.get("branch")
        if not branch:
            print("ERROR=missing_branch")
            return 1
        base = kv.get("base") or None
        return create_branches(project, workspace, branch, base)

    elif cmd == "commit-scaffold":
        if len(sys.argv) < 3:
            print("ERROR=missing_args")
            return 1
        workspace = sys.argv[2]
        kv = parse_kv_args(sys.argv[3:])
        branch = kv.get("branch")
        if not branch:
            print("ERROR=missing_branch")
            return 1
        return commit_scaffold(workspace, branch)

    elif cmd == "sync-main":
        if len(sys.argv) < 4:
            print("ERROR=missing_args")
            return 1
        project = sys.argv[2]
        workspace = sys.argv[3]
        kv = parse_kv_args(sys.argv[4:])
        base = kv.get("base", "main")
        return sync_main(project, workspace, base)

    else:
        print("ERROR=unknown_subcommand")
        return 1


if __name__ == "__main__":
    sys.exit(main())
