"""Where a working branch starts, and the record of where it did start (#515).

A queue's items normally build on each other, so a new branch is stacked on the
branch of the item just before it in the queue when that item is finished but
not yet closed. An item marked `(from main)` in the queue, the first item, and
any item whose predecessor has already landed start from the base branch.

A workspace repo is the exception to `(from main)`: it holds the queue file and
the session's working notes, which are tracked per branch, so its branch always
continues from the previous item's branch while that item is unclosed. Starting
it from main would leave the queue's own state behind. Only code repos honour
`(from main)`.

When a branch is cut, each repo records the fact in refs of its own:

    refs/soredium/base/<branch>     the commit the branch was cut from
    refs/soredium/parent/<branch>   symbolic ref to the branch it was stacked on
                                    (absent when it was cut from the base branch)

The record is keyed by branch name, not by commit, so it survives the branch
being rewritten by a squash: the squashed branch keeps its name and still sits
on the recorded commit. A branch's own commits are `base..branch`; everything
at or before the recorded commit belongs to whatever it was stacked on.

Nothing here touches the network or switches a checkout.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from git_util import git

BASE_REF = "refs/soredium/base"
PARENT_REF = "refs/soredium/parent"


@dataclass(frozen=True)
class StartPoint:
    stacked: bool
    parent: str         # branch code repos stack on; "" when starting from the base branch
    reason: str         # why, in words a person can check against the queue
    carry: str = ""     # branch a workspace repo continues from, whatever `parent` is


def _out(repo: Path | str, *args: str) -> str:
    result = git(repo, *args)
    return result.stdout.strip() if result.returncode == 0 else ""


def _sha(repo: Path | str, ref: str) -> str:
    return _out(repo, "rev-parse", "--verify", "-q", f"{ref}^{{commit}}")


def branch_exists(repo: Path | str, branch: str) -> bool:
    return bool(_sha(repo, f"refs/heads/{branch}"))


def _read_queue(workspace: Path):
    from queue_io import queue_dir, read_queue
    if queue_dir(workspace) != workspace:      # root queue or notes store (#577)
        return read_queue(workspace)
    for candidate in (workspace, workspace.parent):
        if (candidate / ".queue").exists() or (candidate / ".plan").exists():
            queue = read_queue(candidate)
            if queue is not None:
                return queue
    return None


def start_point(workspace: Path | str, issue_ref: str = "") -> StartPoint:
    """Decide where the next branch starts, from the queue alone.

    `issue_ref` names the item being started; without it the active item is
    used. Stacking is always on the item immediately before it in the queue.
    """
    queue = _read_queue(Path(workspace))
    if queue is None or not queue.items:
        return StartPoint(False, "", "no queue: start from the base branch")

    index = None
    if issue_ref:
        wanted = issue_ref.lower()
        index = next((i for i, item in enumerate(queue.items)
                      if item.ref.lower() == wanted), None)
    if index is None:
        index = next((i for i, item in enumerate(queue.items) if item.active), None)
    if index is None:
        return StartPoint(False, "", "no active queue item: start from the base branch")

    item = queue.items[index]
    if index == 0:
        return StartPoint(False, "", f"{item.ref} is the first item in the queue")
    before = queue.items[index - 1]
    carry = before.done_branch if (before.done_branch and not before.completed) else ""
    if item.from_main:
        return StartPoint(False, "", f"{item.ref} is marked (from main)", carry)
    if before.completed:
        return StartPoint(False, "", f"{before.ref}, the item before it, has already landed")
    if not before.done_branch:
        return StartPoint(False, "", f"{before.ref}, the item before it, has no finished branch")
    return StartPoint(True, before.done_branch,
                      f"stacked on {before.done_branch}, the branch of {before.ref}", carry)


def record(repo: Path | str, branch: str, base_sha: str, parent: str = "") -> None:
    """Record where `branch` was cut from in `repo`."""
    git(repo, "update-ref", f"{BASE_REF}/{branch}", base_sha)
    if parent:
        git(repo, "symbolic-ref", f"{PARENT_REF}/{branch}", f"refs/heads/{parent}")
    else:
        git(repo, "symbolic-ref", "--delete", f"{PARENT_REF}/{branch}")


def clear(repo: Path | str, branch: str) -> None:
    git(repo, "update-ref", "-d", f"{BASE_REF}/{branch}")
    git(repo, "symbolic-ref", "--delete", f"{PARENT_REF}/{branch}")


def parent_of(repo: Path | str, branch: str) -> str:
    """The branch `branch` was stacked on in `repo`, "" when cut from the base branch
    or when nothing was recorded."""
    target = _out(repo, "symbolic-ref", "-q", f"{PARENT_REF}/{branch}")
    return target.removeprefix("refs/heads/") if target else ""


def base_of(repo: Path | str, branch: str) -> str:
    """The recorded commit `branch` was cut from in `repo`, "" when nothing usable is
    recorded. A record that is not an ancestor of the branch is not usable: the
    branch was rebuilt on something else, and trusting the record would drop or
    duplicate commits."""
    recorded = _sha(repo, f"{BASE_REF}/{branch}")
    if not recorded or not branch_exists(repo, branch):
        return ""
    if git(repo, "merge-base", "--is-ancestor", recorded, f"refs/heads/{branch}").returncode != 0:
        return ""
    return recorded


def record_is_stale(repo: Path | str, branch: str) -> bool:
    """True when a base was recorded for `branch` but the branch no longer sits on it."""
    return bool(_sha(repo, f"{BASE_REF}/{branch}")) and branch_exists(repo, branch) \
        and not base_of(repo, branch)


def own_range(repo: Path | str, branch: str, fallback_base: str) -> str:
    """The revision range holding only `branch`'s own commits."""
    recorded = base_of(repo, branch)
    return f"{recorded}..{branch}" if recorded else f"{fallback_base}..{branch}"


