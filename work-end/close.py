"""Atomic close ceremony for work-end.

Single entry point: close(workspace) → CloseResult.
Reads .queue and git state; lands branches, stamps, advances queue.
Each step is idempotent — re-running after failure picks up from
committed state.

Landing goes through project/canonical_sync.py: every branch ends on the
canonical repo's base branch by fast-forward, on disk. Nothing is pushed here;
publishing is `canonical_sync.py publish <repo>`, which the ceremony offers when
canonical holds commits its remote lacks. Landing uses no network, and no
checkout is switched while it runs.
"""
from __future__ import annotations

import re

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
from queue_io import queue_dir  # noqa: E402
import squash_marker
import canonical_sync
from canonical_sync import SyncError
import branch_base


LIFECYCLE_FILES = [
    "JOURNAL.md", ".close-state", ".execute-progress",
    ".land-ledger.jsonl", ".artifacts-promoted", ".squash-plan",
    ".close-progress", ".close-report.json",
    ".close-log.jsonl", ".wrap-log.jsonl", ".work-progress",
]


import worktrace  # noqa: E402

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
    squash_review: list[str] = field(default_factory=list)
    # Documents this work added to a workspace that its project does not hold yet,
    # and the command that promotes each workspace's share.
    unpromoted: list[str] = field(default_factory=list)
    promote_commands: list[str] = field(default_factory=list)
    workspace_landed: dict = field(default_factory=dict)
    slot_ready: str = ""
    # Queue items this ceremony closed, in the order they landed, and each one's branch.
    closed_items: list[str] = field(default_factory=list)
    closed_branches: dict = field(default_factory=dict)
    # Slot repos whose own commits, outside the queue's branches, were carried to
    # canonical: {"repo:branch": commits}. And those that could not be: {"repo:branch": why}.
    carried: dict = field(default_factory=dict)
    not_landed: dict = field(default_factory=dict)
    # Canonical repos holding commits their remote lacks: {canonical path: count}.
    unpublished: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    # Documents on a workspace's base branch that its project's base branch lacks,
    # whoever wrote them and whenever: {"workspace -> project": count}, and the
    # command that promotes each. Reported, never a reason to refuse (#566).
    backlog: dict = field(default_factory=dict)
    backlog_commands: list[str] = field(default_factory=list)


@dataclass
class BatchEntry:
    """One queue item's share of a close: its issue and the branches that carry it."""
    issue: str
    branches: list[str]
    done: bool          # marked done earlier in the session, as opposed to the active item
    targets: list = field(default_factory=list)


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
        from slot_core import get_slot_repos
        for candidate in [workspace, workspace.parent]:
            if (candidate / ".slot").exists():
                repo_names = get_slot_repos(candidate)
                return [candidate / name for name in repo_names]
        return []
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


def batch_entries(workspace: Path, queue: Queue) -> list[BatchEntry]:
    """Everything one ceremony closes: each done item in queue order, then the active item."""
    entries = [BatchEntry(issue=item.ref, branches=[item.done_branch], done=True)
               for item in queue.done_items()]
    done_branches = {item.done_branch for item in queue.done_items()}
    active = queue.active_item()
    entries.append(BatchEntry(
        issue=active.ref if active else "",
        branches=[b for b in discover_active_branches(workspace, queue)
                  if b not in done_branches],
        done=False))
    return entries


def resolve(workspace: Path, branches: Optional[list[str]] = None) -> list[CloseTarget]:
    """Determine what to close. Returns a CloseTarget per repo×branch with commits."""
    queue = read_queue(workspace)
    if queue is None:
        return []

    if branches is None:
        branches = discover_active_branches(workspace, queue)
    topology = discover_repo_topology(workspace)
    targets = []

    for branch in branches:
        for repo, base, transport, canonical, push, mirror in topology:
            if not _branch_exists(repo, branch):
                continue
            # A stamp is an empty commit ahead of base: it is not work to land.
            if _is_stamp_commit(repo, branch):
                continue
            if _has_commits_ahead(repo, branch, base):
                is_ws = (repo.resolve() == workspace.resolve())
                targets.append(CloseTarget(
                    repo=repo, branch=branch, base_branch=base,
                    transport=transport, canonical=canonical,
                    push_target=push, mirror_target=mirror,
                    is_workspace=is_ws,
                ))

    return targets


def stamped_branches(workspace: Path) -> list[str]:
    """Return 'repo:branch' for every candidate branch that is already stamped closed."""
    queue = read_queue(workspace)
    if queue is None:
        return []
    found = []
    for branch in discover_active_branches(workspace, queue):
        for repo, *_ in discover_repo_topology(workspace):
            if _branch_exists(repo, branch) and _is_stamp_commit(repo, branch):
                found.append(f"{repo.name}:{branch}")
    return found


_IN_PROGRESS_MARKERS = (
    ("rebase-merge", "rebase"), ("rebase-apply", "rebase"), ("MERGE_HEAD", "merge"),
    ("CHERRY_PICK_HEAD", "cherry-pick"), ("REVERT_HEAD", "revert"), ("BISECT_LOG", "bisect"),
)


