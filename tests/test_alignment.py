"""Tests for project/alignment.py — one real git repo per state, no mocks."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "project"))

from alignment import Alignment, detect
from branch_base import record as bb_record, base_of
from queue_io import write_queue, Queue, QueueItem, QueueState


GIT_ENV = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@test",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@test",
}


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, **GIT_ENV}
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, env=env,
    )


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-b", "main")
    _git(path, "commit", "--allow-empty", "-m", "init")
    return path


def _snapshot(repo: Path) -> tuple[str, str, str]:
    """Capture state: porcelain, HEAD sha, all refs."""
    porcelain = _git(repo, "status", "--porcelain").stdout
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    refs = _git(repo, "for-each-ref").stdout
    return porcelain, head, refs


@pytest.fixture
def repos(tmp_path):
    project = _init_repo(tmp_path / "project")
    workspace = _init_repo(tmp_path / "workspace")
    return project, workspace


class TestOnBase:
    def test_both_on_main(self, repos):
        project, workspace = repos
        result = detect(project, workspace)
        assert result.state == "on_base"
        assert result.project_branch == "main"
        assert result.workspace_branch == "main"


class TestAligned:
    def test_same_branch_base_recorded(self, repos):
        project, workspace = repos
        base_sha = _git(project, "rev-parse", "HEAD").stdout.strip()
        _git(project, "checkout", "-b", "feature-x")
        _git(project, "commit", "--allow-empty", "-m", "work")
        bb_record(project, "feature-x", base_sha)
        _git(workspace, "checkout", "-b", "feature-x")
        bb_record(workspace, "feature-x", _git(workspace, "rev-parse", "main").stdout.strip())
        result = detect(project, workspace)
        assert result.state == "aligned"
        assert result.project_branch == "feature-x"
        assert result.workspace_branch == "feature-x"

    def test_aligned_with_matching_queue(self, repos):
        project, workspace = repos
        base_sha = _git(project, "rev-parse", "HEAD").stdout.strip()
        _git(project, "checkout", "-b", "feature-x")
        _git(project, "commit", "--allow-empty", "-m", "work")
        bb_record(project, "feature-x", base_sha)
        _git(workspace, "checkout", "-b", "feature-x")
        bb_record(workspace, "feature-x", _git(workspace, "rev-parse", "main").stdout.strip())
        q = Queue(
            items=[QueueItem(ref="#1", title="t", completed=False, active=True)],
            state=QueueState(branch="feature-x", status="active"),
        )
        write_queue(workspace, q)
        _git(workspace, "add", ".queue")
        _git(workspace, "commit", "-m", "queue")
        result = detect(project, workspace)
        assert result.state == "aligned"
        assert result.queue_branch == "feature-x"

    def test_aligned_with_empty_queue_branch(self, repos):
        project, workspace = repos
        base_sha = _git(project, "rev-parse", "HEAD").stdout.strip()
        _git(project, "checkout", "-b", "feature-x")
        _git(project, "commit", "--allow-empty", "-m", "work")
        bb_record(project, "feature-x", base_sha)
        _git(workspace, "checkout", "-b", "feature-x")
        bb_record(workspace, "feature-x", _git(workspace, "rev-parse", "main").stdout.strip())
        q = Queue(
            items=[QueueItem(ref="#1", title="t", completed=False, active=True)],
            state=QueueState(branch="", status="active"),
        )
        write_queue(workspace, q)
        _git(workspace, "add", ".queue")
        _git(workspace, "commit", "-m", "queue")
        result = detect(project, workspace)
        assert result.state == "aligned"
        assert result.queue_branch == ""


class TestWorkspaceBehind:
    def test_workspace_on_main(self, repos):
        project, workspace = repos
        base_sha = _git(project, "rev-parse", "HEAD").stdout.strip()
        _git(project, "checkout", "-b", "feature-x")
        _git(project, "commit", "--allow-empty", "-m", "work")
        bb_record(project, "feature-x", base_sha)
        result = detect(project, workspace)
        assert result.state == "workspace_behind"
        assert result.project_branch == "feature-x"
        assert result.workspace_branch == "main"

    def test_branch_does_not_exist_in_workspace(self, repos):
        project, workspace = repos
        base_sha = _git(project, "rev-parse", "HEAD").stdout.strip()
        _git(project, "checkout", "-b", "feature-x")
        _git(project, "commit", "--allow-empty", "-m", "work")
        bb_record(project, "feature-x", base_sha)
        result = detect(project, workspace)
        assert result.state == "workspace_behind"
        branches = _git(workspace, "branch", "--list", "feature-x").stdout.strip()
        assert branches == ""

    def test_branch_exists_but_not_checked_out(self, repos):
        project, workspace = repos
        base_sha = _git(project, "rev-parse", "HEAD").stdout.strip()
        _git(project, "checkout", "-b", "feature-x")
        _git(project, "commit", "--allow-empty", "-m", "work")
        bb_record(project, "feature-x", base_sha)
        _git(workspace, "branch", "feature-x")
        result = detect(project, workspace)
        assert result.state == "workspace_behind"
        current = _git(workspace, "symbolic-ref", "--short", "HEAD").stdout.strip()
        assert current == "main"


class TestWorkspaceDirty:
    def test_uncommitted_changes(self, repos):
        project, workspace = repos
        base_sha = _git(project, "rev-parse", "HEAD").stdout.strip()
        _git(project, "checkout", "-b", "feature-x")
        _git(project, "commit", "--allow-empty", "-m", "work")
        bb_record(project, "feature-x", base_sha)
        (workspace / "dirty.txt").write_text("uncommitted")
        result = detect(project, workspace)
        assert result.state == "workspace_dirty"

    def test_untracked_files_count_as_dirty(self, repos):
        project, workspace = repos
        base_sha = _git(project, "rev-parse", "HEAD").stdout.strip()
        _git(project, "checkout", "-b", "feature-x")
        _git(project, "commit", "--allow-empty", "-m", "work")
        bb_record(project, "feature-x", base_sha)
        (workspace / "untracked.txt").write_text("new file")
        result = detect(project, workspace)
        assert result.state == "workspace_dirty"

    def test_ignored_files_do_not_count_as_dirty(self, repos):
        project, workspace = repos
        base_sha = _git(project, "rev-parse", "HEAD").stdout.strip()
        _git(project, "checkout", "-b", "feature-x")
        _git(project, "commit", "--allow-empty", "-m", "work")
        bb_record(project, "feature-x", base_sha)
        (workspace / ".gitignore").write_text("ignored.txt\n")
        _git(workspace, "add", ".gitignore")
        _git(workspace, "commit", "-m", "add gitignore")
        (workspace / "ignored.txt").write_text("should be ignored")
        result = detect(project, workspace)
        assert result.state == "workspace_behind"

    def test_proj_wksp_links_do_not_count_as_dirty(self, repos):
        project, workspace = repos
        base_sha = _git(project, "rev-parse", "HEAD").stdout.strip()
        _git(project, "checkout", "-b", "feature-x")
        _git(project, "commit", "--allow-empty", "-m", "work")
        bb_record(project, "feature-x", base_sha)
        (workspace / "proj").symlink_to(project)
        result = detect(project, workspace)
        assert result.state == "workspace_behind"


class TestWorkspaceOther:
    def test_different_working_branches(self, repos):
        project, workspace = repos
        _git(project, "checkout", "-b", "feature-a")
        _git(workspace, "checkout", "-b", "feature-b")
        result = detect(project, workspace)
        assert result.state == "workspace_other"
        assert result.project_branch == "feature-a"
        assert result.workspace_branch == "feature-b"


class TestProjectBehind:
    def test_project_on_main_workspace_on_branch(self, repos):
        project, workspace = repos
        _git(workspace, "checkout", "-b", "feature-x")
        result = detect(project, workspace)
        assert result.state == "project_behind"
        assert result.project_branch == "main"
        assert result.workspace_branch == "feature-x"


class TestUnrecordedBranch:
    def test_no_base_recorded(self, repos):
        project, workspace = repos
        _git(project, "checkout", "-b", "feature-x")
        _git(workspace, "checkout", "-b", "feature-x")
        assert base_of(project, "feature-x") == ""
        result = detect(project, workspace)
        assert result.state == "unrecorded_branch"
        assert result.project_branch == "feature-x"


class TestQueueMismatch:
    def test_queue_names_different_branch(self, repos):
        project, workspace = repos
        base_sha = _git(project, "rev-parse", "HEAD").stdout.strip()
        _git(project, "checkout", "-b", "feature-x")
        _git(project, "commit", "--allow-empty", "-m", "work")
        bb_record(project, "feature-x", base_sha)
        _git(workspace, "checkout", "-b", "feature-x")
        bb_record(workspace, "feature-x", _git(workspace, "rev-parse", "main").stdout.strip())
        q = Queue(
            items=[QueueItem(ref="#1", title="t", completed=False, active=True)],
            state=QueueState(branch="feature-y", status="active"),
        )
        write_queue(workspace, q)
        _git(workspace, "add", ".queue")
        _git(workspace, "commit", "-m", "queue")
        result = detect(project, workspace)
        assert result.state == "queue_mismatch"
        assert result.queue_branch == "feature-y"


class TestReadOnly:
    """detect() must leave both repos byte-identical."""

    @pytest.fixture(params=[
        "on_base", "aligned", "workspace_behind", "workspace_dirty",
        "workspace_other", "project_behind", "unrecorded_branch", "queue_mismatch",
    ])
    def state_repos(self, request, tmp_path):
        name = request.param
        project = _init_repo(tmp_path / f"{name}_project")
        workspace = _init_repo(tmp_path / f"{name}_workspace")

        if name == "on_base":
            pass
        elif name == "aligned":
            base_sha = _git(project, "rev-parse", "HEAD").stdout.strip()
            _git(project, "checkout", "-b", "feature-x")
            _git(project, "commit", "--allow-empty", "-m", "work")
            bb_record(project, "feature-x", base_sha)
            _git(workspace, "checkout", "-b", "feature-x")
            bb_record(workspace, "feature-x", _git(workspace, "rev-parse", "main").stdout.strip())
        elif name == "workspace_behind":
            base_sha = _git(project, "rev-parse", "HEAD").stdout.strip()
            _git(project, "checkout", "-b", "feature-x")
            _git(project, "commit", "--allow-empty", "-m", "work")
            bb_record(project, "feature-x", base_sha)
        elif name == "workspace_dirty":
            base_sha = _git(project, "rev-parse", "HEAD").stdout.strip()
            _git(project, "checkout", "-b", "feature-x")
            _git(project, "commit", "--allow-empty", "-m", "work")
            bb_record(project, "feature-x", base_sha)
            (workspace / "dirty.txt").write_text("uncommitted")
        elif name == "workspace_other":
            _git(project, "checkout", "-b", "feature-a")
            _git(workspace, "checkout", "-b", "feature-b")
        elif name == "project_behind":
            _git(workspace, "checkout", "-b", "feature-x")
        elif name == "unrecorded_branch":
            _git(project, "checkout", "-b", "feature-x")
            _git(workspace, "checkout", "-b", "feature-x")
        elif name == "queue_mismatch":
            base_sha = _git(project, "rev-parse", "HEAD").stdout.strip()
            _git(project, "checkout", "-b", "feature-x")
            _git(project, "commit", "--allow-empty", "-m", "work")
            bb_record(project, "feature-x", base_sha)
            _git(workspace, "checkout", "-b", "feature-x")
            bb_record(workspace, "feature-x", _git(workspace, "rev-parse", "main").stdout.strip())
            q = Queue(
                items=[QueueItem(ref="#1", title="t", completed=False, active=True)],
                state=QueueState(branch="feature-y", status="active"),
            )
            write_queue(workspace, q)
            _git(workspace, "add", ".queue")
            _git(workspace, "commit", "-m", "queue")

        return name, project, workspace

    def test_no_mutation(self, state_repos):
        name, project, workspace = state_repos
        before_proj = _snapshot(project)
        before_wksp = _snapshot(workspace)
        result = detect(project, workspace)
        after_proj = _snapshot(project)
        after_wksp = _snapshot(workspace)
        assert before_proj == after_proj, f"project mutated in state {name}"
        assert before_wksp == after_wksp, f"workspace mutated in state {name}"
        assert result.state == name


class TestWorkspaceBaseRecord:
    def test_base_recorded_in_project_only_is_unrecorded(self, repos):
        """create-branches records the base in every repo; a workspace branch
        without one was made by hand."""
        project, workspace = repos
        base_sha = _git(project, "rev-parse", "HEAD").stdout.strip()
        _git(project, "checkout", "-b", "feature-x")
        bb_record(project, "feature-x", base_sha)
        _git(workspace, "checkout", "-b", "feature-x")
        result = detect(project, workspace)
        assert result.state == "unrecorded_branch"
        assert "workspace" in result.detail
        assert "project or" not in result.detail


class TestDetached:
    def test_project_detached_head(self, repos):
        project, workspace = repos
        _git(project, "checkout", "--detach")
        result = detect(project, workspace)
        assert result.state == "detached"
        assert result.project_branch == ""
        assert "project" in result.detail

    def test_workspace_detached_head(self, repos):
        project, workspace = repos
        _git(project, "checkout", "-b", "feature-x")
        _git(workspace, "checkout", "--detach")
        result = detect(project, workspace)
        assert result.state == "detached"
        assert "workspace" in result.detail

    def test_project_stopped_mid_rebase_is_detached_not_behind(self, repos):
        """A rebase stopped on a conflict leaves HEAD detached. It must never be
        read as 'project on a branch, workspace behind' and repaired."""
        project, workspace = repos
        (project / "f.txt").write_text("base\n")
        _git(project, "add", "f.txt"); _git(project, "commit", "-m", "base")
        _git(project, "checkout", "-b", "feature-x")
        (project / "f.txt").write_text("feature\n")
        _git(project, "commit", "-am", "feature")
        _git(project, "checkout", "main")
        (project / "f.txt").write_text("main\n")
        _git(project, "commit", "-am", "main")
        _git(project, "checkout", "feature-x")
        stopped = _git(project, "rebase", "main")
        assert stopped.returncode != 0
        before = _snapshot(project)
        result = detect(project, workspace)
        assert result.state == "detached"
        assert _snapshot(project) == before


class TestUnreadable:
    def test_project_is_not_a_repo(self, tmp_path):
        workspace = _init_repo(tmp_path / "workspace")
        plain = tmp_path / "plain"
        plain.mkdir()
        result = detect(plain, workspace)
        assert result.state == "unreadable"
        assert "project" in result.detail

    def test_workspace_missing(self, tmp_path):
        project = _init_repo(tmp_path / "project")
        result = detect(project, tmp_path / "nowhere")
        assert result.state == "unreadable"
        assert "workspace" in result.detail
