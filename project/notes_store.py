"""Branch-independent storage via a ``.notes/`` worktree on an orphan ``notes`` branch.

The notes store gives every workspace a directory whose contents are visible
regardless of which branch the main checkout is on.  It holds the queue file,
the pause stack, and anything else that must survive branch switches.

The orphan branch is created with git plumbing (mktree + commit-tree) so the
main checkout is never switched.  Each write is serialised with a lock file
and committed with a pathspec so only the named file lands in the commit.
"""

from __future__ import annotations

import fcntl
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


class NotesError(Exception):
    pass


def _run(args: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, **kwargs)


def _git(workspace: Path, *args: str, **kwargs) -> subprocess.CompletedProcess[str]:
    return _run(["git", "-C", str(workspace), *args], **kwargs)


class NotesStore:
    """Manages a ``.notes/`` worktree on an orphan ``notes`` branch."""

    _BRANCH = "notes"
    _WORKTREE_DIR = ".notes"
    _EXCLUDE_LINE = ".notes/"

    def __init__(self, workspace: Path):
        self._workspace = workspace.resolve()

    @property
    def path(self) -> Path:
        return self._workspace / self._WORKTREE_DIR

    @property
    def available(self) -> bool:
        if not self.path.is_dir():
            return False
        result = _git(self.path, "branch", "--show-current")
        return result.returncode == 0 and result.stdout.strip() == self._BRANCH

    def ensure(self) -> Path:
        if self.available:
            self._add_exclude()
            return self.path

        if self.path.exists():
            raise NotesError(
                f".notes exists at {self.path} but is not a worktree on "
                f"branch '{self._BRANCH}'; found: "
                + ("directory" if self.path.is_dir() else "file")
            )

        branch_exists = _git(
            self._workspace, "rev-parse", "--verify", f"refs/heads/{self._BRANCH}"
        ).returncode == 0

        if not branch_exists:
            self._create_orphan_branch()

        result = _git(
            self._workspace, "worktree", "add", self._WORKTREE_DIR, self._BRANCH
        )
        if result.returncode != 0:
            raise NotesError(
                f"failed to add worktree for branch '{self._BRANCH}': "
                + result.stderr.strip()
            )

        self._add_exclude()
        return self.path

    def read(self, filename: str) -> str | None:
        target = self.path / filename
        if not target.is_file():
            return None
        return target.read_text()

    def write(self, filename: str, content: str, what: str) -> None:
        if not self.available:
            raise NotesError("notes worktree not available; call ensure() first")

        git_dir = self._resolve_notes_git_dir()
        if git_dir is None:
            raise NotesError("cannot resolve git dir for notes worktree")

        lock_path = git_dir / "soredium-notes.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_fd = lock_path.open("w")
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)

            target = self.path / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(
                dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp"
            )
            os.close(fd)
            tmp_path = Path(tmp_name)
            try:
                tmp_path.write_text(content)
                tmp_path.replace(target)
            except BaseException:
                tmp_path.unlink(missing_ok=True)
                raise

            add_result = _git(self.path, "add", "--", filename)
            if add_result.returncode != 0:
                raise NotesError(
                    f"git add failed: {add_result.stderr.strip()}"
                )

            commit_result = _git(
                self.path, "commit",
                "-m", f"chore(queue): {what}",
                "-m", "no-issue: queue state",
                "--", filename,
            )
            if commit_result.returncode != 0:
                stderr = commit_result.stderr.strip()
                stdout = commit_result.stdout.strip()
                combined = f"{stdout}\n{stderr}".strip()
                unchanged = _git(self.path, "status", "--porcelain", "--", filename)
                if unchanged.returncode == 0 and not unchanged.stdout.strip():
                    return      # the file is committed as written: nothing changed

                raise NotesError(
                    f"git commit failed: {combined}"
                )
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()

    def _create_orphan_branch(self) -> None:
        tree = _git(self._workspace, "mktree", input="")
        if tree.returncode != 0:
            raise NotesError(f"mktree failed: {tree.stderr.strip()}")
        tree_sha = tree.stdout.strip()

        commit = _git(
            self._workspace, "commit-tree", tree_sha,
            "-m", "chore: initialize notes branch\n\nno-issue: infrastructure"
        )
        if commit.returncode != 0:
            raise NotesError(f"commit-tree failed: {commit.stderr.strip()}")
        commit_sha = commit.stdout.strip()

        result = _git(self._workspace, "branch", self._BRANCH, commit_sha)
        if result.returncode != 0:
            raise NotesError(f"branch creation failed: {result.stderr.strip()}")

    def _add_exclude(self) -> None:
        git_dir = self._resolve_workspace_git_dir()
        if git_dir is None:
            return
        exclude_file = git_dir / "info" / "exclude"
        exclude_file.parent.mkdir(parents=True, exist_ok=True)
        if exclude_file.is_file():
            content = exclude_file.read_text()
            if self._EXCLUDE_LINE in content.splitlines():
                return
            if not content.endswith("\n"):
                content += "\n"
            content += self._EXCLUDE_LINE + "\n"
            exclude_file.write_text(content)
        else:
            exclude_file.write_text(self._EXCLUDE_LINE + "\n")

    # -- Queue directory management --

    def ensure_queue_dir(self, slug: str) -> Path:
        """Create ``queue/<slug>/`` under ``.notes/``, returning its path.

        The directory is committed as a ``.gitkeep`` so it persists on the
        ``notes`` branch even when empty.
        """
        if not self.available:
            raise NotesError("notes worktree not available; call ensure() first")
        queue_path = self.path / "queue" / slug
        if queue_path.is_dir():
            return queue_path
        queue_path.mkdir(parents=True, exist_ok=True)
        gitkeep = queue_path / ".gitkeep"
        gitkeep.touch()
        self.write(f"queue/{slug}/.gitkeep", "", f"create queue dir {slug}")
        return queue_path

    def list_queue_dirs(self) -> list[str]:
        """List queue directory slugs under ``queue/``."""
        queue_root = self.path / "queue"
        if not queue_root.is_dir():
            return []
        return sorted(d.name for d in queue_root.iterdir() if d.is_dir())

    def queue_dir_path(self, slug: str) -> Path:
        """Path to ``queue/<slug>/``, whether it exists or not."""
        return self.path / "queue" / slug

    # -- Internal helpers --

    def _resolve_workspace_git_dir(self) -> Path | None:
        result = _git(self._workspace, "rev-parse", "--git-dir")
        if result.returncode != 0:
            return None
        git_dir = result.stdout.strip()
        p = Path(git_dir)
        if not p.is_absolute():
            p = self._workspace / p
        return p.resolve()

    def _resolve_notes_git_dir(self) -> Path | None:
        result = _git(self.path, "rev-parse", "--git-dir")
        if result.returncode != 0:
            return None
        git_dir = result.stdout.strip()
        p = Path(git_dir)
        if not p.is_absolute():
            p = self.path / p
        return p.resolve()