def own_commit_count(repo: Path | str, branch: str, fallback_base: str) -> int:
    count = _out(repo, "rev-list", "--count", own_range(repo, branch, fallback_base))
    return int(count) if count.isdigit() else 0


def cut(repo: Path | str, branch: str, base_branch: str, parent: str = "") -> tuple[bool, str]:
    """Create `branch` in `repo` and check it out, recording where it was cut from.

    Stacked on `parent` when that branch exists in this repo; otherwise cut from
    `base_branch`. Returns (ok, detail): detail is what it was cut from, or git's
    error. When the branch already exists and has a base record, it is checked out
    and ``resumed:<parent_or_base>`` is returned as the detail. Uncommitted changes
    are carried over by git when they do not conflict and refuse the checkout when
    they do; nothing is stashed.
    """
    if branch in (base_branch, "HEAD"):
        return False, f"refused:branch name '{branch}' is the base branch or reserved"

    stack_on = parent if parent and branch_exists(repo, parent) else ""
    start = stack_on or base_branch
    start_sha = _sha(repo, f"refs/heads/{start}") or _sha(repo, start)
    if not start_sha:
        return False, f"{start} does not exist in {Path(repo).name}"

    if branch_exists(repo, branch):
        recorded = _sha(repo, f"{BASE_REF}/{branch}")
        if recorded:
            result = git(repo, "checkout", "-q", branch)
            if result.returncode != 0:
                return False, " ".join((result.stderr or result.stdout).split())
            existing_parent = parent_of(repo, branch)
            return True, f"resumed:{existing_parent or base_branch}"
        return False, f"branch_exists:{branch} in {Path(repo).name}"

    result = git(repo, "checkout", "-q", "-b", branch, start_sha)
    if result.returncode != 0:
        return False, " ".join((result.stderr or result.stdout).split())
    record(repo, branch, start_sha, stack_on)
    return True, stack_on or base_branch