def _busy_reason(repo: Path) -> Optional[str]:
    """Return why the repo cannot take part in a close, or None when it is idle."""
    for marker, operation in _IN_PROGRESS_MARKERS:
        result = _git(repo, "rev-parse", "--git-path", marker)
        if result.returncode != 0:
            continue
        marker_path = Path(result.stdout.strip())
        if not marker_path.is_absolute():
            marker_path = repo / marker_path
        if marker_path.exists():
            return (f"a {operation} is in progress — finish or abort it first; commits made "
                    f"during it are on a detached HEAD and are lost if it is aborted")
    if _git(repo, "symbolic-ref", "-q", "HEAD").returncode != 0:
        return "HEAD is detached — check out a branch first"
    return None


def check_repos_idle(workspace: Path) -> list[str]:
    """Return an error for each repo that is mid-operation or on a detached HEAD."""
    repos = [repo for repo, *_ in discover_repo_topology(workspace)]
    if all(r.resolve() != workspace.resolve() for r in repos) and (workspace / ".git").exists():
        repos.append(workspace)
    errors = []
    for repo in repos:
        reason = _busy_reason(repo)
        if reason:
            errors.append(f"{repo.name}: {reason}")
    return errors


def check_branch_alignment(workspace: Path) -> list[str]:
    """Return an error for each project repo sitting on a feature branch the queue does not name."""
    queue = read_queue(workspace)
    if queue is None:
        return []
    branches = discover_active_branches(workspace, queue)
    branches += [i.done_branch for i in queue.done_items() if i.done_branch not in branches]
    topology = discover_repo_topology(workspace)
    named = ", ".join(branches) if branches else "no branch"
    errors = []
    for repo, base, *_ in topology:
        # The workspace repo may legitimately sit on its base branch or lag the project.
        if len(topology) > 1 and repo.resolve() == workspace.resolve():
            continue
        current = _current_branch(repo)
        if current and current != base and current not in branches:
            errors.append(
                f"{repo.name} is on branch '{current}' but the queue names {named} — "
                f"refusing to close. Set the queue branch to '{current}' or check out "
                f"the queued branch, then retry.")
    return errors


# --- preflight ---

_LIFECYCLE_IGNORE = frozenset({
    ".queue", ".plan", ".close-state", ".work-progress", ".close-progress",
    ".execute-progress", ".land-ledger.jsonl", ".close-log.jsonl",
    ".wrap-log.jsonl", ".artifacts-promoted", "JOURNAL.md",
    ".close-report.json", ".squash-plan",
})


def _is_dirty(repo: Path) -> bool:
    result = _git(repo, "status", "--porcelain")
    if result.returncode != 0:
        return False
    for line in result.stdout.strip().splitlines():
        filename = line[3:].strip().strip('"')
        if filename not in _LIFECYCLE_IGNORE:
            return True
    return False


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


def preflight(targets: list[CloseTarget]) -> dict:
    """Verify preconditions before mutating. Returns {errors, rescued}."""
    errors: list[str] = []
    rescued: dict[str, str] = {}

    for t in targets:
        if _is_dirty(t.repo):
            errors.append(f"{t.repo.name}: uncommitted changes")
        if not _branch_exists(t.repo, t.base_branch):
            errors.append(f"{t.repo.name}: no {t.base_branch} branch")
        try:
            canonical_sync.locate(t.repo)
        except SyncError as error:
            # Refused before anything is touched: the work would have nowhere to land.
            errors.append(error.detail)
        if not _remote_reachable(t.repo, t.push_target):
            pass

        local_only = _commits_ahead_of_remote(t.repo, t.base_branch, t.push_target)
        if local_only > 0:
            rescued[t.repo.name] = f"{local_only} commit(s) ahead of {t.push_target}/{t.base_branch}"

    return {"errors": errors, "rescued": rescued}


# --- land ---

def _checkout(repo: Path, branch: str) -> None:
    _git(repo, "checkout", branch)



def _is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    result = _git(repo, "merge-base", "--is-ancestor", ancestor, descendant)
    return result.returncode == 0


def _rev_parse(repo: Path, ref: str) -> str:
    result = _git(repo, "rev-parse", ref)
    return result.stdout.strip() if result.returncode == 0 else ""


def strip_lifecycle_files(repo: Path, branch: str, files: list[str]) -> None:
    """Remove tracked lifecycle files from the branch, as a commit on the branch.

    Done before landing, so no commit is ever added to the base branch afterwards.
    """
    tracked = [f for f in files
               if _git(repo, "ls-tree", "--name-only", branch, "--", f).stdout.strip()]
    if not tracked:
        return
    with canonical_sync.checked_out(repo, branch) as tree:
        _git(tree, "rm", "-q", "-f", "--", *tracked)
        result = _git(tree, "commit", "-m", "chore: strip lifecycle files before merge",
                      "-m", _issue_trailer(""))
        if result.returncode != 0:
            raise RuntimeError(
                f"{repo.name}: could not strip lifecycle files from {branch}: "
                f"{result.stderr.strip()}")


def verify_content_landed(target: CloseTarget, landed_sha: str) -> None:
    """The branch tip must be on canonical's base branch. Checked, never assumed."""
    canon = canonical_sync.locate(target.repo)
    tip = _rev_parse(target.repo, target.branch)
    base_tip = _rev_parse(canon.repo, canon.base)
    if not tip or base_tip != landed_sha or not _is_ancestor(canon.repo, tip, canon.base):
        raise RuntimeError(
            f"Content from {target.branch} not landed on {canon.repo.name}:{canon.base} "
            f"(branch {tip[:12]}, base {base_tip[:12]})")


