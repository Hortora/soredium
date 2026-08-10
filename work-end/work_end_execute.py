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

import datetime
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import parse_args, detect_topology


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


def _detect_slot(project: str) -> tuple[Path | None, list[str]]:
    """Detect if project is inside a slot clone. Returns (slot_dir, repo_names) or (None, [])."""
    result = subprocess.run(
        ["git", "-C", project, "remote", "get-url", "origin"],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        return None, []
    origin = Path(result.stdout.strip())
    if not origin.is_dir():
        return None, []

    project_path = Path(project).resolve()
    for dir_name in ("slots", "worktrees"):
        parts = project_path.parts
        try:
            idx = parts.index(dir_name)
        except ValueError:
            continue
        if idx + 1 < len(parts):
            slot_dir = Path(*parts[:idx + 2])
            if slot_dir.exists():
                repos = sorted([
                    d.name for d in slot_dir.iterdir()
                    if d.is_dir() and (d / ".git").exists()
                    and d.name not in (".m2", "attic")
                    and not (d.name == "work" or d.name.startswith("work-"))
                ])
                if repos:
                    return slot_dir, repos
    return None, []


def _resolve_original(repo_path: Path) -> Path:
    """Resolve the original repo that a slot clone was made from."""
    git_path = repo_path / ".git"
    if git_path.is_file():
        result = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            common = Path(result.stdout.strip())
            if not common.is_absolute():
                common = (repo_path / common).resolve()
            return common.parent

    result = subprocess.run(
        ["git", "-C", str(repo_path), "remote", "get-url", "origin"],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode == 0:
        origin = Path(result.stdout.strip())
        if origin.is_dir():
            return origin.resolve()
    return repo_path


def _land_slot(slot_dir: Path, repos: list[str], branch: str,
               base_branch: str, workspace: str) -> int:
    """Land all repos in a slot via two-hop push (slot → original → GitHub)."""
    progress_path = slot_dir / ".execute-progress"
    progress = read_progress(progress_path)

    print("STAGE=preflight")
    for repo_name in repos:
        original = _resolve_original(slot_dir / repo_name)
        cur = git(str(original), "branch", "--show-current")
        cur_branch = cur.stdout.strip() if cur.returncode == 0 else ""
        if cur_branch != base_branch:
            print("ERROR=PREFLIGHT_FAILED")
            print(f"ERROR_DETAIL={repo_name}: original not on {base_branch} (on {cur_branch})")
            return 1
        status = git(str(original), "status", "--porcelain")
        if status.returncode == 0 and status.stdout.strip():
            print("ERROR=PREFLIGHT_FAILED")
            print(f"ERROR_DETAIL={repo_name}: original has uncommitted changes")
            return 1
    print("STAGE=preflight STATUS=pass")

    landed_shas: dict[str, str] = {}
    max_attempts = 3

    for attempt in range(1, max_attempts + 1):
        push_failed = False

        for repo_name in repos:
            if progress.get(repo_name) == "stamped":
                sha_line = [
                    line for line in progress_path.read_text().splitlines()
                    if line.startswith(f"{repo_name}=pushed:")
                ]
                if sha_line:
                    landed_shas[repo_name] = sha_line[0].split(":", 1)[1].strip()
                continue

            slot_repo = str(slot_dir / repo_name)
            original = str(_resolve_original(slot_dir / repo_name))

            push_to_orig = git(slot_repo, "push", "origin", branch, "--force-with-lease")
            if push_to_orig.returncode != 0:
                print(f"WARN=slot_push_failed repo={repo_name} attempt={attempt}")
                push_failed = True
                break

            git(original, "fetch", "origin", base_branch)
            rebase_r = git(original, "rebase", f"origin/{base_branch}")
            if rebase_r.returncode != 0:
                git(original, "rebase", "--abort")
                push_failed = True
                break

            merge_r = git(original, "merge", "--ff-only", branch)
            if merge_r.returncode != 0:
                push_failed = True
                break

            push_r = git(original, "push", "origin", base_branch)
            if push_r.returncode != 0:
                push_failed = True
                break

            sha_r = git(original, "rev-parse", "HEAD")
            sha = sha_r.stdout.strip() if sha_r.returncode == 0 else "unknown"
            landed_shas[repo_name] = sha
            write_progress(progress_path, repo_name, f"pushed:{sha}")

            tip_msg = git(slot_repo, "log", "-1", "--format=%s", branch)
            already_stamped = (tip_msg.returncode == 0
                               and tip_msg.stdout.strip().startswith("chore: branch closed"))
            if not already_stamped:
                git(slot_repo, "commit", "--allow-empty", "-m",
                    f"chore: branch closed — landed as {sha} on {base_branch}")
                git(slot_repo, "push", "origin", branch, "--force-with-lease")
            write_progress(progress_path, repo_name, "stamped")

        if push_failed:
            if attempt < max_attempts:
                print(f"PUSH_RETRY={attempt}")
                continue
            print("ERROR=PUSH_FAILED")
            print(f"ERROR_DETAIL=retry exhausted after {max_attempts} attempts")
            return 1
        break

    primary_sha = landed_shas.get(repos[0], "unknown") if repos else "unknown"
    for sub in slot_dir.iterdir():
        if not sub.is_dir() or not (sub / ".git").exists():
            continue
        if sub.name == "work" or sub.name.startswith("work-"):
            tip_msg = git(str(sub), "log", "-1", "--format=%s", branch)
            already_stamped = (tip_msg.returncode == 0
                               and tip_msg.stdout.strip().startswith("chore: branch closed"))
            if not already_stamped:
                git(str(sub), "commit", "--allow-empty", "-m",
                    f"chore: branch closed — landed as {primary_sha} on {base_branch}")
                git(str(sub), "push", "origin", branch, "--force-with-lease")

    shas_str = ",".join(f"{r}:{s}" for r, s in landed_shas.items())
    (slot_dir / ".landed").write_text(
        f"branch={branch}\n"
        f"repos={','.join(repos)}\n"
        f"landed_shas={shas_str}\n"
        f"timestamp={datetime.datetime.now(datetime.timezone.utc).isoformat()}\n"
    )

    if progress_path.exists():
        progress_path.unlink()

    print("LANDED=yes")
    print(f"LANDED_SHAS={shas_str}")
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

    slot_dir, slot_repos = _detect_slot(project)
    if slot_dir and slot_repos:
        return _land_slot(slot_dir, slot_repos, branch, base_branch, workspace)

    progress_path = (
        Path(workspace) / "design" / ".execute-progress"
        if workspace
        else Path(project) / ".execute-progress"
    )
    progress = read_progress(progress_path)

    repo_name = Path(project).name

    if progress.get(f"{repo_name}") == "stamped":
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
    write_progress(progress_path, f"{repo_name}", "merged")

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
    write_progress(progress_path, f"{repo_name}", "pushed")

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
    write_progress(progress_path, f"{repo_name}", "stamped")

    # Stamp workspace branch and push
    if workspace:
        ws_branch_exists = git(workspace, "branch", "--list", branch)
        if ws_branch_exists.returncode == 0 and ws_branch_exists.stdout.strip():
            tip_msg = git(workspace, "log", "-1", "--format=%s", branch)
            if not (tip_msg.returncode == 0 and tip_msg.stdout.strip().startswith("chore: branch closed")):
                git(workspace, "checkout", branch)
                git(workspace, "commit", "--allow-empty", "-m",
                    f"chore: branch closed — landed as {landed_sha} on {base_branch}")
                ws_push = git(workspace, "push", "origin", branch, "--force-with-lease")
                if ws_push.returncode != 0:
                    print(f"WORKSPACE_PUSH_WARN=push workspace branch failed")
                git(workspace, "checkout", base_branch)

    print(f"LANDED=yes")
    print(f"LANDED_SHA={landed_sha}")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: work_end_execute.py <promote|rebase|land> key=value ...",
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
    else:
        print("ERROR=UNKNOWN_COMMAND")
        print(f"ERROR_DETAIL=unknown command '{command}' — use promote, rebase, or land")
        return 1


if __name__ == "__main__":
    sys.exit(main())
