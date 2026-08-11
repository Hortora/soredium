#!/usr/bin/env python3
"""
Land changes on main via an ephemeral branch — avoids committing directly.

Usage:
    python3 quick_fix.py <project> message="commit message"

Detects state automatically:
  - Dirty tree on main        -> create branch, commit, rebase, land
  - Unpushed commits on main  -> rescue: move to branch, rebase, land
  - Dirty + unpushed          -> rescue with uncommitted changes
  - Not on main / nothing     -> error

Output (KEY=value lines):
    MODE=normal|rescue
    BRANCH=<ephemeral branch name>
    COMMITTED=yes
    REBASED=yes|skipped
    LANDED=yes
    PUSHED=yes|failed|skipped
    MIRRORED=yes|failed|skipped|na
    CLEANED=yes

Error output:
    ERROR=<code>
    ERROR_DETAIL=<message>

Exit codes:
    0  success
    1  error
"""

import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "work-end"))
from common import detect_topology, parse_args


def git(repo: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True, text=True, timeout=30,
    )


def _current_branch(project: str) -> str:
    r = git(project, "branch", "--show-current")
    return r.stdout.strip() if r.returncode == 0 else ""


def _is_dirty(project: str) -> bool:
    r = git(project, "status", "--porcelain")
    return bool(r.stdout.strip()) if r.returncode == 0 else False


def _commits_ahead(project: str, remote: str, base: str) -> int:
    r = git(project, "rev-list", f"{remote}/{base}..HEAD", "--count")
    if r.returncode != 0:
        return 0
    try:
        return int(r.stdout.strip())
    except ValueError:
        return 0


def _make_branch_name() -> str:
    return f"quick-{datetime.now().strftime('%Y%m%d-%H%M%S')}"


# ---------------------------------------------------------------------------
# Library API — typed interface for command layer
# ---------------------------------------------------------------------------

@dataclass
class QuickFixResult:
    success: bool
    branch: str | None = None
    message: str | None = None
    mode: str | None = None
    landed_sha: str | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def run(project: str, message: str, base_branch: str = "main") -> int:
    branch = _current_branch(project)
    if branch != base_branch:
        print("ERROR=NOT_ON_MAIN")
        print(f"ERROR_DETAIL=on '{branch}', not '{base_branch}' — quick-fix only works from {base_branch}")
        return 1

    dirty = _is_dirty(project)

    fork_remote, blessed_remote = detect_topology(project)
    push_remote = blessed_remote if blessed_remote else fork_remote
    mirror_remote = fork_remote if blessed_remote else ""

    if not push_remote:
        print("ERROR=NO_REMOTE")
        print("ERROR_DETAIL=no remote configured")
        return 1

    git(project, "fetch", push_remote, base_branch)

    ahead = _commits_ahead(project, push_remote, base_branch)

    if not dirty and ahead == 0:
        print("ERROR=NOTHING_TO_DO")
        print("ERROR_DETAIL=no changes and no unpushed commits on main")
        return 1

    ephemeral = _make_branch_name()
    print(f"BRANCH={ephemeral}")

    if ahead > 0:
        print("MODE=rescue")
        return _rescue(project, ephemeral, message, dirty, ahead,
                        base_branch, push_remote, mirror_remote)
    else:
        print("MODE=normal")
        return _normal(project, ephemeral, message,
                        base_branch, push_remote, mirror_remote)


def _normal(project: str, ephemeral: str, message: str,
            base_branch: str, push_remote: str, mirror_remote: str) -> int:
    r = git(project, "checkout", "-b", ephemeral)
    if r.returncode != 0:
        print("ERROR=BRANCH_FAILED")
        print(f"ERROR_DETAIL={r.stderr.strip()}")
        return 1

    git(project, "add", "-A")
    r = git(project, "commit", "-m", message)
    if r.returncode != 0:
        git(project, "checkout", base_branch)
        git(project, "branch", "-D", ephemeral)
        print("ERROR=COMMIT_FAILED")
        print(f"ERROR_DETAIL={r.stderr.strip()}")
        return 1
    print("COMMITTED=yes")

    r = git(project, "rebase", f"{push_remote}/{base_branch}")
    if r.returncode != 0:
        git(project, "rebase", "--abort")
        print("REBASED=conflict")
        print(f"REBASE_DETAIL={r.stderr.strip()}")
        git(project, "checkout", base_branch)
        git(project, "branch", "-D", ephemeral)
        print("ERROR=REBASE_CONFLICT")
        print("ERROR_DETAIL=rebase conflict — resolve manually or use a feature branch")
        return 1
    print("REBASED=yes")

    return _land_and_push(project, ephemeral, base_branch, push_remote, mirror_remote)


