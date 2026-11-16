"""Every base-branch change and every push goes through here (#515).

Rules this module enforces:

  1. Linear history: a base branch only ever fast-forwards.
  2. Canonical is the sync point: work reaches the canonical repo first.
  3. Only canonical publishes: nothing is pushed to a remote from a slot clone.

Landing and publishing are separate. Landing puts a branch on canonical's base
branch, on disk, and pushes nothing:

  sync     canonical base fast-forwards from the blessed remote (stop if diverged)
  rebase   the branch is rebased onto canonical base, where it is checked out or
           in a temporary worktree; canonical's own checkout is never switched
  hold     canonical takes the branch into refs/landing/<branch>
  advance  canonical's base branch fast-forwards to the held ref

Publishing (`publish_base`, or `canonical_sync.py publish <repo>`) is a step of
its own: canonical's base branch is pushed to the blessed remote with a plain
push, then to the mirror. Between the two, canonical is ahead of the remote.

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
    published: str = "none"     # blessed remote name, or "none" when the repo has no remote
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


def locate(repo: Path | str) -> Canonical:
    """Find the canonical repo behind `repo` and where it publishes.

    A slot clone names its canonical repo with a `local` remote. Anything else
    (a canonical checkout, or one of its linked worktrees) is canonical itself.
    """
    repo = Path(repo)
    canonical = repo
    url = _out(repo, "remote", "get-url", "local")
    if url and Path(url).is_dir():
        canonical = Path(url).resolve()
    else:
        common = _git_dir(repo, "--git-common-dir")
        if common.name == ".git":
            canonical = common.parent
    remotes = _out(canonical, "remote").split()
    if "upstream" in remotes:
        blessed, mirror = "upstream", ("origin" if "origin" in remotes else "")
    elif "origin" in remotes:
        blessed, mirror = "origin", ""
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


def sync_base(canon: Canonical) -> str:
    """Bring canonical's base branch up to the blessed remote. Returns base's SHA.

    Canonical ahead of the remote is fine: those commits are published with the
    next landing. Canonical and the remote each holding commits the other lacks
    is a divergence, and nothing is changed.
    """
    local_ref = f"refs/heads/{canon.base}"
    if not canon.blessed:
        return _sha(canon.repo, local_ref)
    fetched = git(canon.repo, "fetch", "-q", canon.blessed, canon.base,
                  timeout=_NETWORK_TIMEOUT)
    remote_ref = f"refs/remotes/{canon.blessed}/{canon.base}"
    remote = _sha(canon.repo, remote_ref)
    if fetched.returncode != 0:
        if "couldn't find remote ref" in fetched.stderr.lower():
            return _sha(canon.repo, local_ref)     # the remote has no base branch yet
        raise SyncError(
            "fetch_failed",
            f"{canon.repo.name}: cannot fetch {canon.base} from {canon.blessed}: "
            f"{fetched.stderr.strip()}")
    local = _sha(canon.repo, local_ref)
    if not remote or remote == local or (local and _is_ancestor(canon.repo, remote, local)):
        return local
    if local and not _is_ancestor(canon.repo, local, remote):
        raise SyncError(
            "diverged",
            f"{canon.repo.name}: local {canon.base} and {canon.blessed}/{canon.base} "
            f"have diverged; resolve it by hand, landing cannot")
    advance(canon, remote_ref)
    return remote


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


def rebase(repo: Path | str, branch: str, canon: Optional[Canonical] = None) -> str:
    """Rebase `branch` onto canonical's base branch. Returns the new tip.

    Runs where the branch is checked out; otherwise in a temporary worktree, so
    no existing checkout is switched. A conflict aborts the rebase this call
    started and leaves the branch exactly as it was.
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
    with checked_out(repo, branch) as worktree:
        result = git(worktree, "rebase", "-q", onto, timeout=_NETWORK_TIMEOUT)
        if result.returncode != 0:
            if _rebase_in_progress(worktree) is not None:
                files = _conflicted(worktree)
                git(worktree, "rebase", "--abort")      # the rebase this call started
                raise SyncError(
                    "rebase_conflict",
                    f"{repo.name}: {branch} conflicts with {canon.base} in "
                    f"{', '.join(files) or 'unknown files'}")
            raise SyncError(
                "rebase_refused",
                f"{repo.name}: {branch} could not be rebased: "
                f"{(result.stderr or result.stdout).strip()}")
    return _sha(repo, f"refs/heads/{branch}")


def _same_store(repo: Path, canon: Canonical) -> bool:
    return _git_dir(repo, "--git-common-dir") == _git_dir(canon.repo, "--git-common-dir")


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


