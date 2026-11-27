"""Tests for commit_pipeline_files and its integration with the close ceremony.

A workspace clone whose only dirty tracked files are pipeline state files
(.work-progress, .wrap-log.jsonl, etc.) must land cleanly: the ceremony
commits them before rebasing. Non-pipeline dirty files must NOT be committed
by the helper. In a root-queue slot, inherited .queue files are not committed.

Refs Hortora/soredium#587
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "work-end"))
sys.path.insert(0, str(Path(__file__).parent.parent / "project"))
sys.path.insert(0, str(Path(__file__).parent.parent / "work-slot"))

from queue_io import write_queue, Queue, QueueItem, QueueState
from close import close, commit_pipeline_files, render
import squash_marker
import branch_base


# --- helpers ---

def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=True,
    )


def _git_nc(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True,
    )


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-b", "main", "--template=")
    (path / ".git" / "hooks").mkdir(exist_ok=True)
    _git(path, "commit", "--allow-empty", "-m", "init")
    return path


def _on_branch(repo: Path) -> str:
    return _git(repo, "branch", "--show-current").stdout.strip()


def _is_clean(repo: Path) -> bool:
    r = _git_nc(repo, "status", "--porcelain")
    return r.stdout.strip() == ""


def _main_head(repo: Path) -> str:
    return _git(repo, "rev-parse", "main").stdout.strip()


def _dirty_pipeline_files(repo: Path) -> None:
    for name in [".work-progress", ".wrap-log.jsonl"]:
        (repo / name).write_text(f'{{"step": "initial"}}')
        _git(repo, "add", "--", name)
    _git(repo, "commit", "-m", "chore: initial pipeline files Refs #1")
    for name in [".work-progress", ".wrap-log.jsonl"]:
        (repo / name).write_text(f'{{"step": "modified"}}')


# --- Unit tests for commit_pipeline_files ---

class TestCommitPipelineFiles:

    def test_commits_tracked_pipeline_files(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _git(repo, "checkout", "-b", "feat")
        (repo / ".work-progress").write_text("modified")
        _git(repo, "add", ".work-progress")
        _git(repo, "commit", "-m", "add .work-progress")
        (repo / ".work-progress").write_text("changed again")

        committed = commit_pipeline_files(repo, "1")
        assert ".work-progress" in committed
        assert _is_clean(repo)

    def test_ignores_untracked_pipeline_files(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _git(repo, "checkout", "-b", "feat")
        (repo / ".work-progress").write_text("new and untracked")

        committed = commit_pipeline_files(repo, "1")
        assert committed == []

    def test_ignores_non_pipeline_files(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _git(repo, "checkout", "-b", "feat")
        (repo / "real-work.txt").write_text("important code")
        _git(repo, "add", "real-work.txt")
        _git(repo, "commit", "-m", "add tracked file")
        (repo / "real-work.txt").write_text("modified code")

        committed = commit_pipeline_files(repo, "1")
        assert committed == []
        assert (repo / "real-work.txt").read_text() == "modified code"

    def test_skips_inherited_queue_in_root_queue_slot(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        (slot_dir / ".queue-root").touch()
        (slot_dir / ".slot").write_text("# Slot\n")
        repo = _init_repo(slot_dir / "wsp")

        _git(repo, "checkout", "-b", "feat")
        (repo / ".queue").write_text("inherited queue content")
        _git(repo, "add", ".queue")
        _git(repo, "commit", "-m", "add .queue")
        original_content = "modified inherited"
        (repo / ".queue").write_text(original_content)

        committed = commit_pipeline_files(repo, "1")
        assert ".queue" not in committed
        assert (repo / ".queue").read_text() == original_content

    def test_returns_empty_when_nothing_dirty(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        committed = commit_pipeline_files(repo, "1")
        assert committed == []


# --- Permanent clone fixture ---

@pytest.fixture
def clone_world(tmp_path):
    """Family with canonical P and W, permanent clone, workspace has pipeline files dirty."""
    family = tmp_path / "family"
    family.mkdir()
    (family / "slots").mkdir()

    canonical_p = _init_repo(family / "P")
    (canonical_p / "src.txt").write_text("source\n")
    _git(canonical_p, "add", ".")
    _git(canonical_p, "commit", "-m", "add source")

    canonical_w = _init_repo(family / "W")
    proj_link = canonical_w / "proj"
    proj_link.symlink_to(os.path.relpath(canonical_p, canonical_w))
    write_queue(canonical_w, Queue(
        items=[QueueItem(ref="R#1", title="Task", completed=False, active=True)],
        state=QueueState(branch="", issue_repo="R", status="active"),
    ))
    _git(canonical_w, "add", ".")
    _git(canonical_w, "commit", "-m", "workspace init with queue")

    wksp_link = canonical_p / "wksp"
    wksp_link.symlink_to(os.path.relpath(canonical_w, canonical_p))
    _git(canonical_p, "add", ".")
    _git(canonical_p, "commit", "-m", "add wksp symlink")

    from clone_manager import create_clone
    result = create_clone(family, "P")
    assert result["CREATED"] == "yes"

    clone_target = family / "clone" / "P"
    project_clone = clone_target / "P"
    ws_dirs = [d for d in clone_target.iterdir()
               if d.is_dir() and d.name != "P"
               and (d / ".git").exists()
               and (d / ".workspace").exists()]
    assert ws_dirs
    ws_clone = ws_dirs[0]

    branch = "issue-1-feat"

    main_sha_p = _main_head(project_clone)
    _git(project_clone, "checkout", "-b", branch)
    branch_base.record(project_clone, branch, main_sha_p)
    (project_clone / "feature.txt").write_text("new feature\n")
    _git(project_clone, "add", ".")
    _git(project_clone, "commit", "-m", "feat: add feature Refs #1")
    squash_marker.mark(project_clone, branch)

    main_sha_w = _main_head(ws_clone)
    _git(ws_clone, "checkout", "-b", branch)
    branch_base.record(ws_clone, branch, main_sha_w)
    (ws_clone / "notes.md").write_text("work notes\n")
    _git(ws_clone, "add", ".")
    _git(ws_clone, "commit", "-m", "docs: work notes Refs #1")
    squash_marker.mark(ws_clone, branch)

    from queue_io import queue_dir
    qdir = queue_dir(ws_clone)
    write_queue(ws_clone, Queue(
        items=[QueueItem(ref="R#1", title="Task", completed=False, active=True)],
        state=QueueState(branch=branch, issue_repo="R", status="active"),
    ))
    qfile = qdir / ".queue"
    if qfile.exists() and (qdir / ".git").exists():
        r = _git_nc(qdir, "add", ".queue")
        if r.returncode == 0:
            r2 = _git_nc(qdir, "diff", "--cached", "--quiet")
            if r2.returncode != 0:
                _git(qdir, "commit", "-m", "chore: set queue branch Refs #1")

    return family, canonical_p, canonical_w, clone_target, project_clone, ws_clone, branch


# --- Integration tests with permanent clone ---

class TestCeremonyWithPipelineFiles:

    def test_workspace_with_pipeline_files_lands_cleanly(self, clone_world):
        """The main test: workspace with pipeline files dirty lands and settles."""
        family, canonical_p, canonical_w, clone_target, project_clone, ws_clone, branch = clone_world

        # Advance canonical so the rebase is not a no-op — this is what
        # happens in practice when the project branch lands first.
        (canonical_w / "extra.txt").write_text("canonical moved\n")
        _git(canonical_w, "add", ".")
        _git(canonical_w, "commit", "-m", "canonical advances")

        _dirty_pipeline_files(ws_clone)

        result = close(ws_clone)

        assert result.success, f"ceremony failed: {result.errors}"
        assert not result.not_landed, f"not landed: {result.not_landed}"
        # Workspace is not settled in the new model — it stays on its branch
        assert _on_branch(ws_clone) == branch

    def test_non_pipeline_dirty_file_not_committed(self, clone_world):
        """Non-pipeline tracked files must not be committed by the helper."""
        family, canonical_p, canonical_w, clone_target, project_clone, ws_clone, branch = clone_world

        (ws_clone / "real-work.txt").write_text("important")
        _git(ws_clone, "add", "real-work.txt")
        _git(ws_clone, "commit", "-m", "add real-work Refs #1")
        (ws_clone / "real-work.txt").write_text("modified in progress")

        result = close(ws_clone)

        log = _git_nc(ws_clone, "log", "--oneline", "--all", "--grep=pipeline state")
        assert "pipeline state" not in log.stdout
        assert (ws_clone / "real-work.txt").read_text() == "modified in progress"

    def test_inherited_queue_not_committed_in_root_queue_clone(self, clone_world):
        """In a clone with .queue-root, inherited .queue is not committed."""
        family, canonical_p, canonical_w, clone_target, project_clone, ws_clone, branch = clone_world

        (clone_target / ".queue-root").touch()

        (ws_clone / ".queue").write_text("inherited queue")
        _git(ws_clone, "add", ".queue")
        _git(ws_clone, "commit", "-m", "add inherited .queue Refs #1")
        original = "modified inherited"
        (ws_clone / ".queue").write_text(original)

        _dirty_pipeline_files(ws_clone)

        result = close(ws_clone)

        assert result.success
        log = _git_nc(ws_clone, "log", "--oneline", "--all", "--", ".queue")
        assert "pipeline state" not in log.stdout

    def test_not_landed_causes_attention(self, clone_world):
        """A ceremony with not_landed items produces ATTENTION= in render output."""
        from close import CloseResult
        result = CloseResult(success=True, not_landed={"ws:branch": "rebase failed"})
        lines = render(result)
        assert any("ATTENTION=" in l for l in lines)
        assert any("NOT_LANDED=" in l for l in lines)


class TestScopeLand:

    def test_scope_land_exits_1_on_not_landed(self, clone_world):
        """scope.land() returns exit 1 when the ceremony has not_landed items."""
        from unittest.mock import patch
        from close import CloseResult
        from scope import land

        family, canonical_p, canonical_w, clone_target, project_clone, ws_clone, branch = clone_world

        mock_result = CloseResult(
            success=True,
            not_landed={"ws:branch": "could not be rebased: unstaged changes"},
        )
        with patch("scope.ceremony") as mock_ceremony:
            mock_ceremony.close.return_value = mock_result
            mock_ceremony.render.return_value = render(mock_result)
            exit_code, lines = land(ws_clone)

        assert exit_code == 1
        assert any("not_landed" in l.lower() for l in lines)
