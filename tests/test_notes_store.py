"""Tests for project/notes_store.py — pins the store contract from Hortora/soredium#567."""

from __future__ import annotations

import multiprocessing
import subprocess
from pathlib import Path

import pytest

from notes_store import NotesStore, NotesError


def _git(repo: Path, *args: str, **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, **kwargs,
    )


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    _git(ws, "init", "-b", "main")
    _git(ws, "config", "user.email", "test@test.com")
    _git(ws, "config", "user.name", "Test")
    _git(ws, "commit", "--allow-empty", "-m", "init")
    return ws


# ---------------------------------------------------------------------------
# ensure()
# ---------------------------------------------------------------------------


class TestEnsure:
    def test_creates_notes_worktree(self, workspace):
        store = NotesStore(workspace)
        path = store.ensure()

        assert path == workspace / ".notes"
        assert path.is_dir()
        assert store.available
        branch = _git(path, "branch", "--show-current").stdout.strip()
        assert branch == "notes"

    def test_idempotent(self, workspace):
        """ensure() twice: second call changes nothing."""
        store = NotesStore(workspace)
        p1 = store.ensure()

        sha1 = _git(workspace / ".notes", "rev-parse", "HEAD").stdout.strip()
        p2 = store.ensure()
        sha2 = _git(workspace / ".notes", "rev-parse", "HEAD").stdout.strip()

        assert p1 == p2
        assert sha1 == sha2
        assert store.available

    def test_plain_notes_directory_raises_and_is_untouched(self, workspace):
        """ensure() with a plain .notes directory holding NOTES.md: raises,
        directory and file untouched."""
        notes_dir = workspace / ".notes"
        notes_dir.mkdir()
        notes_file = notes_dir / "NOTES.md"
        notes_file.write_text("my important notes\n")

        store = NotesStore(workspace)
        with pytest.raises(NotesError, match="not a worktree"):
            store.ensure()

        assert notes_dir.is_dir()
        assert notes_file.read_text() == "my important notes\n"

    def test_existing_worktree_with_notes_md_used_as_is(self, workspace):
        """ensure() when .notes worktree already exists with NOTES.md
        (created by git worktree add --orphan): used as is, NOTES.md untouched."""
        result = _git(workspace, "worktree", "add", "--orphan", "-b", "notes", ".notes")
        assert result.returncode == 0, result.stderr
        notes_file = workspace / ".notes" / "NOTES.md"
        notes_file.write_text("existing notes\n")
        _git(workspace / ".notes", "add", "NOTES.md")
        _git(workspace / ".notes", "commit", "-m", "add NOTES.md")

        store = NotesStore(workspace)
        path = store.ensure()

        assert path == workspace / ".notes"
        assert store.available
        assert notes_file.read_text() == "existing notes\n"

    def test_existing_branch_without_worktree(self, workspace):
        """If a notes branch exists but no worktree, ensure() attaches to it."""
        store = NotesStore(workspace)
        tree = _git(workspace, "mktree", input="").stdout.strip()
        commit = _git(workspace, "commit-tree", tree, "-m", "pre-existing").stdout.strip()
        _git(workspace, "branch", "notes", commit)

        path = store.ensure()
        assert store.available
        log = _git(path, "log", "--oneline").stdout.strip()
        assert "pre-existing" in log

    def test_exclude_from_git_status(self, workspace):
        store = NotesStore(workspace)
        store.ensure()

        status = _git(workspace, "status", "--porcelain").stdout
        assert ".notes" not in status

    def test_branch_exists_but_worktree_add_fails(self, workspace):
        """If the branch exists but the worktree cannot be added, raises NotesError."""
        store = NotesStore(workspace)
        store.ensure()
        # Now remove the worktree registration but leave .notes dir so it conflicts
        _git(workspace, "worktree", "remove", "--force", ".notes")
        (workspace / ".notes").mkdir()
        (workspace / ".notes" / "blocker.txt").write_text("blocking")

        store2 = NotesStore(workspace)
        with pytest.raises(NotesError):
            store2.ensure()


# ---------------------------------------------------------------------------
# write()
# ---------------------------------------------------------------------------