def land_targets(targets: list[CloseTarget]) -> dict:
    """Land every target in canonical, on disk. Returns {target: LandResult}.

    Project and workspace repos take the same linear path: rebase, then
    fast-forward the canonical base branch. No network is used and nothing is pushed.
    Only a branch's own commits are replayed: what it was stacked on has landed
    with its own item.
    """
    own_bases = {target: branch_base.base_of(target.repo, target.branch) for target in targets}
    for target in targets:
        strip_lifecycle_files(target.repo, target.branch, LIFECYCLE_FILES)
    results = canonical_sync.land_all(
        [(target.repo, target.branch, own_bases[target]) for target in targets])
    landed = dict(zip(targets, results))
    for target, result in landed.items():
        verify_content_landed(target, result.sha)
    return landed


def land(target: CloseTarget, issue: str = "") -> str:
    """Land one target; returns the canonical base SHA it landed as."""
    return land_targets([target])[target].sha


def slot_strays(slot_dir: Path, covered: set) -> list[tuple[Path, str, int]]:
    """Commits in a slot that no queue branch carries and canonical lacks.

    Workspace clones are worked on directly, on their base branch or whatever
    they have checked out, and an earlier ceremony may have left work on a
    clone's own base branch. Both are (repo, branch, commits) here, so that
    nothing in the slot is left behind when its issue closes.
    """
    from slot_core import get_all_slot_repos, is_workspace_clone
    strays = []
    for name in get_all_slot_repos(slot_dir):
        repo = slot_dir / name
        branches = [_get_base_branch(repo)]
        current = _current_branch(repo)
        if is_workspace_clone(repo) and current and current not in branches:
            branches.append(current)
        for branch in branches:
            if (repo, branch) in covered or _is_stamp_commit(repo, branch):
                continue
            try:
                count = canonical_sync.ahead_of_canonical(repo, branch)
            except SyncError:
                continue      # no canonical behind this clone: reported by preflight for targets
            if count:
                strays.append((repo, branch, count))
    return strays


def diverged_bases(slot_dir: Optional[Path]) -> set:
    """Slot repos whose own base branch has diverged from canonical, as it stands now.

    Taken before the ceremony lands anything: afterwards every clone base that
    was merely ahead looks diverged too, because canonical has just moved.
    """
    if slot_dir is None:
        return set()
    from slot_core import get_all_slot_repos
    found = set()
    for name in get_all_slot_repos(slot_dir):
        repo = slot_dir / name
        try:
            if canonical_sync.follow(repo) == "diverged":
                found.add(repo.resolve())
        except SyncError:
            continue
    return found


def carry_strays(slot_dir: Path, covered: set, diverged: Optional[set] = None) -> tuple[dict, dict]:
    """Land every stray in canonical. Returns (carried, not_landed), keyed "repo:branch"."""
    carried: dict[str, int] = {}
    not_landed: dict[str, str] = {}
    for repo, branch, count in slot_strays(slot_dir, covered):
        key = f"{repo.name}:{branch}"
        try:
            # A clone's own base branch is carried only when it simply holds extra
            # commits. One that has diverged from canonical (commits on both sides:
            # an old clone, or history rewritten since it was made) is not replayed
            # onto canonical; that would re-apply its whole divergent history.
            if branch == _get_base_branch(repo) and repo.resolve() in (diverged or set()):
                not_landed[key] = (f"{branch} has diverged from canonical ({count} commits "
                                   f"canonical lacks, and canonical has commits it lacks); "
                                   f"not carried. Compare the two by hand")
                continue
            canonical_sync.land(repo, branch)
            carried[key] = count
        except SyncError as error:
            not_landed[key] = error.detail
    return carried, not_landed


def settle_permanent_clone(slot_dir: Path, keep_branches: Optional[set] = None) -> list[str]:
    """After a ceremony in a permanent clone: every clone returns to its base
    branch and follows canonical, ready for the next item. Returns warnings.

    A clone on one of `keep_branches` stays there: that is an active item the
    ceremony deliberately did not land, and its work continues on that branch.

    A clone with uncommitted changes, or whose branch still holds commits
    canonical lacks, is left where it is: moving it would hide work.
    """
    from slot_core import get_all_slot_repos
    left: list[str] = []
    for name in get_all_slot_repos(slot_dir):
        repo = slot_dir / name
        base = _get_base_branch(repo)
        current = _current_branch(repo)
        if current and current != base and current in (keep_branches or set()):
            try:
                canonical_sync.follow(repo)      # the base ref still catches up
            except SyncError:
                pass
            continue
        if current and current != base:
            if _git(repo, "status", "--porcelain").stdout.strip():
                left.append(f"{name}: left on {current} with uncommitted changes")
                continue
            try:
                ahead = canonical_sync.ahead_of_canonical(repo, current)
            except SyncError:
                ahead = 0
            if ahead and not _is_stamp_commit(repo, current):
                left.append(f"{name}: left on {current}, {ahead} commit(s) not in canonical")
                continue
            if _git(repo, "checkout", "-q", base).returncode != 0:
                left.append(f"{name}: could not return to {base}")
                continue
        try:
            state = canonical_sync.follow(repo)
        except SyncError as error:
            left.append(f"{name}: {error.detail}")
            continue
        if state == "diverged":
            left.append(f"{name}: {base} has diverged from canonical")
        elif state == "blocked":
            left.append(f"{name}: {base} is behind canonical and could not be moved")
    return left


