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
    stacked_on: str = ""        # the branch it was stacked on; "" when cut from the base branch
    reason: str = ""            # why it starts there
    cut_from: dict | None = None  # {repo name: what its branch was cut from}
    resumed: bool = False       # True when checking out existing branches rather than creating


def create_branches_typed(project: str, workspace: str, branch: str,
                          base: str | None = None,
                          slot_path: str = "") -> CreateResult:
    """Create branches in project and workspace (and slot siblings) atomically.

    Every repo starts the branch from the same place. The queue decides where:
    stacked on the branch of the item just before this one when that item is
    finished but not closed, otherwise from the base branch. Each repo records
    what its branch was cut from (project/branch_base.py), which is what the
    close ceremony and the squash review later read.
    """
    _project_dir = str(Path(__file__).resolve().parent.parent / "project")
    if _project_dir not in sys.path:
        sys.path.insert(0, _project_dir)
    import branch_base
    from git_util import collect_slot_repos

    where = branch_base.start_point(Path(workspace))
    cut_from: dict[str, str] = {}

    def _base_branch(repo: str, wanted: str | None) -> str:
        if wanted and branch_base.branch_exists(repo, wanted):
            return wanted
        for candidate in ("main", "master"):
            if branch_base.branch_exists(repo, candidate):
                return candidate
        return wanted or "main"

    def _cut(repo: str, wanted_base: str | None, is_workspace: bool = False) -> tuple[bool, str]:
        parent = where.carry if is_workspace else where.parent
        if not parent:
            _follow_canonical(repo)
        ok, detail = branch_base.cut(repo, branch, _base_branch(repo, wanted_base), parent)
        if ok:
            actual = detail.removeprefix("resumed:")
            cut_from[Path(repo).name] = actual
        return ok, detail

    ok, detail = _cut(project, base)
    if not ok:
        return CreateResult(branch, False, False, f"project_branch_failed:{detail}")
    project_resumed = detail.startswith("resumed:")

    ok, detail = _cut(workspace, None, is_workspace=True)
    if not ok:
        if not project_resumed:
            run_git(project, "checkout", "-")
            run_git(project, "branch", "-D", branch)
            branch_base.clear(project, branch)
        else:
            run_git(project, "checkout", "-")
        return CreateResult(branch, project_resumed, False, f"workspace_branch_failed:{detail}")
    workspace_resumed = detail.startswith("resumed:")

    if slot_path:
        for repo_path, label in collect_slot_repos(slot_path, project, workspace):
            if repo_path in (project, workspace):
                continue
            _cut(repo_path, None, is_workspace=(Path(repo_path) / ".workspace").exists())

    _slot_reentry_cleanup(Path(project).parent)
    return CreateResult(branch, True, True, stacked_on=where.parent, reason=where.reason,
                        cut_from=cut_from, resumed=project_resumed or workspace_resumed)


def _follow_canonical(repo: str) -> None:
    """Before cutting from the base branch in a slot clone, bring that branch up to
    the canonical repo's, so "from main" means canonical main as it is on disk."""
    try:
        cs = _canonical_sync()
        cs.follow(repo)
    except Exception:
        pass        # no canonical behind this repo: cut from what it has


_SLOT_ROOT_MARKERS = [".landed", ".phase-a-complete", ".execute-progress"]

_WORKSPACE_MARKERS = [
    ".plan", ".close-progress", ".close-report.json",
    ".close-log.jsonl", ".wrap-log.jsonl",
    ".land-ledger.jsonl", ".artifacts-promoted",
]