class TestWrite:
    def test_write_and_read(self, workspace):
        store = NotesStore(workspace)
        store.ensure()

        store.write(".queue", "item1\nitem2\n", "add queue")
        result = store.read(".queue")
        assert result == "item1\nitem2\n"

    def test_write_commits_on_notes_branch(self, workspace):
        store = NotesStore(workspace)
        store.ensure()

        store.write(".queue", "v1", "first write")
        store.write(".queue", "v2", "second write")

        log = _git(store.path, "log", "--oneline").stdout.strip()
        lines = log.splitlines()
        assert len(lines) >= 2
        assert "second write" in lines[0]
        assert "first write" in lines[1]

    def test_commit_message_format(self, workspace):
        store = NotesStore(workspace)
        store.ensure()

        store.write(".queue", "content", "update queue")

        log = _git(store.path, "log", "-1", "--format=%B").stdout.strip()
        assert "chore(queue): update queue" in log
        assert "no-issue: queue state" in log

    def test_commits_only_the_named_file(self, workspace):
        """write() commits only the named file when another file is staged."""
        store = NotesStore(workspace)
        store.ensure()

        other = store.path / "other.txt"
        other.write_text("staged but not committed\n")
        _git(store.path, "add", "other.txt")

        store.write(".queue", "queue content\n", "update queue")

        show = _git(store.path, "show", "--name-only", "--format=", "HEAD").stdout.strip()
        assert show == ".queue"

        status = _git(store.path, "status", "--porcelain").stdout.strip()
        assert "other.txt" in status

    def test_nothing_to_commit_is_success(self, workspace):
        store = NotesStore(workspace)
        store.ensure()

        store.write(".queue", "same\n", "first")
        store.write(".queue", "same\n", "second")

    def test_hook_that_accepts_no_issue_succeeds(self, workspace):
        """write() with a commit-msg hook that rejects messages lacking
        'no-issue' or an issue reference: succeeds because our messages
        include 'no-issue: queue state'."""
        store = NotesStore(workspace)
        store.ensure()

        common_dir = _git(store.path, "rev-parse", "--git-common-dir").stdout.strip()
        common = Path(common_dir)
        if not common.is_absolute():
            common = store.path / common
        hooks_dir = common / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        hook = hooks_dir / "commit-msg"
        hook.write_text(
            "#!/bin/sh\n"
            "if grep -q 'no-issue' \"$1\" || grep -qE '#[0-9]+' \"$1\"; then\n"
            "  exit 0\n"
            "fi\n"
            "echo 'REJECTED: missing issue reference or no-issue marker' >&2\n"
            "exit 1\n"
        )
        hook.chmod(0o755)

        store.write(".queue", "queue data\n", "update queue")
        assert store.read(".queue") == "queue data\n"

    def test_hook_that_always_rejects_raises_but_file_has_new_content(self, workspace):
        """write() with a hook that always rejects: raises NotesError,
        file content is the new content."""
        store = NotesStore(workspace)
        store.ensure()

        common_dir = _git(store.path, "rev-parse", "--git-common-dir").stdout.strip()
        common = Path(common_dir)
        if not common.is_absolute():
            common = store.path / common
        hooks_dir = common / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        hook = hooks_dir / "commit-msg"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)

        with pytest.raises(NotesError, match="git commit failed"):
            store.write(".queue", "new content\n", "update queue")

        assert (store.path / ".queue").read_text() == "new content\n"

    def test_write_raises_before_ensure(self, workspace):
        store = NotesStore(workspace)
        with pytest.raises(NotesError, match="not available"):
            store.write(".queue", "data", "msg")

    def test_read_nonexistent_returns_none(self, workspace):
        store = NotesStore(workspace)
        store.ensure()
        assert store.read("nonexistent.md") is None


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


def _writer_process(workspace_path: str, writer_id: int) -> None:
    ws = Path(workspace_path)
    store = NotesStore(ws)
    store.write(f"file-{writer_id}.txt", f"content from writer {writer_id}\n",
                f"writer {writer_id}")


class TestConcurrency:
    def test_two_processes_writing_at_once(self, workspace):
        """two processes writing at once: both commits exist, neither is lost."""
        store = NotesStore(workspace)
        store.ensure()

        p1 = multiprocessing.Process(target=_writer_process, args=(str(workspace), 1))
        p2 = multiprocessing.Process(target=_writer_process, args=(str(workspace), 2))
        p1.start()
        p2.start()
        p1.join(timeout=30)
        p2.join(timeout=30)
        assert p1.exitcode == 0, "Writer 1 failed"
        assert p2.exitcode == 0, "Writer 2 failed"

        assert (store.path / "file-1.txt").read_text() == "content from writer 1\n"
        assert (store.path / "file-2.txt").read_text() == "content from writer 2\n"

        log = _git(store.path, "log", "--oneline").stdout.strip()
        assert "writer 1" in log
        assert "writer 2" in log


# ---------------------------------------------------------------------------
# Branch isolation
# ---------------------------------------------------------------------------


class TestBranchIsolation:
    def test_queue_survives_branch_switch(self, workspace):
        """queue written on branch A is read unchanged after checking out
        branch B in the workspace."""
        store = NotesStore(workspace)
        store.ensure()
        store.write(".queue", "queue on main\n", "add queue")

        _git(workspace, "checkout", "-b", "feature-x")
        (workspace / "feature.txt").write_text("feature work")
        _git(workspace, "add", "feature.txt")
        _git(workspace, "commit", "-m", "feature commit")

        assert store.available
        assert store.read(".queue") == "queue on main\n"

        _git(workspace, "checkout", "main")
        assert store.available
        assert store.read(".queue") == "queue on main\n"


# ---------------------------------------------------------------------------
# Source audit
# ---------------------------------------------------------------------------


class TestSourceAudit:
    def test_no_remote_operations_in_source(self):
        """no test or code path runs git push, fetch, pull, reset or merge."""
        import inspect
        import notes_store
        source = inspect.getsource(notes_store)
        for forbidden in ["push", "fetch", "pull", "reset", "merge"]:
            lines_with = [
                line.strip() for line in source.splitlines()
                if forbidden in line.lower()
                and not line.strip().startswith("#")
                and not line.strip().startswith('"""')
                and not line.strip().startswith("'")
                and "forbidden" not in line
                and "for forbidden" not in line
            ]
            assert not lines_with, (
                f"Found '{forbidden}' in notes_store.py source: {lines_with}"
            )


class TestReviewFindings:
    """Found by review of the first version (Hortora/soredium#577)."""

    def test_an_unchanged_write_succeeds_when_another_file_is_untracked(self, workspace):
        from notes_store import NotesStore
        store = NotesStore(workspace)
        store.ensure()
        store.write(".queue", "one\n", "first")
        (store.path / ".pause-stack").write_text("untracked\n")
        store.write(".queue", "one\n", "same content again")
        assert store.read(".queue") == "one\n"
        assert (store.path / ".pause-stack").read_text() == "untracked\n"

    def test_writing_does_not_leak_file_descriptors(self, workspace):
        import os
        from notes_store import NotesStore
        store = NotesStore(workspace)
        store.ensure()
        store.write(".queue", "0\n", "warm up")
        before = len(os.listdir("/dev/fd"))
        for n in range(1, 12):
            store.write(".queue", f"{n}\n", "again")
        assert len(os.listdir("/dev/fd")) <= before + 1