def promotion_pairs(workspace: Path) -> list[tuple[Path, Path]]:
    """(workspace repo, project repo) pairs this ceremony covers.

    Outside a slot: the workspace and the project its proj/ symlink names. In a
    slot: every workspace clone, with the project named in its .workspace marker.
    """
    pairs: list[tuple[Path, Path]] = []
    slot_dir = _slot_dir_of(workspace)
    if slot_dir is None:
        project = _resolve_project(workspace)
        if project and project.is_dir() and project.resolve() != workspace.resolve():
            pairs.append((workspace, project))
        return pairs
    from slot_core import get_all_slot_repos
    for name in get_all_slot_repos(slot_dir):
        clone = slot_dir / name
        marker = clone / ".workspace"
        if not marker.exists():
            continue
        for line in marker.read_text().splitlines():
            if line.startswith("project:"):
                project = Path(line.split(":", 1)[1].strip())
                if project.is_dir():
                    pairs.append((clone, project))
                break
    return pairs


def unpromoted_artifacts(workspace: Path, covers: str = "") -> tuple[list[str], list[str]]:
    """Documents this work added to a workspace that are not in the project yet.

    Returns (findings, commands). Checked before anything lands: a branch must not
    be reported closed while what it wrote is still only in the workspace.
    """
    import artifact_sweep
    findings: list[str] = []
    commands: list[str] = []
    sweep = Path(__file__).resolve().parent / "artifact_sweep.py"
    for ws_repo, project in promotion_pairs(workspace):
        gaps = artifact_sweep.branch_gaps(ws_repo, project)
        if not gaps:
            continue
        findings += [f"{ws_repo.name}/{gap['source_rel']} -> {project.name}/{gap['dest_rel']}"
                     for gap in gaps]
        commands.append(f"python3 {sweep} {ws_repo} {project} scope=branch"
                        + (f" covers={covers}" if covers else ""))
    return findings, commands


# Where the sweep (artifact_promote.py sweep-gaps) promotes from and to.
_PROMOTED_DIRS = (("blog", "docs/blog"), ("specs", "docs/specs"))
_NOT_DOCUMENTS = {"INDEX.md", "index.html", ".gitkeep", "decisions.md", "pipeline.state"}


def _documents_on(repo: Path, branch: str, directory: str) -> set[str]:
    """Names of the markdown files directly in `directory` on `branch`."""
    listed = _git(repo, "ls-tree", "--name-only", branch, f"{directory}/")
    if listed.returncode != 0:
        return set()
    names = {Path(line).name for line in listed.stdout.splitlines() if line.strip()}
    return {n for n in names if n.endswith(".md") and n not in _NOT_DOCUMENTS}


def promotion_backlog(workspace: Path, covers: str = "") -> tuple[dict, list[str]]:
    """Documents committed on a workspace's base branch that its project lacks.

    The promotion gate sees only what the closing branch added. A document
    committed straight onto the base branch (workspace left on it, an entry
    written outside a work branch, a recovery) is never the closing branch's,
    so it is counted here, after the ceremony, from the base branches as they
    now stand. Returns ({"workspace -> project": count}, commands).
    """
    backlog: dict[str, int] = {}
    commands: list[str] = []
    sweep = Path(__file__).resolve().parent / "artifact_promote.py"
    for ws_repo, project in promotion_pairs(workspace):
        ws_base, project_base = _get_base_branch(ws_repo), _get_base_branch(project)
        missing = 0
        for source, destination in _PROMOTED_DIRS:
            missing += len(_documents_on(ws_repo, ws_base, source)
                           - _documents_on(project, project_base, destination))
        if missing:
            backlog[f"{ws_repo.name} -> {project.name}"] = missing
            commands.append(f"python3 {sweep} sweep-gaps {project} {ws_repo}"
                            + (f" covers={covers}" if covers else ""))
    return backlog, commands


def _branch_landed(repo: Path, branch: str, base: str) -> bool:
    """A branch that is gone, stamped closed, or wholly on the base branch has landed."""
    if not _branch_exists(repo, branch):
        return True
    return _is_stamp_commit(repo, branch) or _is_ancestor(repo, branch, base)


