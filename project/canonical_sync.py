"""Every base-branch change and every push goes through here (#515).

Rules this module enforces:

  1. Linear history: a base branch only ever fast-forwards.
  2. Canonical is the sync point: work reaches the canonical repo first.
  3. Only canonical publishes: nothing is pushed to a remote from a slot clone.

Landing and publishing are separate. Landing puts a branch on canonical's base
branch, on disk. It never touches the network:

  rebase   the branch is rebased onto canonical base, where it is checked out or
           in a temporary worktree; canonical's own checkout is never switched
  hold     canonical takes the branch into refs/landing/<branch>
  advance  canonical's base branch fast-forwards to the held ref

Publishing (`publish_base`, or `canonical_sync.py publish <repo>`) is a step of
its own, and the only one that uses the network:

  fetch    the blessed remote's base branch
  settle   canonical base fast-forwards to it; or, when canonical holds commits
           of its own and the remote has moved, those unpublished commits are
           rebased onto the remote's (nothing anyone else has is rewritten)
  stage    canonical base is pushed to the fork as the branch publish/<base>
  publish  plain push to the blessed remote's base branch; never forced
  mirror   the fork's base branch follows the blessed remote's

The fork gets the work first and as a branch, which is what a pull request
needs; when publishing moves to pull requests only the publish step changes.

Canonical may be mid-work. Nothing here stashes, resets or checks out in a
canonical repo, and the only rebase it ever aborts is one it started itself.
"""
from __future__ import annotations

import fcntl
import os
import sys
import shutil
import tempfile
import time
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

from git_util import git

LANDING_REF = "refs/landing"
STAGING_BRANCH = "publish"
BACKUP_REF = "refs/backup"
PUBLISH_ATTEMPTS = 3
LOCK_TIMEOUT = 120.0
_NETWORK_TIMEOUT = 300
_REBASE_MARKERS = ("rebase-merge", "rebase-apply")


