#!/usr/bin/env python3
"""
work_end_execute.py — Per-repo orchestrator for work-end Execute step.

Three subcommands that bracket the LLM squash analysis:

  promote  — promote artifacts from workspace branch to destinations
  rebase   — rebase branch onto base branch (all repos in slot mode)
  land     — apply squash plan, build, push, stamp (all repos)

Progress tracking via .execute-progress enables crash recovery.

Usage:
    python3 work_end_execute.py promote workspace=<path> project=<path> branch=<name>
    python3 work_end_execute.py rebase  project=<path> branch=<name> base_branch=<base>
    python3 work_end_execute.py land    project=<path> branch=<name> base_branch=<base> workspace=<path>

Output: KEY=value lines (stdout). Errors on stderr, exit code 1.
"""

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import parse_args, detect_topology


# ---------------------------------------------------------------------------
# Library API — typed interface for command layer
# ---------------------------------------------------------------------------

@dataclass
class RebaseResult:
    success: bool
    branch: str | None = None
    base: str | None = None
    error: str | None = None


@dataclass
class MergeResult:
    success: bool
    error: str | None = None


@dataclass
class PushResult:
    success: bool
    attempts: int = 1
    error: str | None = None


def rebase_onto_base(project: str, branch: str, base_branch: str = "main") -> RebaseResult:
    """Rebase branch onto base branch."""
    result = git(project, "fetch", "origin", base_branch)

    result = git(project, "rebase", base_branch)
    if result.returncode != 0:
        git(project, "rebase", "--abort")
        return RebaseResult(False, branch, base_branch, result.stderr.strip())
    return RebaseResult(True, branch, base_branch)


def merge_to_main(project: str, branch: str, base_branch: str = "main") -> MergeResult:
    """FF-only merge branch into local main."""
    result = git(project, "checkout", base_branch)
    if result.returncode != 0:
        return MergeResult(False, f"checkout_{base_branch}_failed:{result.stderr.strip()}")

    result = git(project, "merge", "--ff-only", branch)
    if result.returncode != 0:
        return MergeResult(False, f"merge_failed:{result.stderr.strip()}")
    return MergeResult(True)


def push_to_remote(project: str, base_branch: str = "main",
                   max_retries: int = 3) -> PushResult:
    """Push base branch to remote with retries."""
    for attempt in range(1, max_retries + 1):
        result = git(project, "push", "origin", base_branch)
        if result.returncode == 0:
            return PushResult(True, attempt)
    return PushResult(False, max_retries, f"push_failed_after_{max_retries}_retries")


def git(repo: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True, text=True,
        timeout=30,
    )


def read_progress(progress_path: Path) -> dict[str, str]:
    if not progress_path.exists():
        return {}
    result: dict[str, str] = {}
    for line in progress_path.read_text().splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip()
    return result


def write_progress(progress_path: Path, key: str, value: str) -> None:
    progress = read_progress(progress_path)
    progress[key] = value
    lines = [f"{k}={v}" for k, v in progress.items()]
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    progress_path.write_text("\n".join(lines) + "\n")


def cmd_promote(opts: dict[str, str]) -> int:
    workspace = opts.get("workspace", "")
    project = opts.get("project", "")
    branch = opts.get("branch", "")

    if not workspace or not project or not branch:
        print("ERROR=MISSING_ARGS")
        print("ERROR_DETAIL=workspace=, project=, and branch= are required")
        return 1

    progress_path = Path(workspace) / "design" / ".execute-progress"
    progress = read_progress(progress_path)

    if progress.get("default") == "promoted":
        print("PROMOTED=yes")
        print("SKIPPED=already promoted")
        return 0

    close_artifacts = Path(__file__).parent / "close_artifacts.py"
    result = subprocess.run(
        [sys.executable, str(close_artifacts), workspace, project, branch],
        capture_output=True, text=True,
        timeout=60,
    )

    for line in result.stdout.splitlines():
        print(line)

    if result.returncode != 0:
        print("ERROR=PROMOTE_FAILED")
        print(f"ERROR_DETAIL=close_artifacts.py exited {result.returncode}")
        return 1

    write_progress(progress_path, "default", "promoted")
    print("PROMOTED=yes")
    return 0


