"""Tests for work-end/scope.py promote and squash-review commands (#599)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _d in ("project", "work-slot", "work-end"):
    sys.path.insert(0, str(ROOT / _d))

import branch_base  # noqa: E402
import squash_marker  # noqa: E402
import scope  # noqa: E402
from queue_io import Queue, QueueItem, QueueState, write_queue  # noqa: E402

BRANCH = "issue-1-x"


def g(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    assert r.returncode == 0, f"git {' '.join(args)}: {r.stderr}"
    return r.stdout.strip()


def with_remote(tmp_path: Path, name: str) -> tuple[Path, Path]:
    bare = tmp_path / "remotes" / f"{name}.git"
    bare.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    repo = tmp_path / name
    repo.mkdir()
    g(repo, "init", "-q", "-b", "main")
    (repo / "seed.txt").write_text(name)
    g(repo, "add", ".")
    g(repo, "commit", "-q", "-m", "init")
    g(repo, "remote", "add", "origin", str(bare))
    g(repo, "push", "-q", "origin", "main")
    return repo, bare


def commit(repo: Path, name: str, text: str = "x") -> None:
    (repo / name).write_text(text)
    g(repo, "add", name)
    g(repo, "commit", "-q", "-m", f"feat: {name} Refs O/r#1")


@pytest.fixture
def world(tmp_path):
    project, project_remote = with_remote(tmp_path, "project")
    workspace, workspace_remote = with_remote(tmp_path, "workspace")
    (workspace / "proj").symlink_to(project)
    (project / ".git" / "info" / "exclude").write_text("wksp\n")
    (workspace / ".git" / "info" / "exclude").write_text("proj\n.work-progress\n")
    for repo in (project, workspace):
        base = g(repo, "rev-parse", "main")
        g(repo, "checkout", "-q", "-b", BRANCH)
        branch_base.record(repo, BRANCH, base)
    commit(project, "code.txt")
    commit(workspace, "notes.md")
    squash_marker.mark(project, BRANCH)
    squash_marker.mark(workspace, BRANCH)
    write_queue(workspace, Queue(
        items=[QueueItem(ref="o/r#1", title="First", completed=False, active=False,
                         done_branch=BRANCH)],
        state=QueueState(branch=BRANCH, issue_repo="O/r", status="active", covers="o/r#1")))
    g(workspace, "add", ".queue")
    g(workspace, "commit", "-q", "-m", "chore: queue Refs O/r#1")
    squash_marker.mark(workspace, BRANCH)
    return dict(project=project, workspace=workspace)


class TestPromote:

    def test_no_unpromoted_returns_exit_0(self, world):
        code, lines = scope.promote(world["workspace"])
        assert code == 0
        assert any("PROMOTED=nothing_needed" in l for l in lines)

    def test_unpromoted_blog_entry_returns_exit_2(self, world):
        ws = world["workspace"]
        (ws / "blog").mkdir(exist_ok=True)
        (ws / "blog" / "2026-11-24-test-entry.md").write_text(
            "---\ntitle: test\n---\nbody\n")
        g(ws, "add", "blog")
        g(ws, "commit", "-q", "-m", "add blog entry Refs O/r#1")

        code, lines = scope.promote(ws)

        assert code == 2
        assert any("ERROR=promotion_needed" in l for l in lines)
        assert any("PROMOTE_COMMANDS=" in l for l in lines)


class TestSquashReview:

    def test_reviewed_branch_returns_exit_0(self, world):
        code, lines = scope.squash_review(world["workspace"])
        assert code == 0
        assert any("SQUASH_REVIEW=all_clear" in l for l in lines)

    def test_unreviewed_multi_commit_branch_returns_exit_2(self, world):
        project = world["project"]
        commit(project, "second.txt")  # now 2 commits, squash marker is stale

        code, lines = scope.squash_review(world["workspace"])

        assert code == 2
        assert any("ERROR=squash_review_needed" in l for l in lines)
        assert any("SQUASH_REVIEW=" in l for l in lines)