class SyncError(Exception):
    """A landing step refused. `code` is stable; `detail` is for people."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class Canonical:
    repo: Path      # the canonical repo
    base: str       # its base branch
    blessed: str    # remote that base is published to; "" when the repo has no remote
    mirror: str     # second remote kept in step with base; "" when there is none


@dataclass
class LandResult:
    repo: Path
    branch: str
    sha: str = ""               # canonical base after landing
    already_landed: bool = False
    unpublished: int = 0        # commits on canonical base the blessed remote lacks
    warnings: list[str] = field(default_factory=list)


@dataclass
class PublishResult:
    repo: Path
    sha: str = ""
    pushed: int = 0             # commits the blessed remote gained
    rebased: int = 0            # unpublished commits rewritten onto a remote that had moved
    published: str = "none"     # blessed remote name, or "none" when the repo has no remote
    staged: str = "none"        # "<fork>/publish/<base>", "none", or "failed"
    mirrored: str = "none"      # mirror remote name, "none", or "failed"
    warnings: list[str] = field(default_factory=list)


# --- reading state ---

def _out(repo: Path, *args: str) -> str:
    result = git(repo, *args)
    return result.stdout.strip() if result.returncode == 0 else ""


def _sha(repo: Path, ref: str) -> str:
    return _out(repo, "rev-parse", "--verify", "-q", f"{ref}^{{commit}}")


def _is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    return git(repo, "merge-base", "--is-ancestor", ancestor, descendant).returncode == 0


def _git_dir(repo: Path, flag: str = "--absolute-git-dir") -> Path:
    path = Path(_out(repo, "rev-parse", flag))
    return path if path.is_absolute() else (repo / path).resolve()


def _base_branch(repo: Path) -> str:
    for candidate in ("main", "master"):
        if git(repo, "rev-parse", "--verify", "-q", f"refs/heads/{candidate}").returncode == 0:
            return candidate
    return "main"


def _is_repo(path: Path) -> bool:
    return path.is_dir() and git(path, "rev-parse", "--git-dir").returncode == 0


def locate(repo: Path | str) -> Canonical:
    """Find the canonical repo behind `repo` and where it publishes.

    A slot clone names its canonical repo with a `local` remote. Anything else
    (a canonical checkout, or one of its linked worktrees) is canonical itself.
    A clone inside a slot with no usable `local` remote is an error: treating
    it as its own canonical would "land" work that never leaves the slot.

    Remotes, by the two conventions in use: `upstream` is published to and
    `origin` mirrors it; otherwise `origin` is published to and `fork`, when
    present, mirrors it.
    """
    repo = Path(repo)
    canonical = repo
    url = _out(repo, "remote", "get-url", "local")
    if url:
        if not _is_repo(Path(url)):
            raise SyncError(
                "no_canonical",
                f"{repo.name}: its `local` remote names {url}, which is not a git repo")
        canonical = Path(url).resolve()
    elif (repo.parent / ".slot").exists():
        raise SyncError(
            "no_canonical",
            f"{repo.name}: a slot clone with no `local` remote; it cannot say which "
            f"canonical repo its work lands in")
    else:
        common = _git_dir(repo, "--git-common-dir")
        if common.name == ".git":
            canonical = common.parent
    remotes = _out(canonical, "remote").split()
    if "upstream" in remotes:
        blessed, mirror = "upstream", ("origin" if "origin" in remotes else "")
    elif "origin" in remotes:
        blessed, mirror = "origin", ("fork" if "fork" in remotes else "")
    else:
        blessed, mirror = "", ""
    return Canonical(canonical, _base_branch(canonical), blessed, mirror)


def _worktrees(repo: Path) -> list[tuple[Path, str]]:
    """(path, checked-out branch or "") for every worktree of `repo`."""
    found: list[tuple[Path, str]] = []
    path: Optional[Path] = None
    branch = ""
    for line in _out(repo, "worktree", "list", "--porcelain").splitlines() + [""]:
        if line.startswith("worktree "):
            path, branch = Path(line[len("worktree "):]), ""
        elif line.startswith("branch refs/heads/"):
            branch = line[len("branch refs/heads/"):]
        elif not line and path is not None:
            found.append((path, branch))
            path = None
    return found


def _worktree_of(repo: Path, branch: str) -> Optional[Path]:
    for path, checked_out in _worktrees(repo):
        if checked_out == branch:
            return path
    return None


def _rebase_in_progress(worktree: Path) -> Optional[str]:
    """Name of the branch being rebased in `worktree`, "" if unknown, None if idle."""
    git_dir = _git_dir(worktree)
    for marker in _REBASE_MARKERS:
        state = git_dir / marker
        if state.is_dir():
            head_name = state / "head-name"
            if head_name.exists():
                return head_name.read_text().strip().removeprefix("refs/heads/")
            return ""
    return None


def _in_progress(worktree: Path) -> Optional[str]:
    if _rebase_in_progress(worktree) is not None:
        return "rebase"
    git_dir = _git_dir(worktree)
    for marker, operation in (("MERGE_HEAD", "merge"), ("CHERRY_PICK_HEAD", "cherry-pick"),
                              ("REVERT_HEAD", "revert")):
        if (git_dir / marker).exists():
            return operation
    return None


def _base_being_rebased(canon: Canonical) -> Optional[Path]:
    for path, _ in _worktrees(canon.repo):
        if _rebase_in_progress(path) == canon.base:
            return path
    return None


# --- lock ---

@contextmanager
def landing_lock(canon: Canonical, timeout: float = LOCK_TIMEOUT) -> Iterator[None]:
    """One landing at a time per canonical repo."""
    lock_path = _git_dir(canon.repo, "--git-common-dir") / "soredium-landing.lock"
    handle = open(lock_path, "a+")
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise SyncError(
                        "locked", f"{canon.repo.name}: another landing holds {lock_path}")
                time.sleep(0.2)
        handle.seek(0)
        handle.truncate()
        handle.write(f"pid={os.getpid()}\n")
        handle.flush()
        yield
    finally:
        try:
            fcntl.flock(handle, fcntl.LOCK_UN)
        finally:
            handle.close()


# --- steps ---

def advance(canon: Canonical, ref: str) -> None:
    """Fast-forward canonical's base branch to `ref`. Never rewrites, never switches."""
    target = _sha(canon.repo, ref)
    if not target:
        raise SyncError("advance_failed", f"{canon.repo.name}: {ref} does not exist")
    current = _sha(canon.repo, f"refs/heads/{canon.base}")
    if current == target:
        return
    if current and not _is_ancestor(canon.repo, current, target):
        raise SyncError(
            "diverged",
            f"{canon.repo.name}: {canon.base} has commits that {ref} lacks; "
            f"it cannot fast-forward")
    busy = _base_being_rebased(canon)
    if busy:
        raise SyncError(
            "base_busy", f"{canon.repo.name}: {canon.base} is being rebased in {busy}")
    checked_out = _worktree_of(canon.repo, canon.base)
    if checked_out is not None:
        operation = _in_progress(checked_out)
        if operation:
            raise SyncError(
                "base_busy",
                f"{canon.repo.name}: a {operation} is in progress on {canon.base} in {checked_out}")
        result = git(checked_out, "merge", "--ff-only", "-q", target)
    else:
        # git refuses this itself when base is checked out or is not a fast-forward.
        result = git(canon.repo, "fetch", "-q", ".", f"{ref}:refs/heads/{canon.base}")
    if result.returncode != 0 or _sha(canon.repo, f"refs/heads/{canon.base}") != target:
        raise SyncError(
            "advance_blocked",
            f"{canon.repo.name}: {canon.base} could not fast-forward to {target[:12]}: "
            f"{result.stderr.strip()}")