def _slot_reentry_cleanup(slot_dir: Path) -> None:
    """Orient, validate, and self-heal a slot that had previous work.

    Three phases:
    1. Orient — detect previous lifecycle state and print summary
    2. Validate — check for stuck/conflicting state
    3. Self-heal — clear all stale markers so new work starts clean
    """
    if not slot_dir.is_dir() or "/slots/" not in str(slot_dir):
        return

    # --- Phase 1: Orient ---
    prev_markers: list[str] = []
    for m in _SLOT_ROOT_MARKERS:
        if (slot_dir / m).exists():
            prev_markers.append(m)

    for sub in sorted(slot_dir.iterdir()):
        if not sub.is_dir() or sub.name.startswith("."):
            continue
        for m in _WORKSPACE_MARKERS:
            if (sub / m).exists():
                prev_markers.append(f"{sub.name}/{m}")
            if (sub / "design" / m).exists():
                prev_markers.append(f"{sub.name}/design/{m}")

    if not prev_markers:
        return

    prev_state = "unknown"
    if any(m == ".landed" for m in prev_markers):
        prev_state = "landed"
    elif any(m == ".phase-a-complete" for m in prev_markers):
        prev_state = "partial-close"
    elif any(".close-progress" in m for m in prev_markers):
        prev_state = "interrupted-close"
    elif any(".plan" in m for m in prev_markers):
        prev_state = "stale-scaffold"

    print(f"SLOT_REENTRY=yes PREV_STATE={prev_state} MARKERS={len(prev_markers)}")

    # --- Phase 2: Validate ---
    for sub in sorted(slot_dir.iterdir()):
        if not sub.is_dir() or sub.name.startswith("."):
            continue
        plan = sub / ".plan"
        if plan.exists():
            try:
                for line in plan.read_text().splitlines():
                    stripped = line.strip()
                    if stripped.startswith("state:"):
                        state = stripped.split(":", 1)[1].strip()
                        if state.startswith("closing:"):
                            print(f"WARN=stuck_close_state plan={sub.name}/.plan state={state}")
            except OSError:
                pass

    for sub in sorted(slot_dir.iterdir()):
        if not sub.is_dir() or not (sub / ".git").is_dir():
            continue
        ok, branch = run_git(str(sub), "branch", "--show-current")
        if ok and branch.strip() == "main":
            print(f"WARN=repo_on_main repo={sub.name}")

    # --- Phase 3: Self-heal ---
    for m in _SLOT_ROOT_MARKERS:
        marker = slot_dir / m
        if marker.exists():
            marker.unlink()
            print(f"CLEARED_STALE={m}")

    for sub in sorted(slot_dir.iterdir()):
        if not sub.is_dir() or sub.name.startswith("."):
            continue
        for m in _WORKSPACE_MARKERS:
            for loc in [sub / m, sub / "design" / m]:
                if loc.exists():
                    loc.unlink()
                    print(f"CLEARED_STALE={sub.name}/{loc.relative_to(sub)}")


# ---------------------------------------------------------------------------
# CLI entry points (print KEY=value output)
# ---------------------------------------------------------------------------

def create_branches(project: str, workspace: str, branch: str, base: str | None,
                    slot_path: str = "") -> int:
    """Create branches in project, workspace, and slot siblings atomically."""
    result = create_branches_typed(project, workspace, branch, base, slot_path)
    if result.error:
        print(f"ERROR={result.error}")
        return 1
    print(f"{'RESUMED' if result.resumed else 'CREATED'}=yes")
    print(f"STACKED={'yes' if result.stacked_on else 'no'}")
    print(f"STACKED_ON={result.stacked_on or 'none'}")
    print(f"START_REASON={result.reason}")
    for repo_name, origin in (result.cut_from or {}).items():
        print(f"CUT_FROM={repo_name}:{origin}")
    return 0


def commit_scaffold(workspace: str, branch: str) -> int:
    """Commit scaffold files; the canonical repo keeps a backup of the branch."""
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

    candidates = [f for f in [".plan", "JOURNAL.md", ".work-progress"]
                  if (Path(workspace) / f).exists()]
    files_to_add = [f for f in candidates
                    if not run_git(workspace, "check-ignore", "-q", f)[0]]
    if files_to_add:
        ok, _ = run_git(workspace, "add", *files_to_add)
        if not ok:
            print("ERROR=add_failed")
            return 1

    status_ok, status_out = run_git(workspace, "diff", "--cached", "--quiet")
    if status_ok:
        print("COMMITTED=no_changes")
        _back_up_branch(workspace, branch)
        return 0

    commit_msg = f"init({branch}): scaffold workspace branch"
    ok, _ = run_git(workspace, "commit", "-m", commit_msg)
    if not ok:
        print("ERROR=commit_failed")
        return 1

    print("COMMITTED=yes")
    _back_up_branch(workspace, branch)
    return 0