def order_entries(entries: list[BatchEntry]) -> tuple[list[BatchEntry], list[str]]:
    """Put a batch in an order that is safe to land, derived from the repos themselves.

    An entry lands after the entry whose branch it was stacked on. That comes
    from each repo's record of what a branch was cut from; for branches cut
    before records existed it comes from ancestry (a branch whose tip is inside
    another's history lands first). Queue order only breaks ties.

    Returns (ordered entries, errors). Errors: a branch stacked on one that has
    not landed and is not in this batch; a record the branch no longer sits on;
    repos that disagree about the order.
    """
    errors: list[str] = []
    owner: dict[str, int] = {}
    for index, entry in enumerate(entries):
        for branch in entry.branches:
            owner.setdefault(branch, index)

    after: dict[int, set[int]] = {i: set() for i in range(len(entries))}
    why: dict[tuple[int, int], str] = {}

    def depend(later: int, earlier: int, reason: str) -> None:
        if later != earlier:
            after[later].add(earlier)
            why.setdefault((later, earlier), reason)

    for index, entry in enumerate(entries):
        for target in entry.targets:
            name = f"{target.repo.name}:{target.branch}"
            if branch_base.record_is_stale(target.repo, target.branch):
                errors.append(
                    f"{name} no longer sits on the commit it was recorded as cut from, so its "
                    f"own commits cannot be told apart from what it was stacked on. Nothing was "
                    f"landed. Rebase it back onto its parent, or clear the record if it was "
                    f"deliberately rebuilt.")
                continue
            parent = branch_base.parent_of(target.repo, target.branch)
            if parent:
                if parent in owner:
                    depend(index, owner[parent], f"{name} was stacked on {parent}")
                elif not _branch_landed(target.repo, parent, target.base_branch):
                    errors.append(
                        f"{name} was stacked on {parent}, which has not landed and is not part "
                        f"of this close. Nothing was landed. Land {parent} first, or mark its "
                        f"item done so that it lands in this batch.")
                continue
            # No record: fall back to what the commits themselves say.
            for other_index, other in enumerate(entries):
                if other_index == index:
                    continue
                for other_target in other.targets:
                    if other_target.repo != target.repo:
                        continue
                    mine = _rev_parse(target.repo, target.branch)
                    theirs = _rev_parse(target.repo, other_target.branch)
                    if mine and theirs and mine != theirs and \
                            _is_ancestor(target.repo, theirs, mine):
                        depend(index, other_index,
                               f"{name} contains {other_target.branch}")

    if errors:
        return entries, errors

    ordered: list[int] = []
    remaining = list(range(len(entries)))
    while remaining:
        ready = [i for i in remaining if not (after[i] - set(ordered))]
        if not ready:
            names = ", ".join(entries[i].issue or entry_branch(entries[i]) for i in remaining)
            reasons = "; ".join(sorted({why[(a, b)] for a in remaining for b in after[a]
                                        if b in remaining and (a, b) in why}))
            return entries, [
                f"the repos disagree about the order to land {names} in ({reasons}). "
                f"Nothing was landed."]
        ordered.append(ready[0])            # queue order breaks ties
        remaining.remove(ready[0])
    return [entries[i] for i in ordered], []


# --- stamp ---

def _is_stamp_commit(repo: Path, branch: str) -> bool:
    result = _git(repo, "log", "-1", "--format=%s", branch)
    if result.returncode != 0:
        return False
    return result.stdout.strip().startswith("chore: branch closed")


_QUALIFIED_REF = re.compile(r"^(?P<repo>[^#\s]+)#(?P<number>\d+)$")
_REMOTE_SLUG = re.compile(r"[:/]([^/:\s]+/[^/\s]+?)(?:\.git)?/?$")


def _published_as(repo: Path) -> str:
    """owner/name this repository's commits are published under; "" when unknown.

    Read from the remote its canonical repo publishes to, so a slot clone and a
    linked worktree answer the same as the canonical checkout.
    """
    try:
        canon = canonical_sync.locate(repo)
    except SyncError:
        return ""
    if not canon.blessed:
        return ""
    url = _git(canon.repo, "remote", "get-url", canon.blessed).stdout.strip()
    m = _REMOTE_SLUG.search(url)
    return m.group(1) if m else ""


def _issue_trailer(issue: str, repo: Optional[Path] = None) -> str:
    """Issue reference for a commit made in `repo` by the ceremony.

    A bare number means "an issue of the repository this commit is in", so it is
    used only there. Anywhere else the reference keeps its repository: a bare
    number would link to an unrelated issue. Installed commit-msg hooks come in
    two generations, one accepting only a bare number, so the qualified form
    carries a no-issue note that the older one accepts as well.
    """
    if not issue:
        return "no-issue: close ceremony bookkeeping"
    if issue.isdigit():
        return f"Refs #{issue}"
    m = _QUALIFIED_REF.match(issue)
    if not m:
        return "no-issue: close ceremony bookkeeping"
    home = _published_as(repo) if repo is not None else ""
    if home and home.lower() == m.group("repo").lower():
        return f"Refs #{m.group('number')}"
    return f"Refs {issue} (no-issue: the reference is repository-qualified)"


def stamp(target: CloseTarget, landed_sha: str, issue: str = "") -> None:
    if _is_stamp_commit(target.repo, target.branch):
        return

    with canonical_sync.checked_out(target.repo, target.branch) as tree:
        result = _git(tree, "commit", "--allow-empty",
                      "-m", f"chore: branch closed — landed as {landed_sha} on {target.base_branch}",
                      "-m", _issue_trailer(issue, target.repo))
    if result.returncode != 0:
        raise RuntimeError(
            f"stamp commit failed in {target.repo.name}: {result.stderr.strip()}")


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


def complete_item(workspace: Path, issue: str) -> None:
    """Check one done item, once its own landing and stamp have succeeded."""
    queue = read_queue(workspace)
    if queue is not None and queue.complete(issue):
        write_queue(workspace, queue)