def _fetch_blessed(canon: Canonical) -> str:
    """Fetch the blessed remote's base branch. Returns its SHA, "" if it has none yet."""
    fetched = git(canon.repo, "fetch", "-q", canon.blessed, canon.base,
                  timeout=_NETWORK_TIMEOUT)
    if fetched.returncode != 0:
        if "couldn't find remote ref" in fetched.stderr.lower():
            return ""
        raise SyncError(
            "fetch_failed",
            f"{canon.repo.name}: cannot fetch {canon.base} from {canon.blessed}: "
            f"{fetched.stderr.strip()}")
    return _sha(canon.repo, f"refs/remotes/{canon.blessed}/{canon.base}")


def sync_base(canon: Canonical) -> str:
    """Fast-forward canonical's base branch to the blessed remote. Returns base's SHA.

    Canonical ahead of the remote is left alone. Each holding commits the other
    lacks is a divergence: nothing is changed (`settle_base` is what resolves it).
    """
    local_ref = f"refs/heads/{canon.base}"
    if not canon.blessed:
        return _sha(canon.repo, local_ref)
    remote = _fetch_blessed(canon)
    local = _sha(canon.repo, local_ref)
    if not remote or remote == local or (local and _is_ancestor(canon.repo, remote, local)):
        return local
    if local and not _is_ancestor(canon.repo, local, remote):
        raise SyncError(
            "diverged",
            f"{canon.repo.name}: local {canon.base} and {canon.blessed}/{canon.base} "
            f"have diverged")
    advance(canon, f"refs/remotes/{canon.blessed}/{canon.base}")
    return remote


def settle_base(canon: Canonical) -> int:
    """Make canonical's base branch sit on top of the blessed remote's. Publishing only.

    Fast-forwards when canonical has nothing of its own. When it has, and the
    remote moved, its unpublished commits are rebased onto the remote's and the
    count is returned. Only commits no remote holds are rewritten. Refuses, with
    nothing changed, on a conflict or when the base branch's checkout has
    uncommitted changes to tracked files.
    """
    remote = _fetch_blessed(canon)
    local = _sha(canon.repo, f"refs/heads/{canon.base}")
    if not remote or remote == local or _is_ancestor(canon.repo, remote, local):
        return 0
    remote_ref = f"refs/remotes/{canon.blessed}/{canon.base}"
    if _is_ancestor(canon.repo, local, remote):
        advance(canon, remote_ref)
        return 0
    busy = _base_being_rebased(canon)
    if busy:
        raise SyncError(
            "base_busy", f"{canon.repo.name}: {canon.base} is being rebased in {busy}")
    count = _out(canon.repo, "rev-list", "--count", f"{remote}..{local}")
    _rebase_where_checked_out(canon.repo, canon.base, remote, f"{canon.blessed}/{canon.base}")
    return int(count) if count.isdigit() else 0