def cmd_rebase(opts: dict[str, str]) -> int:
    project = opts.get("project", "")
    branch = opts.get("branch", "")
    base_branch = opts.get("base_branch", "main")

    if not project or not branch:
        print("ERROR=MISSING_ARGS")
        print("ERROR_DETAIL=project= and branch= are required")
        return 1

    result = git(project, "fetch", "origin", base_branch)
    if result.returncode != 0:
        print("FETCH_WARNING=no network — using local base", file=sys.stderr)

    result = git(project, "rebase", base_branch)
    if result.returncode != 0:
        git(project, "rebase", "--abort")
        print("ERROR=REBASE_CONFLICT")
        print(f"ERROR_DETAIL={result.stderr.strip()}")
        return 1

    print("REBASED=yes")
    return 0


def cmd_land(opts: dict[str, str]) -> int:
    project = opts.get("project", "")
    branch = opts.get("branch", "")
    base_branch = opts.get("base_branch", "main")
    workspace = opts.get("workspace", "")

    if not project or not branch:
        print("ERROR=MISSING_ARGS")
        print("ERROR_DETAIL=project= and branch= are required")
        return 1

    progress_path = (
        Path(workspace) / "design" / ".execute-progress"
        if workspace
        else Path(project) / ".execute-progress"
    )
    progress = read_progress(progress_path)

    repo_name = Path(project).name

    progress_key = f"{repo_name}:{branch}"
    if progress.get(progress_key) == "stamped":
        print(f"LANDED=yes")
        print(f"SKIPPED={repo_name} already stamped")
        return 0

    # Detect topology and sync main from blessed before merging
    fork_remote, blessed_remote = detect_topology(project)
    push_target = blessed_remote if blessed_remote else fork_remote

    checkout_result = git(project, "checkout", base_branch)
    if checkout_result.returncode != 0:
        print("ERROR=CHECKOUT_FAILED")
        print(f"ERROR_DETAIL=cannot checkout {base_branch}: {checkout_result.stderr.strip()}")
        return 1

    # Fetch blessed main and check for local-only commits
    if push_target:
        git(project, "fetch", push_target, base_branch)
        local_only = git(project, "rev-list", f"{push_target}/{base_branch}..{base_branch}")
        if local_only.returncode == 0 and local_only.stdout.strip():
            count = len(local_only.stdout.strip().splitlines())
            print(f"LOCAL_COMMITS={count}")
            rescue_branch = f"rescue-{branch}"
            git(project, "branch", rescue_branch, base_branch)
            git(project, "reset", "--hard", f"{push_target}/{base_branch}")
            print(f"RESCUED_TO={rescue_branch}")
            print(f"MAIN_RESET=yes")

    # Merge branch into main (ff-only) before pushing
    merge_result = git(project, "merge", "--ff-only", branch)
    if merge_result.returncode != 0:
        print("ERROR=MERGE_FAILED")
        print(f"ERROR_DETAIL=ff-only merge of {branch} into {base_branch} failed: {merge_result.stderr.strip()}")
        return 1
    write_progress(progress_path, progress_key,"merged")

    # Push main to blessed remote
    if not push_target:
        print("ERROR=NO_REMOTE")
        print("ERROR_DETAIL=no origin or upstream remote configured")
        return 1

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        push_result = git(project, "push", push_target, base_branch)
        if push_result.returncode == 0:
            break
        if attempt == max_retries:
            print("ERROR=PUSH_FAILED")
            print(f"ERROR_DETAIL=push {base_branch} to {push_target} failed after {max_retries} attempts: {push_result.stderr.strip()}")
            return 1
        print(f"PUSH_RETRY={attempt}")
        git(project, "fetch", push_target, base_branch)
        rebase_result = git(project, "rebase", f"{push_target}/{base_branch}")
        if rebase_result.returncode != 0:
            git(project, "rebase", "--abort")
            print("ERROR=PUSH_RETRY_REBASE_FAILED")
            print(f"ERROR_DETAIL=rebase onto {push_target}/{base_branch} failed during retry: {rebase_result.stderr.strip()}")
            return 1

    print(f"PUSHED_TO={push_target}/{base_branch}")
    write_progress(progress_path, progress_key,"pushed")

    # Mirror to fork if fork model (fork main tracks blessed)
    if blessed_remote and fork_remote and fork_remote != blessed_remote:
        mirror_result = git(project, "push", fork_remote, base_branch, "--force-with-lease")
        if mirror_result.returncode != 0:
            print(f"MIRROR_WARN=push to {fork_remote} failed: {mirror_result.stderr.strip()}")
        else:
            print(f"MIRRORED_TO={fork_remote}/{base_branch}")

    # Stamp the branch
    stamp_script = Path(__file__).parent / "land_branch.py"
    stamp_result = subprocess.run(
        [sys.executable, str(stamp_script), "stamp", project,
         f"branch={branch}", f"base_branch={base_branch}"],
        capture_output=True, text=True,
        timeout=30,
    )

    stamp_ok = False
    landed_sha = ""
    for line in stamp_result.stdout.splitlines():
        if line.startswith("STAMP=ok"):
            stamp_ok = True
        if line.startswith("LANDED_SHA="):
            landed_sha = line.split("=", 1)[1]
        print(line)

    if not stamp_ok:
        print("ERROR=STAMP_FAILED")
        if stamp_result.stderr.strip():
            print(stamp_result.stderr.strip(), file=sys.stderr)
        return 1
    write_progress(progress_path, progress_key,"stamped")

    # Merge and stamp workspace branch
    if workspace:
        ws_branch_exists = git(workspace, "branch", "--list", branch)
        if ws_branch_exists.returncode == 0 and ws_branch_exists.stdout.strip():
            tip_msg = git(workspace, "log", "-1", "--format=%s", branch)
            if not (tip_msg.returncode == 0 and tip_msg.stdout.strip().startswith("chore: branch closed")):
                git(workspace, "checkout", base_branch)
                ws_merge = git(workspace, "merge", "--ff-only", branch)
                if ws_merge.returncode != 0:
                    git(workspace, "merge", branch, "--no-edit")
                ws_landed = git(workspace, "rev-parse", "HEAD")
                ws_sha = ws_landed.stdout.strip() if ws_landed.returncode == 0 else ""
                ws_push_target = detect_topology(workspace)[0]
                if ws_push_target:
                    git(workspace, "push", ws_push_target, base_branch)
                git(workspace, "checkout", branch)
                git(workspace, "commit", "--allow-empty", "-m",
                    f"chore: branch closed — landed as {ws_sha} on {base_branch}")
                git(workspace, "checkout", base_branch)

    print(f"LANDED=yes")
    print(f"LANDED_SHA={landed_sha}")
    return 0