def settle_queue(workspace: Path) -> Optional[QueueItem]:
    """After done items were closed: activate the next open item, or drain the queue."""
    queue = read_queue(workspace)
    if queue is None:
        return None
    if queue.active_item() is None:
        if queue.has_next():
            queue.activate_next()
            queue.set_status("active")
        elif not queue.done_items():
            queue.set_status("drained")
        write_queue(workspace, queue)
    return queue.active_item()


def commit_and_push_queue(workspace: Path, closing_issue: str, refs_issue: str = "") -> None:
    if queue_dir(workspace) != workspace:
        return      # the queue is at the area root or in the notes store: not a file tracked here
    if not (workspace / ".queue").exists():
        return
    _git(workspace, "add", ".queue")
    result = _git(workspace, "commit", "-m", f"chore: advance queue — completed {closing_issue}",
                  "-m", _issue_trailer(refs_issue or closing_issue, workspace), "--", ".queue")
    if result.returncode != 0 and _git(workspace, "status", "--porcelain", "--", ".queue").stdout.strip():
        raise RuntimeError(
            f"queue commit failed in {workspace.name}: {result.stderr.strip()}")


# --- elevate ---

def elevate_queue(workspace: Path, slot_root: Optional[Path]) -> None:
    if not slot_root:
        return
    if queue_dir(workspace) != workspace:
        return      # the slot already uses its root queue (#577): nothing is copied up
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
    """Move the session's own checkouts off the closed branch, onto the base branch.

    Only a repo that is sitting on the branch just closed is moved; a repo that is
    on anything else is someone's work in progress and is left where it is.
    """
    for target in targets:
        if _current_branch(target.repo) == target.branch:
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


def _slot_dir_of(workspace: Path) -> Optional[Path]:
    """The slot directory when the ceremony runs in a slot, whichever level it was given."""
    for candidate in (workspace, workspace.parent):
        if (candidate / ".slot").exists():
            return candidate
    return None


def mark_slot_landed(slot_dir: Path, branch: str, project_shas: dict[str, str]) -> None:
    """Record that every issue in this slot has landed, so it is ready to archive.

    The marker is a claim, not a proof: archive-slot checks each SHA against the
    canonical repo's base branch before it moves anything. Repos landed by an
    earlier close in the same slot are kept.
    """
    marker = slot_dir / ".landed"
    shas: dict[str, str] = {}
    if marker.exists():
        for line in marker.read_text().splitlines():
            if line.startswith("landed_shas="):
                for entry in line.split("=", 1)[1].split(","):
                    if ":" in entry:
                        name, sha = entry.split(":", 1)
                        shas[name] = sha
    shas.update({name: sha for name, sha in project_shas.items() if sha})
    if not shas:
        return
    import datetime
    marker.write_text("\n".join([
        f"branch={branch}",
        f"repos={','.join(shas)}",
        f"landed_shas={','.join(f'{n}:{s}' for n, s in shas.items())}",
        f"timestamp={datetime.datetime.now(datetime.timezone.utc).isoformat()}",
    ]) + "\n")


# --- close orchestration ---

def close(workspace: Path, land_active: bool = True) -> CloseResult:
    """Run the ceremony and record what it did, whether or not it succeeded."""
    result = _close(workspace, land_active)
    for ref in result.closed_items:
        worktrace.record("issue-close", repo=workspace,
                         branch=result.closed_branches.get(ref, ""), issue=ref)
    worktrace.record(
        "close-ceremony", repo=workspace, success=result.success,
        land_active=land_active, closed=result.closed_items,
        landed={**result.landed, **result.workspace_landed}, carried=result.carried,
        not_landed=result.not_landed, squash_review=result.squash_review,
        slot_ready=result.slot_ready, errors=[str(e)[:200] for e in result.errors])
    return result