def _onto(repo: Path, canon: Canonical) -> str:
    """The commit a branch in `repo` is rebased onto: canonical's base branch."""
    if repo.resolve() == canon.repo.resolve() or \
            _git_dir(repo, "--git-common-dir") == _git_dir(canon.repo, "--git-common-dir"):
        return _sha(canon.repo, f"refs/heads/{canon.base}")
    result = git(repo, "fetch", "-q", str(canon.repo), f"refs/heads/{canon.base}")
    if result.returncode != 0:
        raise SyncError(
            "fetch_failed",
            f"{repo.name}: cannot fetch {canon.base} from canonical: {result.stderr.strip()}")
    return _sha(repo, "FETCH_HEAD")


def _conflicted(worktree: Path) -> list[str]:
    return [name for name in
            _out(worktree, "diff", "--name-only", "--diff-filter=U").splitlines() if name]


@contextmanager
def checked_out(repo: Path | str, branch: str) -> Iterator[Path]:
    """A directory where `branch` is checked out, without switching any existing checkout.

    Yields the worktree that already has the branch, or a temporary one that is
    removed afterwards. Refuses when that worktree is mid-rebase or mid-merge:
    whoever started that operation owns it.
    """
    repo = Path(repo)
    if not _sha(repo, f"refs/heads/{branch}"):
        raise SyncError("no_branch", f"{repo.name}: branch {branch} does not exist")
    worktree = _worktree_of(repo, branch)
    if worktree is not None:
        operation = _in_progress(worktree)
        if operation:
            raise SyncError(
                "busy",
                f"{repo.name}: a {operation} is in progress in {worktree}; finish it first")
        yield worktree
        return
    for path, _ in _worktrees(repo):
        if _rebase_in_progress(path) == branch:
            raise SyncError(
                "busy", f"{repo.name}: {branch} is already being rebased in {path}")
    temporary = Path(tempfile.mkdtemp(prefix="soredium-worktree-"))
    added = git(repo, "worktree", "add", "-q", str(temporary / "wt"), branch)
    if added.returncode != 0:
        shutil.rmtree(temporary, ignore_errors=True)
        raise SyncError(
            "worktree_refused",
            f"{repo.name}: cannot open a worktree for {branch}: {added.stderr.strip()}")
    try:
        yield temporary / "wt"
    finally:
        git(repo, "worktree", "remove", "--force", str(temporary / "wt"))
        shutil.rmtree(temporary, ignore_errors=True)
        git(repo, "worktree", "prune")


def _rebase_where_checked_out(repo: Path, branch: str, onto: str, onto_name: str,
                              own_base: str = "") -> None:
    """Rebase `branch` onto `onto` without switching any existing checkout.

    With `own_base`, only the commits after it are replayed: the branch's own
    work, not what it was stacked on. A conflict aborts the rebase this call
    started; the branch is left as it was.
    """
    with checked_out(repo, branch) as worktree:
        args = ["rebase", "-q", "--onto", onto, own_base] if own_base else ["rebase", "-q", onto]
        result = git(worktree, *args, timeout=_NETWORK_TIMEOUT)
        if result.returncode != 0:
            if _rebase_in_progress(worktree) is not None:
                files = _conflicted(worktree)
                git(worktree, "rebase", "--abort")      # the rebase this call started
                raise SyncError(
                    "rebase_conflict",
                    f"{repo.name}: {branch} conflicts with {onto_name} in "
                    f"{', '.join(files) or 'unknown files'}")
            raise SyncError(
                "rebase_refused",
                f"{repo.name}: {branch} could not be rebased: "
                f"{(result.stderr or result.stdout).strip()}")


def rebase(repo: Path | str, branch: str, canon: Optional[Canonical] = None,
           own_base: str = "") -> str:
    """Rebase `branch` onto canonical's base branch. Returns the new tip.

    Runs where the branch is checked out; otherwise in a temporary worktree, so
    no existing checkout is switched. A conflict aborts the rebase this call
    started and leaves the branch exactly as it was.

    `own_base` is the commit the branch was cut from (project/branch_base.py).
    With it, only the branch's own commits are replayed. That matters for a
    stacked branch whose parent was squashed before landing: the parent's old
    commits are still under the branch, and replaying them onto the squashed
    parent would conflict or duplicate.
    """
    repo = Path(repo)
    canon = canon or locate(repo)
    tip = _sha(repo, f"refs/heads/{branch}")
    if not tip:
        raise SyncError("no_branch", f"{repo.name}: branch {branch} does not exist")
    onto = _onto(repo, canon)
    if not onto:
        raise SyncError("no_base", f"{canon.repo.name}: no {canon.base} branch")
    if _is_ancestor(repo, onto, tip):
        return tip
    if own_base and (not _sha(repo, own_base) or not _is_ancestor(repo, own_base, tip)):
        own_base = ""        # not this branch's history: fall back to a plain rebase
    _rebase_where_checked_out(repo, branch, onto, canon.base, own_base)
    return _sha(repo, f"refs/heads/{branch}")