def publish_base(repo: Path | str, lock_timeout: float = LOCK_TIMEOUT) -> PublishResult:
    """Publish canonical's base branch: the standalone step after one or more landings.

    Syncs first, so a remote that moved is fast-forwarded in when canonical has
    nothing of its own, and reported as `diverged` when it has. Nothing is ever
    forced. A mirror failure is a warning: the blessed remote is what counts.
    """
    canon = locate(repo)
    result = PublishResult(repo=canon.repo)
    with landing_lock(canon, lock_timeout):
        if not canon.blessed:
            result.sha = _sha(canon.repo, f"refs/heads/{canon.base}")
            result.warnings.append(f"{canon.repo.name}: no remote to publish to")
            return result
        for attempt in range(1, PUBLISH_ATTEMPTS + 1):
            sync_base(canon)
            result.pushed = unpublished(canon)
            try:
                _push_base(canon)
                break
            except SyncError as error:
                if error.code != "remote_moved" or attempt == PUBLISH_ATTEMPTS:
                    raise
        result.published = canon.blessed
        result.sha = _sha(canon.repo, f"refs/heads/{canon.base}")
        result.mirrored = mirror(canon)
        if result.mirrored == "failed":
            result.warnings.append(
                f"{canon.repo.name}: push to mirror {canon.mirror} failed; "
                f"it catches up on the next publish")
    return result


def _release(canon: Canonical, branch: str) -> None:
    git(canon.repo, "update-ref", "-d", f"{LANDING_REF}/{branch}")


def _follow_in_clone(repo: Path, canon: Canonical) -> None:
    """Best effort: a slot clone's own base branch follows canonical's."""
    if _same_store(repo, canon):
        return
    checked_out = _worktree_of(repo, canon.base)
    if checked_out is not None:
        if git(repo, "fetch", "-q", str(canon.repo), f"refs/heads/{canon.base}").returncode == 0:
            git(checked_out, "merge", "--ff-only", "-q", "FETCH_HEAD")
    else:
        git(repo, "fetch", "-q", str(canon.repo),
            f"refs/heads/{canon.base}:refs/heads/{canon.base}")


# --- landing ---

def _prepare(repo: Path, branch: str, canon: Canonical, offline: bool,
             warnings: list[str]) -> Optional[str]:
    """Sync canonical and rebase the branch. Returns None when it has already landed."""
    blocked = _base_being_rebased(canon)
    if blocked:
        raise SyncError(
            "base_busy", f"{canon.repo.name}: {canon.base} is being rebased in {blocked}")
    try:
        sync_base(canon)
    except SyncError as error:
        if error.code != "fetch_failed" or not offline:
            raise
        warnings.append(
            f"{canon.repo.name}: {canon.blessed} was not checked (offline); if it has moved, "
            f"publishing will report a divergence")
    tip = _sha(repo, f"refs/heads/{branch}")
    if not tip:
        raise SyncError("no_branch", f"{repo.name}: branch {branch} does not exist")
    base_in_repo = _onto(repo, canon)
    if base_in_repo and _is_ancestor(repo, tip, base_in_repo):
        return None
    return rebase(repo, branch, canon)


def land_all(work: list[tuple[Path, str]], lock_timeout: float = LOCK_TIMEOUT,
             offline: bool = False) -> list[LandResult]:
    """Land several (repo, branch) pairs in canonical, on disk. Nothing is pushed.

    Every branch is rebased before any base branch moves, because rebase is the
    only step that can conflict. `offline` lands without checking the remote.
    """
    items = [(Path(repo), branch, locate(repo)) for repo, branch in work]
    canonicals = {str(canon.repo.resolve()): canon for _, _, canon in items}
    with ExitStack() as stack:
        for key in sorted(canonicals):
            stack.enter_context(landing_lock(canonicals[key], lock_timeout))
        results: list[LandResult] = []
        ready = []
        for repo, branch, canon in items:
            result = LandResult(repo=repo, branch=branch)
            if _prepare(repo, branch, canon, offline, result.warnings) is None:
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
         offline: bool = False) -> LandResult:
    """Land one branch in canonical: sync, rebase, hold, advance. Nothing is pushed."""
    return land_all([(Path(repo), branch)], lock_timeout, offline)[0]


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


# --- command line ---

def main(argv: Optional[list[str]] = None) -> int:
    """canonical_sync.py status <repo> | publish <repo>"""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2 or args[0] not in ("status", "publish"):
        print("usage: canonical_sync.py <status|publish> <repo>", file=sys.stderr)
        return 2
    command, repo = args[0], Path(args[1])
    try:
        canon = locate(repo)
        print(f"CANONICAL={canon.repo}")
        print(f"BASE={canon.base}")
        print(f"REMOTE={canon.blessed or 'none'}")
        print(f"MIRROR={canon.mirror or 'none'}")
        if command == "status":
            print(f"UNPUBLISHED={unpublished(canon)}")
            return 0
        result = publish_base(repo)
        print(f"PUBLISHED={result.published}")
        print(f"PUSHED={result.pushed}")
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