def _close(workspace: Path, land_active: bool = True) -> CloseResult:
    """Run the ceremony. `land_active=False` lands only the items marked done and
    leaves the active item exactly as it is: still active, its branch unlanded
    and still checked out (#571). That is `work end` run part-way through the
    queue while the current item is unfinished."""
    busy = check_repos_idle(workspace)
    if busy:
        return CloseResult(success=False, errors=busy)

    misaligned = check_branch_alignment(workspace)
    if misaligned:
        return CloseResult(success=False, errors=misaligned)

    already_diverged = diverged_bases(_slot_dir_of(workspace))

    queue = read_queue(workspace)
    entries = batch_entries(workspace, queue) if queue else []
    repos = [repo for repo, *_ in discover_repo_topology(workspace)]

    missing = []
    for entry in entries:
        if not entry.done and not land_active:
            entry.targets = []      # handled below like an active item that was never started
            continue
        entry.targets = resolve(workspace, entry.branches)
        if entry.done and not entry.targets and not any(
                _branch_exists(repo, b) for repo in repos for b in entry.branches):
            missing.append(
                f"{entry.issue} is marked done on branch '{entry.branches[0]}', which exists "
                f"in no repo — nothing was landed. Restore the branch or correct the queue.")
    if missing:
        return CloseResult(success=False, errors=missing)

    entries, order_errors = order_entries(entries)
    if order_errors:
        return CloseResult(success=False, errors=order_errors)

    targets = [t for entry in entries for t in entry.targets]
    done_entries = [e for e in entries if e.done]

    if not targets and not done_entries:
        stamped = stamped_branches(workspace)
        if stamped:
            return CloseResult(
                success=False,
                errors=[f"branch already closed (stamped): {', '.join(stamped)} — "
                        f"nothing was landed. The queue names a branch that has "
                        f"already been closed."],
            )
        if not land_active:
            return CloseResult(
                success=False,
                errors=["nothing to land: no item is marked done, and the active item "
                        "was left out because it is not finished"])
        return CloseResult(
            success=False,
            errors=["no targets found — branch may not exist or has no commits"],
        )

    # Promotion first: promoting adds a commit to the project branch, and the squash
    # review below has to be of the branch as it will land.
    unpromoted, promote_commands = unpromoted_artifacts(
        workspace, queue.state.covers if queue else "")
    if unpromoted:
        return CloseResult(success=False, unpromoted=unpromoted,
                           promote_commands=promote_commands)

    # Checked before anything is rebased: the ceremony's own rebase changes every SHA.
    # One branch that needs review holds back the whole batch, so nothing lands out of order.
    review_needed = []
    for target in targets:
        if target.is_workspace:
            continue
        reason = squash_marker.review_status(target.repo, target.branch, target.base_branch)
        if reason:
            review_needed.append(f"{target.repo.name}:{target.branch}: {reason}")
    if review_needed:
        return CloseResult(success=False, squash_review=review_needed)

    active = queue.active_item() if queue else None
    closing_issue = active.ref if active else ""
    covers_issue = queue.state.covers.split(",")[0].strip() if queue else ""

    pre = preflight(targets)
    if pre["errors"]:
        return CloseResult(success=False, errors=list(dict.fromkeys(pre["errors"])))

    session_id = _generate_session_id()
    _write_close_state(workspace, {
        "step": "landing",
        "closing_issue": ", ".join(e.issue for e in entries if e.issue and (e.done or e.targets)),
        "session_id": session_id,
        "repos": ", ".join(f"{t.repo.name}:{t.branch}" for t in targets),
    })

    # A workspace repo can share its directory name with the project repo.
    split_workspace = len(discover_repo_topology(workspace)) > 1
    slot_root = _detect_slot_root(workspace)

    landed: dict[CloseTarget, str] = {}
    unpublished: dict[str, int] = {}
    warnings: list[str] = []
    closed: list[str] = []
    closed_branches: dict[str, str] = {}
    active_landed = False

    try:
        for entry in entries:
            if not entry.done and not entry.targets:
                continue  # the active item was never started: it stays active
            issue = entry.issue or covers_issue
            try:
                results = land_targets(entry.targets)
            except SyncError as error:
                raise RuntimeError(error.detail) from error
            for target, outcome in results.items():
                landed[target] = outcome.sha
                warnings.extend(outcome.warnings)
                canonical = str(canonical_sync.locate(target.repo).repo)
                unpublished.pop(canonical, None)
                if outcome.unpublished:
                    unpublished[canonical] = outcome.unpublished
            for target in entry.targets:
                stamp(target, landed[target], issue)
                worktrace.record("stamp", repo=target.repo, branch=target.branch,
                                 sha=landed[target], issue=issue)
                worktrace.work_ended(target.repo, target.branch, landed[target])
                squash_marker.clear(target.repo, target.branch)
                # The branch now sits on the base branch: the record has done its job.
                branch_base.clear(target.repo, target.branch)
            if entry.done:
                # Checked only now, so a later failure leaves the rest done-but-not-closed.
                complete_item(workspace, entry.issue)
                closed.append(entry.issue)
                closed_branches[entry.issue] = entry.branches[0]
            else:
                active_landed = True

        def finish_queue() -> Optional[QueueItem]:
            item = advance(workspace, closing_issue) if active_landed else None
            if active_landed and closing_issue:
                closed.append(closing_issue)
                active_entry = next((e for e in entries if not e.done), entries[-1])
                closed_branches[closing_issue] = entry_branch(active_entry)
            if done_entries:
                item = settle_queue(workspace)
            return item

        if slot_root:
            next_item = finish_queue()
            if (slot_root / ".permanent").exists() and (workspace / ".git").exists():
                # A permanent clone's workspace holds the repo's own queue, which
                # travels with its base branch: the completion is committed here
                # and reaches canonical when the workspace's commits are carried.
                # No second copy is kept at the clone root (#563).
                commit_and_push_queue(workspace, ", ".join(closed) or closing_issue,
                                      closed[-1] if closed else covers_issue)
            else:
                elevate_queue(workspace, slot_root)
            checkout_all(targets)
        else:
            checkout_all(targets)
            next_item = finish_queue()
            commit_and_push_queue(workspace, ", ".join(closed) or closing_issue,
                                  closed[-1] if closed else covers_issue)

        _remove_close_state(workspace)

        slot_ready = ""
        slot_dir = _slot_dir_of(workspace)
        carried: dict = {}
        not_landed: dict = {}
        if slot_dir is not None:
            carried, not_landed = carry_strays(
                slot_dir, {(t.repo, t.branch) for t in targets}, diverged=already_diverged)
        # A slot with anything still stranded in it is not ready to archive.
        # A permanent clone (#553) is never archived: it is where the repo's
        # work continues, so a drained queue leaves it exactly as it is.
        permanent = slot_dir is not None and (slot_dir / ".permanent").exists()
        if permanent:
            kept = set() if active_landed or not queue else {
                b for b in discover_active_branches(workspace, queue)}
            warnings.extend(settle_permanent_clone(slot_dir, keep_branches=kept))

        # Counted last: after the queue commit and after strays were carried, and
        # for the workspace even when it had no branch to land. Commits made
        # straight onto a base branch (queue, handoff, diary) are unpublished
        # work too (#559, #563).
        covered = [t.repo for t in targets]
        if (workspace / ".git").exists():
            covered.append(workspace)
        if slot_dir is not None:
            from slot_core import get_all_slot_repos
            covered += [slot_dir / name for name in get_all_slot_repos(slot_dir)]
        for repo in covered:
            try:
                canon = canonical_sync.locate(repo)
            except SyncError:
                continue
            count = canonical_sync.unpublished(canon)
            if count:
                unpublished[str(canon.repo)] = count
            else:
                unpublished.pop(str(canon.repo), None)
        if slot_dir is not None and not permanent and next_item is None and not not_landed:
            mark_slot_landed(
                slot_dir, queue.state.branch if queue else "",
                {t.repo.name: sha for t, sha in landed.items() if not t.is_workspace})
            if (slot_dir / ".landed").exists():
                slot_ready = str(slot_dir)

        try:
            backlog, backlog_commands = promotion_backlog(workspace, covers_issue)
        except Exception as error:      # a report must never fail a ceremony that landed
            backlog, backlog_commands = {}, []
            warnings.append(f"promotion backlog could not be counted: {error}")

        return CloseResult(
            success=True,
            backlog=backlog,
            backlog_commands=backlog_commands,
            slot_ready=slot_ready,
            landed={t.repo.name: sha for t, sha in landed.items()
                    if not (split_workspace and t.is_workspace)},
            workspace_landed={t.repo.name: sha for t, sha in landed.items()
                              if split_workspace and t.is_workspace},
            next_item=next_item,
            rescued=pre["rescued"],
            closed_items=closed,
            closed_branches=closed_branches,
            unpublished=unpublished,
            warnings=list(dict.fromkeys(warnings)),
            carried=carried,
            not_landed=not_landed,
        )
    except Exception:
        # Nothing was switched while landing, so no checkout needs putting back.
        if closed and not slot_root:
            # Record the items that did close, so a rerun starts from the failed one.
            try:
                commit_and_push_queue(workspace, ", ".join(closed), closed[-1])
            except RuntimeError as commit_error:
                print(f"WARN=queue_progress_not_committed detail={commit_error}", file=sys.stderr)
        raise