def _same_store(repo: Path, canon: Canonical) -> bool:
    return _git_dir(repo, "--git-common-dir") == _git_dir(canon.repo, "--git-common-dir")


def is_clone(repo: Path | str, canon: Optional[Canonical] = None) -> bool:
    """True when `repo` is a separate clone of its canonical repo (a slot clone),
    False when it is the canonical checkout or one of its worktrees."""
    repo = Path(repo)
    return not _same_store(repo, canon or locate(repo))


def hold(repo: Path, branch: str, canon: Canonical) -> str:
    """Take `branch` into canonical as refs/landing/<branch>. Returns its SHA."""
    ref = f"{LANDING_REF}/{branch}"
    if _same_store(repo, canon):
        result = git(canon.repo, "update-ref", ref, f"refs/heads/{branch}")
    else:
        result = git(canon.repo, "fetch", "-q", str(repo), f"+refs/heads/{branch}:{ref}")
    held = _sha(canon.repo, ref)
    if result.returncode != 0 or not held:
        raise SyncError(
            "hold_failed",
            f"{canon.repo.name}: cannot take {branch} from {repo}: {result.stderr.strip()}")
    return held


def ahead_of_canonical(repo: Path | str, branch: str) -> int:
    """Commits on `branch` in `repo` that canonical's base branch, on disk, lacks.

    Read from canonical itself, never from a tracking ref, which can be stale.
    """
    repo = Path(repo)
    canon = locate(repo)
    if not _sha(repo, f"refs/heads/{branch}"):
        return 0
    onto = _onto(repo, canon)
    if not onto:
        return 0
    count = _out(repo, "rev-list", "--count", f"{onto}..refs/heads/{branch}")
    return int(count) if count.isdigit() else 0


def reference(repo: Path | str) -> tuple[str, str]:
    """What `repo`'s base branch is measured against: (ref, kind).

    A slot clone is measured against its canonical repo on disk
    ("local/<base>", "canonical"); the tracking ref is refreshed first, because
    a stale one reports commits that have in fact landed. A canonical repo is
    measured against its remote as last fetched ("<remote>/<base>", "remote").
    ("", "") when there is nothing to measure against.

    Being ahead means different things. A clone ahead of canonical holds work
    that has not landed. A canonical repo ahead of its remote holds landed work
    awaiting publish, which is a normal state, not a fault.
    """
    repo = Path(repo)
    try:
        canon = locate(repo)
    except SyncError:
        return "", ""
    if not _same_store(repo, canon):
        git(repo, "fetch", "-q", "local")
        ref = f"local/{canon.base}"
        return (ref, "canonical") if _sha(repo, f"refs/remotes/{ref}") else ("", "")
    if canon.blessed:
        ref = f"{canon.blessed}/{canon.base}"
        if _sha(canon.repo, f"refs/remotes/{ref}"):
            return ref, "remote"
    return "", ""


def unpublished(canon: Canonical) -> int:
    """Commits on canonical's base branch that the blessed remote, as last fetched, lacks."""
    if not canon.blessed:
        return 0
    remote_ref = f"refs/remotes/{canon.blessed}/{canon.base}"
    if not _sha(canon.repo, remote_ref):
        count = _out(canon.repo, "rev-list", "--count", f"refs/heads/{canon.base}")
    else:
        count = _out(canon.repo, "rev-list", "--count",
                     f"{remote_ref}..refs/heads/{canon.base}")
    return int(count) if count.isdigit() else 0


def mirror(canon: Canonical) -> str:
    """Push canonical's base branch to the mirror. Returns the remote, "none" or "failed"."""
    if not canon.mirror:
        return "none"
    result = git(canon.repo, "push", "-q", canon.mirror,
                 f"refs/heads/{canon.base}:refs/heads/{canon.base}", timeout=_NETWORK_TIMEOUT)
    return canon.mirror if result.returncode == 0 else "failed"


