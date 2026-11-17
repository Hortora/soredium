"""Atomic close ceremony for work-end.

Single entry point: close(workspace) → CloseResult.
Reads .queue and git state; lands branches, stamps, advances queue.
Each step is idempotent — re-running after failure picks up from
committed state.

Landing goes through project/canonical_sync.py: every branch ends on the
canonical repo's base branch by fast-forward, on disk. Nothing is pushed here;
publishing is `canonical_sync.py publish <repo>`, which the ceremony offers when
canonical holds commits its remote lacks. No checkout is switched while landing.
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
import squash_marker
import canonical_sync
from canonical_sync import SyncError


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
    squash_review: list[str] = field(default_factory=list)
    workspace_landed: dict = field(default_factory=dict)
    slot_ready: str = ""
    # Queue items this ceremony closed, in the order they landed, and each one's branch.
    closed_items: list[str] = field(default_factory=list)
    closed_branches: dict = field(default_factory=dict)
    # Canonical repos holding commits their remote lacks: {canonical path: count}.
    unpublished: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


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


def land_targets(targets: list[CloseTarget], offline: bool = False) -> dict:
    """Land every target in canonical, on disk. Returns {target: LandResult}.

    Project and workspace repos take the same linear path: rebase, then
    fast-forward the canonical base branch. Nothing is pushed.
    """
    for target in targets:
        strip_lifecycle_files(target.repo, target.branch, LIFECYCLE_FILES)
    results = canonical_sync.land_all(
        [(target.repo, target.branch) for target in targets], offline=offline)
    landed = dict(zip(targets, results))
    for target, result in landed.items():
        verify_content_landed(target, result.sha)
    return landed


def land(target: CloseTarget, issue: str = "") -> str:
    """Land one target; returns the canonical base SHA it landed as."""
    return land_targets([target])[target].sha


# --- stamp ---

def _is_stamp_commit(repo: Path, branch: str) -> bool:
    result = _git(repo, "log", "-1", "--format=%s", branch)
    if result.returncode != 0:
        return False
    return result.stdout.strip().startswith("chore: branch closed")


def _issue_trailer(issue: str) -> str:
    """Trailer that satisfies a commit-msg hook requiring an issue reference."""
    return f"Refs {issue}" if issue else "no-issue: close ceremony bookkeeping"


def stamp(target: CloseTarget, landed_sha: str, issue: str = "") -> None:
    if _is_stamp_commit(target.repo, target.branch):
        return

    with canonical_sync.checked_out(target.repo, target.branch) as tree:
        result = _git(tree, "commit", "--allow-empty",
                      "-m", f"chore: branch closed — landed as {landed_sha} on {target.base_branch}",
                      "-m", _issue_trailer(issue))
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
    if not (workspace / ".queue").exists():
        return
    _git(workspace, "add", ".queue")
    result = _git(workspace, "commit", "-m", f"chore: advance queue — completed {closing_issue}",
                  "-m", _issue_trailer(refs_issue or closing_issue), "--", ".queue")
    if result.returncode != 0 and _git(workspace, "status", "--porcelain", "--", ".queue").stdout.strip():
        raise RuntimeError(
            f"queue commit failed in {workspace.name}: {result.stderr.strip()}")


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

def close(workspace: Path, offline: bool = False) -> CloseResult:
    busy = check_repos_idle(workspace)
    if busy:
        return CloseResult(success=False, errors=busy)

    misaligned = check_branch_alignment(workspace)
    if misaligned:
        return CloseResult(success=False, errors=misaligned)

    queue = read_queue(workspace)
    entries = batch_entries(workspace, queue) if queue else []
    repos = [repo for repo, *_ in discover_repo_topology(workspace)]

    missing = []
    for entry in entries:
        entry.targets = resolve(workspace, entry.branches)
        if entry.done and not entry.targets and not any(
                _branch_exists(repo, b) for repo in repos for b in entry.branches):
            missing.append(
                f"{entry.issue} is marked done on branch '{entry.branches[0]}', which exists "
                f"in no repo — nothing was landed. Restore the branch or correct the queue.")
    if missing:
        return CloseResult(success=False, errors=missing)

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
        return CloseResult(
            success=False,
            errors=["no targets found — branch may not exist or has no commits"],
        )

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
                results = land_targets(entry.targets, offline)
            except SyncError as error:
                hint = (" — rerun with offline=yes to land without checking the remote"
                        if error.code == "fetch_failed" else "")
                raise RuntimeError(f"{error.detail}{hint}") from error
            for target, outcome in results.items():
                landed[target] = outcome.sha
                warnings.extend(outcome.warnings)
                canonical = str(canonical_sync.locate(target.repo).repo)
                unpublished.pop(canonical, None)
                if outcome.unpublished:
                    unpublished[canonical] = outcome.unpublished
            for target in entry.targets:
                stamp(target, landed[target], issue)
                squash_marker.clear(target.repo, target.branch)
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
                closed_branches[closing_issue] = entry_branch(entries[-1])
            if done_entries:
                item = settle_queue(workspace)
            return item

        if slot_root:
            next_item = finish_queue()
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
        if slot_dir is not None and next_item is None:
            mark_slot_landed(
                slot_dir, queue.state.branch if queue else "",
                {t.repo.name: sha for t, sha in landed.items() if not t.is_workspace})
            if (slot_dir / ".landed").exists():
                slot_ready = str(slot_dir)

        return CloseResult(
            success=True,
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
        lines += [f"WARN={warning}" for warning in result.warnings]
        lines += [f"UNPUBLISHED={repo} commits={count}"
                  for repo, count in result.unpublished.items()]
        if result.unpublished:
            lines.append("OFFER=publish")
        if result.slot_ready:
            lines.append(f"SLOT_READY_FOR_ARCHIVE={result.slot_ready}")
        return lines
    if result.squash_review:
        return ["ACTION=squash_review_needed"] + [f"SQUASH_REVIEW={r}" for r in result.squash_review]
    return ["ACTION=error"] + [f"ERROR={e}" for e in result.errors]


def main() -> int:
    if len(sys.argv) < 2:
        print("ERROR=missing_workspace")
        return 1
    workspace = Path(sys.argv[1])
    if not workspace.is_dir():
        print(f"ERROR=workspace_not_found:{workspace}")
        return 1
    offline = any(arg in ("offline=yes", "--offline") for arg in sys.argv[2:])
    try:
        result = close(workspace, offline=offline)
    except Exception as e:
        print(f"ACTION=error\nERROR={e}")
        return 1
    for line in render(result):
        print(line)
    if result.success:
        return 0
    return 2 if result.squash_review else 1


if __name__ == "__main__":
    sys.exit(main())