def cmd_write_marker(opts: dict[str, str]) -> int:
    slot_path = opts.get("slot_path", "")
    branch = opts.get("branch", "")

    if not slot_path:
        print("ERROR=MISSING_ARGS")
        print("ERROR_DETAIL=slot_path= is required")
        return 1
    if not branch:
        print("ERROR=MISSING_ARGS")
        print("ERROR_DETAIL=branch= is required")
        return 1

    slot_dir = Path(slot_path)
    if not slot_dir.is_dir():
        print("ERROR=BAD_PATH")
        print(f"ERROR_DETAIL=slot_path={slot_path} not found")
        return 1

    import datetime
    marker = slot_dir / ".phase-a-complete"
    marker.write_text(
        f"branch={branch}\n"
        f"timestamp={datetime.datetime.now(datetime.timezone.utc).isoformat()}\n"
    )
    print(f"MARKER_WRITTEN={marker}")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: work_end_execute.py <promote|rebase|land|write-marker> key=value ...",
              file=sys.stderr)
        return 1

    command = sys.argv[1]
    opts = parse_args(sys.argv[2:])

    if command == "promote":
        return cmd_promote(opts)
    elif command == "rebase":
        return cmd_rebase(opts)
    elif command == "land":
        return cmd_land(opts)
    elif command == "write-marker":
        return cmd_write_marker(opts)
    else:
        print("ERROR=UNKNOWN_COMMAND")
        print(f"ERROR_DETAIL=unknown command '{command}' — use promote, rebase, land, or write-marker")
        return 1


if __name__ == "__main__":
    sys.exit(main())