def _push_base(canon: Canonical) -> None:
    """Plain push of canonical's base branch to the blessed remote. Never forced."""
    result = git(canon.repo, "push", "-q", canon.blessed,
                 f"refs/heads/{canon.base}:refs/heads/{canon.base}", timeout=_NETWORK_TIMEOUT)
    if result.returncode == 0:
        return
    text = result.stderr.lower()
    if "non-fast-forward" in text or "fetch first" in text or "rejected" in text:
        raise SyncError(
            "remote_moved",
            f"{canon.repo.name}: {canon.blessed}/{canon.base} moved during publishing")
    raise SyncError(
        "publish_failed",
        f"{canon.repo.name}: push to {canon.blessed} failed: {result.stderr.strip()}")


def _stage_on_fork(canon: Canonical) -> str:
    """Push canonical's base branch to the fork as publish/<base>. A branch of our own
    on our own fork, so it may be overwritten when publishing rebases."""
    if not canon.mirror:
        return "none"
    target = f"{STAGING_BRANCH}/{canon.base}"
    result = git(canon.repo, "push", "-q", canon.mirror,
                 f"+refs/heads/{canon.base}:refs/heads/{target}", timeout=_NETWORK_TIMEOUT)
    return f"{canon.mirror}/{target}" if result.returncode == 0 else "failed"


def publish_base(repo: Path | str, lock_timeout: float = LOCK_TIMEOUT) -> PublishResult:
    """Publish canonical's base branch: fetch, settle, stage on the fork, push, mirror.

    The standalone step after one or more landings. The blessed remote is never
    force-pushed. A failure to reach the fork is a warning: the blessed remote
    is what counts.
    """
    canon = locate(repo)
    result = PublishResult(repo=canon.repo)
    with landing_lock(canon, lock_timeout):
        if not canon.blessed:
            result.sha = _sha(canon.repo, f"refs/heads/{canon.base}")
            result.warnings.append(f"{canon.repo.name}: no remote to publish to")
            return result
        for attempt in range(1, PUBLISH_ATTEMPTS + 1):
            result.rebased += settle_base(canon)
            result.pushed = unpublished(canon)
            result.staged = _stage_on_fork(canon)
            try:
                _push_base(canon)
                break
            except SyncError as error:
                if error.code != "remote_moved" or attempt == PUBLISH_ATTEMPTS:
                    raise
        result.published = canon.blessed
        result.sha = _sha(canon.repo, f"refs/heads/{canon.base}")
        if result.staged == "failed":
            result.warnings.append(
                f"{canon.repo.name}: push to {canon.mirror} failed; "
                f"{canon.blessed} has the work")
        result.mirrored = mirror(canon)
        if result.mirrored == "failed":
            result.warnings.append(
                f"{canon.repo.name}: {canon.mirror}/{canon.base} could not follow "
                f"{canon.blessed}/{canon.base}; it catches up on the next publish")
    return result


def _release(canon: Canonical, branch: str) -> None:
    git(canon.repo, "update-ref", "-d", f"{LANDING_REF}/{branch}")


def _follow_in_clone(repo: Path, canon: Canonical) -> None:
    """Best effort: a slot clone's own base branch and its `local/*` refs follow canonical.

    The tracking refs matter: a stale `local/main` makes every later
    "ahead of canonical" check report commits that have in fact landed.
    """
    if _same_store(repo, canon):
        return
    git(repo, "fetch", "-q", "local")
    checked_out = _worktree_of(repo, canon.base)
    if checked_out is not None:
        if git(repo, "fetch", "-q", str(canon.repo), f"refs/heads/{canon.base}").returncode == 0:
            git(checked_out, "merge", "--ff-only", "-q", "FETCH_HEAD")
    else:
        git(repo, "fetch", "-q", str(canon.repo),
            f"refs/heads/{canon.base}:refs/heads/{canon.base}")


