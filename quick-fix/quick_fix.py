#!/usr/bin/env python3
"""
Land a small change on the base branch, on disk.

Usage:
    python3 quick_fix.py <project> message="commit message"

The uncommitted changes in <project>, which must be on its base branch, become
one commit on that branch. In a slot clone the commit is then landed in the
canonical repo through project/canonical_sync.py. Nothing is pushed: publishing
is `canonical_sync.py publish <repo>`, offered here when canonical holds commits
its remote lacks.

Commits already on the base branch that the remote lacks are landed work
awaiting publish. They are left exactly as they are.

Never stashes, resets, switches a checkout or uses the network.

Output (KEY=value lines):
    COMMITTED=yes|skipped
    LANDED=yes
    SHA=<canonical base branch tip>
    UNPUBLISHED=<commits canonical's base branch holds that its remote lacks>
    OFFER=publish            (only when UNPUBLISHED is above zero)

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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "work-end"))
sys.path.insert(0, str(Path(__file__).parent.parent / "project"))
from common import parse_args
import canonical_sync
from canonical_sync import SyncError

_IN_PROGRESS = (
    ("rebase-merge", "rebase"), ("rebase-apply", "rebase"), ("MERGE_HEAD", "merge"),
    ("CHERRY_PICK_HEAD", "cherry-pick"), ("REVERT_HEAD", "revert"),
)


def git(repo: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True, text=True, timeout=60,
    )


def _current_branch(project: str) -> str:
    r = git(project, "branch", "--show-current")
    return r.stdout.strip() if r.returncode == 0 else ""


def _is_dirty(project: str) -> bool:
    r = git(project, "status", "--porcelain")
    return bool(r.stdout.strip()) if r.returncode == 0 else False


def _in_progress(project: str) -> str:
    for marker, operation in _IN_PROGRESS:
        path = git(project, "rev-parse", "--git-path", marker).stdout.strip()
        if path and (Path(path) if Path(path).is_absolute() else Path(project) / path).exists():
            return operation
    return ""


def _fail(code: str, detail: str) -> int:
    print(f"ERROR={code}")
    print(f"ERROR_DETAIL={detail}")
    return 1


def _report_unpublished(canon: canonical_sync.Canonical) -> None:
    count = canonical_sync.unpublished(canon)
    print(f"UNPUBLISHED={count}")
    if count:
        print("OFFER=publish")


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
        return _fail("NOT_ON_MAIN",
                     f"on '{branch}', not '{base_branch}' — quick-fix only works from {base_branch}")

    operation = _in_progress(project)
    if operation:
        return _fail("BUSY", f"a {operation} is in progress in {project}; finish it first")

    try:
        canon = canonical_sync.locate(project)
        is_clone = canonical_sync.is_clone(project, canon)
        dirty = _is_dirty(project)
        waiting = canonical_sync.ahead_of_canonical(project, base_branch) if is_clone else 0

        if not dirty and not waiting:
            print("ERROR=NOTHING_TO_DO")
            print(f"ERROR_DETAIL=no uncommitted changes on {base_branch}")
            _report_unpublished(canon)
            return 1

        if dirty:
            git(project, "add", "-A")
            r = git(project, "commit", "-m", message)
            if r.returncode != 0:
                git(project, "reset", "-q")      # unstage only; the changes stay in the tree
                return _fail("COMMIT_FAILED",
                             " ".join((r.stderr or r.stdout).strip().split()))
            print("COMMITTED=yes")
        else:
            print("COMMITTED=skipped")

        if is_clone:
            canonical_sync.land(project, base_branch)
        print("LANDED=yes")
        print(f"SHA={git(str(canon.repo), 'rev-parse', base_branch).stdout.strip()}")
        _report_unpublished(canon)
        return 0
    except SyncError as error:
        return _fail(error.code.upper(), error.detail)


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