def _rescue(project: str, ephemeral: str, message: str,
            dirty: bool, ahead: int,
            base_branch: str, push_remote: str, mirror_remote: str) -> int:
    if dirty:
        git(project, "stash", "push", "-u", "-m", "quick-fix rescue stash")

    r = git(project, "checkout", "-b", ephemeral)
    if r.returncode != 0:
        if dirty:
            git(project, "stash", "pop")
        print("ERROR=BRANCH_FAILED")
        print(f"ERROR_DETAIL={r.stderr.strip()}")
        return 1

    git(project, "checkout", base_branch)
    git(project, "reset", "--hard", f"{push_remote}/{base_branch}")

    git(project, "checkout", ephemeral)

    if dirty:
        git(project, "stash", "pop")
        git(project, "add", "-A")
        r = git(project, "commit", "-m", message)
        if r.returncode != 0:
            print("ERROR=COMMIT_FAILED")
            print(f"ERROR_DETAIL={r.stderr.strip()}")
            return 1
        print("COMMITTED=yes")
    else:
        print("COMMITTED=skipped")

    r = git(project, "rebase", f"{push_remote}/{base_branch}")
    if r.returncode != 0:
        git(project, "rebase", "--abort")
        print("REBASED=conflict")
        print("ERROR=REBASE_CONFLICT")
        print("ERROR_DETAIL=rebase conflict during rescue — resolve manually")
        return 1
    print("REBASED=yes")

    return _land_and_push(project, ephemeral, base_branch, push_remote, mirror_remote)


def _land_and_push(project: str, ephemeral: str,
                   base_branch: str, push_remote: str, mirror_remote: str) -> int:
    r = git(project, "checkout", base_branch)
    if r.returncode != 0:
        print("ERROR=CHECKOUT_FAILED")
        print(f"ERROR_DETAIL={r.stderr.strip()}")
        return 1

    r = git(project, "merge", "--ff-only", f"{push_remote}/{base_branch}")
    if r.returncode != 0:
        pass

    r = git(project, "merge", "--ff-only", ephemeral)
    if r.returncode != 0:
        print("ERROR=MERGE_FAILED")
        print(f"ERROR_DETAIL=cannot fast-forward {base_branch} to {ephemeral}: {r.stderr.strip()}")
        return 1
    print("LANDED=yes")

    r = git(project, "push", push_remote, base_branch)
    if r.returncode != 0:
        print("PUSHED=failed")
        print(f"PUSH_DETAIL={r.stderr.strip()}")
    else:
        print("PUSHED=yes")

    if mirror_remote:
        r = git(project, "push", mirror_remote, base_branch, "--force-with-lease")
        if r.returncode != 0:
            print("MIRRORED=failed")
        else:
            print("MIRRORED=yes")
    else:
        print("MIRRORED=na")

    git(project, "branch", "-D", ephemeral)
    print("CLEANED=yes")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 1

    project = sys.argv[1]
    opts = parse_args(sys.argv[2:])
    message = opts.get("message", "")
    base_branch = opts.get("base_branch", "main")

    if not message:
        print("ERROR=MISSING_MESSAGE")
        print("ERROR_DETAIL=message= argument required")
        return 1

    r = git(project, "rev-parse", "--git-dir")
    if r.returncode != 0:
        print("ERROR=NOT_A_REPO")
        print(f"ERROR_DETAIL={project} is not a git repository")
        return 1

    return run(project, message, base_branch)


if __name__ == "__main__":
    sys.exit(main())