def follow(repo: Path | str, canon: Optional[Canonical] = None) -> str:
    """Bring a slot clone's base branch up to canonical's, on disk. No network.

    Returns "current", "fast-forward", "ahead" when the clone's base branch holds
    commits canonical lacks (strays the next landing carries), "diverged" when
    each has commits the other lacks (left as it is), or "canonical" when `repo`
    is not a clone. The clone's local/* tracking refs are refreshed either way.
    """
    repo = Path(repo)
    canon = canon or locate(repo)
    if _same_store(repo, canon):
        return "canonical"
    git(repo, "fetch", "-q", "local")
    target = _onto(repo, canon)
    mine = _sha(repo, f"refs/heads/{canon.base}")
    if not target or mine == target:
        return "current"
    if mine and not _is_ancestor(repo, mine, target):
        return "ahead" if _is_ancestor(repo, target, mine) else "diverged"
    _follow_in_clone(repo, canon)
    return "fast-forward" if _sha(repo, f"refs/heads/{canon.base}") == target else "current"


# --- landing ---

def _prepare(repo: Path, branch: str, canon: Canonical, own_base: str = "") -> Optional[str]:
    """Rebase the branch onto canonical's base as it is on disk.

    Returns None when the branch has already landed. No remote is consulted:
    bringing canonical up to date with a remote is publishing's job.
    """
    blocked = _base_being_rebased(canon)
    if blocked:
        raise SyncError(
            "base_busy", f"{canon.repo.name}: {canon.base} is being rebased in {blocked}")
    tip = _sha(repo, f"refs/heads/{branch}")
    if not tip:
        raise SyncError("no_branch", f"{repo.name}: branch {branch} does not exist")
    base_in_repo = _onto(repo, canon)
    if base_in_repo and _is_ancestor(repo, tip, base_in_repo):
        return None
    return rebase(repo, branch, canon, own_base)


def land_all(work: list[tuple],
             lock_timeout: float = LOCK_TIMEOUT) -> list[LandResult]:
    """Land several branches in canonical, on disk. No network, no push.

    Each entry is (repo, branch) or (repo, branch, own_base); see `rebase` for
    `own_base`. Every branch is rebased before any base branch moves, because
    rebase is the only step that can conflict.
    """
    entries = [(Path(e[0]), e[1], e[2] if len(e) > 2 else "") for e in work]
    own_bases = {(str(repo), branch): own for repo, branch, own in entries}
    items = [(repo, branch, locate(repo)) for repo, branch, _ in entries]
    canonicals = {str(canon.repo.resolve()): canon for _, _, canon in items}
    with ExitStack() as stack:
        for key in sorted(canonicals):
            stack.enter_context(landing_lock(canonicals[key], lock_timeout))
        results: list[LandResult] = []
        ready = []
        for repo, branch, canon in items:
            result = LandResult(repo=repo, branch=branch)
            if _prepare(repo, branch, canon, own_bases[(str(repo), branch)]) is None:
                result.already_landed = True
            ready.append((repo, branch, canon, result))
        for repo, branch, canon, result in ready:
            if not result.already_landed:
                hold(repo, branch, canon)
                advance(canon, f"{LANDING_REF}/{branch}")
                _release(canon, branch)
                _follow_in_clone(repo, canon)
            result.sha = _sha(canon.repo, f"refs/heads/{canon.base}")
            result.unpublished = unpublished(canon)
            results.append(result)
        return results


def land(repo: Path | str, branch: str, lock_timeout: float = LOCK_TIMEOUT,
         own_base: str = "") -> LandResult:
    """Land one branch in canonical: rebase, hold, advance. No network, no push."""
    return land_all([(Path(repo), branch, own_base)], lock_timeout)[0]


# --- the other callers' needs ---

def refresh(repo: Path | str, branch: str) -> str:
    """Bring a working branch up to date with the published base. Replaces `pull --rebase`."""
    repo = Path(repo)
    canon = locate(repo)
    with landing_lock(canon):
        sync_base(canon)
    return rebase(repo, branch, canon)


def _backup_namespace(repo: Path) -> str:
    return repo.parent.name if (repo.parent / ".slot").exists() else repo.name


def backup(repo: Path | str, branch: str) -> str:
    """Keep a copy of a working branch in canonical. Replaces pushing from a slot.

    Returns the ref it was stored under. Works whatever state canonical is in,
    because the ref is not a branch.
    """
    repo = Path(repo)
    canon = locate(repo)
    ref = f"{BACKUP_REF}/{_backup_namespace(repo)}/{branch}"
    if _same_store(repo, canon):
        result = git(canon.repo, "update-ref", ref, f"refs/heads/{branch}")
    else:
        result = git(canon.repo, "fetch", "-q", str(repo), f"+refs/heads/{branch}:{ref}")
    if result.returncode != 0 or not _sha(canon.repo, ref):
        raise SyncError(
            "backup_failed",
            f"{canon.repo.name}: cannot back up {branch} from {repo}: {result.stderr.strip()}")
    return ref