def entry_branch(entry: BatchEntry) -> str:
    return entry.branches[0] if entry.branches else ""


def render(result: CloseResult) -> list[str]:
    """KEY=value lines describing a ceremony result."""
    if result.success:
        lines = ["ACTION=complete"]
        lines += [f"LANDED_{repo}={sha}" for repo, sha in result.landed.items()]
        lines += [f"WORKSPACE_LANDED_{repo}={sha}"
                  for repo, sha in result.workspace_landed.items()]
        lines += [f"CLOSED_ITEM={ref} branch={result.closed_branches.get(ref, '')}"
                  for ref in result.closed_items]
        if result.next_item:
            lines.append(f"NEXT_ITEM={result.next_item.ref}")
        lines += [f"CARRIED={key} commits={count}" for key, count in result.carried.items()]
        lines += [f"NOT_LANDED={key} reason={why}" for key, why in result.not_landed.items()]
        lines += [f"WARN={warning}" for warning in result.warnings]
        lines += [f"UNPUBLISHED={repo} commits={count}"
                  for repo, count in result.unpublished.items()]
        if result.unpublished:
            lines.append("OFFER=publish")
        lines += [f"UNPROMOTED_BACKLOG={pair} documents={count}"
                  for pair, count in result.backlog.items()]
        lines += [f"PROMOTE_BACKLOG={command}" for command in result.backlog_commands]
        if result.backlog:
            lines.append("OFFER=promote_backlog")
        if result.slot_ready:
            lines.append(f"SLOT_READY_FOR_ARCHIVE={result.slot_ready}")
        return lines
    if result.squash_review:
        return ["ACTION=squash_review_needed"] + [f"SQUASH_REVIEW={r}" for r in result.squash_review]
    if result.unpromoted:
        return (["ACTION=promotion_needed"]
                + [f"UNPROMOTED={u}" for u in result.unpromoted]
                + [f"PROMOTE={c}" for c in result.promote_commands])
    return ["ACTION=error"] + [f"ERROR={e}" for e in result.errors]


def main() -> int:
    if len(sys.argv) < 2:
        print("ERROR=missing_workspace")
        return 1
    workspace = Path(sys.argv[1])
    if not workspace.is_dir():
        print(f"ERROR=workspace_not_found:{workspace}")
        return 1
    land_active = "land_active=no" not in sys.argv[2:]
    try:
        result = close(workspace, land_active=land_active)
    except Exception as e:
        print(f"ACTION=error\nERROR={e}")
        return 1
    for line in render(result):
        print(line)
    if result.success:
        return 0
    return 2 if (result.squash_review or result.unpromoted) else 1


if __name__ == "__main__":
    sys.exit(main())