def _back_up_branch(repo: str, branch: str) -> None:
    """The canonical repo keeps a copy of the new branch. Nothing is pushed. Never fatal."""
    cs = _canonical_sync()
    try:
        print(f"BACKED_UP={cs.backup(repo, branch)}")
    except cs.SyncError as error:
        print("BACKED_UP=no")
        print(f"WARN={error.detail}")


def _canonical_sync():
    project_dir = str(Path(__file__).resolve().parent.parent / "project")
    if project_dir not in sys.path:
        sys.path.insert(0, project_dir)
    import canonical_sync
    return canonical_sync


def _sync_repo(repo: str, warnings: list[str], label: str) -> str:
    """Bring one repo's starting point up to date, by fast-forward only.

    The canonical repo's base branch fast-forwards from its remote when it can.
    A slot clone's base branch then fast-forwards from canonical's. Nothing is
    rebased, merged or pushed: canonical being ahead of its remote is landed
    work awaiting publish, and a remote that has moved past unpublished commits
    is settled by `canonical_sync.py publish`, not here.

    Returns the strategy that applied: current, fast-forward, ahead, diverged,
    offline or skipped.
    """
    cs = _canonical_sync()
    name = Path(repo).name
    try:
        canon = cs.locate(repo)
    except cs.SyncError as error:
        warnings.append(f"no_canonical_{label}")
        print(f"SYNC_DETAIL={error.detail}")
        return "skipped"

    strategy = "current"
    try:
        with cs.landing_lock(canon):
            before = cs._sha(canon.repo, f"refs/heads/{canon.base}")
            after = cs.sync_base(canon)
        if after != before:
            strategy = "fast-forward"
    except cs.SyncError as error:
        if error.code == "fetch_failed":
            warnings.append(f"fetch_{label}_failed")
            strategy = "offline"
        elif error.code == "diverged":
            # Not a failure: work starts from canonical, and publishing settles it.
            strategy = "diverged"
            print(f"NOTE=diverged repo={name} detail=the remote moved while canonical holds "
                  f"unpublished commits; publishing will put them on top")
        else:
            warnings.append(f"sync_{label}_{error.code}")
            print(f"SYNC_DETAIL={error.detail}")
            strategy = "skipped"

    waiting = cs.unpublished(canon)
    if waiting:
        print(f"UNPUBLISHED={waiting} repo={name}")
        if strategy == "current":
            strategy = "ahead"

    state = cs.follow(repo, canon)
    if state == "blocked":
        warnings.append(f"follow_{label}_blocked")
        print(f"SYNC_DETAIL={name} is behind canonical and could not be moved: "
              f"uncommitted changes in its checkout")
    if state in ("ahead", "diverged"):
        print(f"STRAY={name} state={state} detail=the clone's own {canon.base} holds commits "
              f"canonical lacks; the next landing carries them")

    print(f"STRATEGY={strategy} repo={name}")
    return strategy


def sync_main(project: str, workspace: str, base: str) -> int:
    """Bring the project's and workspace's starting point up to date before branching.

    Fast-forward only, never fatal: an unreachable remote is a warning, and work
    starts from what the canonical repo has on disk.
    """
    warnings: list[str] = []
    cs = _canonical_sync()

    model = "none"
    try:
        canon = cs.locate(project)
        if canon.blessed == "upstream":
            model = "upstream"
        elif canon.mirror:
            model = "fork"
        elif canon.blessed:
            model = "single"
    except cs.SyncError:
        pass

    _sync_repo(project, warnings, "project")
    _sync_repo(workspace, warnings, "workspace")

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
        slot = kv.get("slot_path", "")
        return create_branches(project, workspace, branch, base, slot_path=slot)

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