BACKUP_FAILED_MARKER = "soredium-backup-failed"


def backup_remote(canon: Canonical) -> str:
    """The remote that receives off-machine copies of working branches, "" for none.

    `git config soredium.backupRemote <name>` in the canonical repo decides. By
    default it is the fork (the mirror): never a blessed remote other people
    share, so a repo with a single remote gets no off-machine copy until told to.
    """
    configured = _out(canon.repo, "config", "--get", "soredium.backupRemote")
    if configured:
        return configured if configured in _out(canon.repo, "remote").split() else ""
    return canon.mirror


def backup_offsite(canon: Canonical, ref: str) -> str:
    """Push one backup ref from canonical to the backup remote, under the same name.

    The ref is not a branch, so it does not show up as one. Returns the remote
    name, "none" when there is nowhere to send it; raises when the push fails.
    """
    remote = backup_remote(canon)
    if not remote:
        return "none"
    result = git(canon.repo, "push", "-q", remote, f"+{ref}:{ref}", timeout=60)
    if result.returncode != 0:
        raise SyncError(
            "backup_offsite_failed",
            f"{canon.repo.name}: backup of {ref} was not copied to {remote}: "
            f"{result.stderr.strip()}")
    return remote


def _backup_marker(repo: Path) -> Path:
    return _git_dir(repo) / BACKUP_FAILED_MARKER


def _run_backup(repo: Path, offsite: bool) -> int:
    """The post-commit hook's entry: back up the checked-out branch, hide nothing."""
    marker = _backup_marker(repo)
    branch = _out(repo, "symbolic-ref", "-q", "--short", "HEAD")
    if not branch:
        print("BACKUP_REF=none")
        return 0
    try:
        ref = backup(repo, branch)
        print(f"BACKUP_REF={ref}")
        where = backup_offsite(locate(repo), ref) if offsite else "skipped"
        print(f"BACKUP_OFFSITE={where}")
    except SyncError as error:
        if error.code == "backup_offsite_failed":
            print("BACKUP_OFFSITE=failed")
        else:
            print(f"ERROR={error.code}")
            print(f"ERROR_DETAIL={error.detail}")
        print(f"soredium: BACKUP FAILED for {repo.name}:{branch} - {error.detail}",
              file=sys.stderr)
        marker.write_text(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {branch}: {error.detail}\n")
        return 1
    if marker.exists():
        marker.unlink()
    return 0


# --- command line ---

def main(argv: Optional[list[str]] = None) -> int:
    """canonical_sync.py status <repo> | publish <repo> | backup <repo> [offsite=yes]"""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 2 or args[0] not in ("status", "publish", "backup"):
        print("usage: canonical_sync.py <status|publish|backup> <repo> [offsite=yes]",
              file=sys.stderr)
        return 2
    command, repo = args[0], Path(args[1])
    if command == "backup":
        return _run_backup(repo, "offsite=yes" in args[2:])
    try:
        canon = locate(repo)
        print(f"CANONICAL={canon.repo}")
        print(f"BASE={canon.base}")
        print(f"REMOTE={canon.blessed or 'none'}")
        print(f"MIRROR={canon.mirror or 'none'}")
        if command == "status":
            print(f"UNPUBLISHED={unpublished(canon)}")
            print(f"BACKUP_REMOTE={backup_remote(canon) or 'none'}")
            marker = _backup_marker(repo)
            if marker.exists():
                print(f"BACKUP_FAILED={marker.read_text().strip()}")
            return 0
        result = publish_base(repo)
        print(f"PUBLISHED={result.published}")
        print(f"PUSHED={result.pushed}")
        print(f"REBASED={result.rebased}")
        print(f"STAGED={result.staged}")
        print(f"MIRRORED={result.mirrored}")
        print(f"SHA={result.sha}")
        for warning in result.warnings:
            print(f"WARN={warning}")
        return 0
    except SyncError as error:
        print(f"ERROR={error.code}")
        print(f"ERROR_DETAIL={error.detail}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
