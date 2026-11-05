"""Tests for work-end/close.py — atomic close ceremony."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "work-end"))
sys.path.insert(0, str(Path(__file__).parent.parent / "project"))
sys.path.insert(0, str(Path(__file__).parent.parent / "work-slot"))

from queue_io import read_queue, write_queue, Queue, QueueItem, QueueState


# --- helpers ---

def _init_repo(path: Path, branch: str = "main") -> None:
    subprocess.run(["git", "init", "-b", branch, str(path)],
                   capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@test.com"],
                   capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"],
                   capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "commit",
                     "--allow-empty", "-m", "init"],
                   capture_output=True, check=True)


def _create_branch_with_commit(repo: Path, branch: str) -> None:
    subprocess.run(["git", "-C", str(repo), "checkout", "-b", branch],
                   capture_output=True, check=True)
    (repo / f"{branch}-file.txt").write_text("content")
    subprocess.run(["git", "-C", str(repo), "add", "."],
                   capture_output=True, check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "work on " + branch],
                   capture_output=True, check=True)


def _make_queue(ws: Path, branch: str = "issue-1-feat",
                issue_repo: str = "R", number: int = 1,
                title: str = "Feat") -> None:
    write_queue(ws, Queue(
        items=[QueueItem(ref=f"{issue_repo}#{number}", title=title,
                         completed=False, active=True)],
        state=QueueState(branch=branch, issue_repo=issue_repo, status="active"),
    ))


# --- resolve tests ---

class TestResolve:
    def test_resolve_single_repo(self, tmp_path: Path) -> None:
        from close import resolve, CloseTarget

        repo = tmp_path / "project"
        _init_repo(repo)
        _create_branch_with_commit(repo, "issue-1-feat")

        ws = tmp_path / "workspace"
        ws.mkdir()
        _make_queue(ws, "issue-1-feat")

        with patch("close.discover_repo_topology") as mock_topo:
            mock_topo.return_value = [
                (repo, "main", "direct", None, "origin", ""),
            ]
            targets = resolve(ws)

        assert len(targets) == 1
        assert targets[0].branch == "issue-1-feat"
        assert targets[0].base_branch == "main"
        assert targets[0].transport == "direct"
        assert targets[0].canonical is None
        assert targets[0].push_target == "origin"
        assert targets[0].mirror_target == ""
        assert targets[0].is_workspace is False

    def test_resolve_no_branch_returns_empty(self, tmp_path: Path) -> None:
        from close import resolve

        repo = tmp_path / "project"
        _init_repo(repo)

        ws = tmp_path / "workspace"
        ws.mkdir()
        _make_queue(ws, "nonexistent")

        with patch("close.discover_repo_topology") as mock_topo:
            mock_topo.return_value = [
                (repo, "main", "direct", None, "origin", ""),
            ]
            targets = resolve(ws)

        assert len(targets) == 0

    def test_resolve_branch_no_commits_returns_empty(self, tmp_path: Path) -> None:
        """Branch exists but has no commits ahead of base → not a target."""
        from close import resolve

        repo = tmp_path / "project"
        _init_repo(repo)
        subprocess.run(["git", "-C", str(repo), "checkout", "-b", "issue-1-feat"],
                       capture_output=True, check=True)

        ws = tmp_path / "workspace"
        ws.mkdir()
        _make_queue(ws, "issue-1-feat")

        with patch("close.discover_repo_topology") as mock_topo:
            mock_topo.return_value = [
                (repo, "main", "direct", None, "origin", ""),
            ]
            targets = resolve(ws)

        assert len(targets) == 0

    def test_resolve_marks_workspace(self, tmp_path: Path) -> None:
        """The repo matching workspace path gets is_workspace=True."""
        from close import resolve

        ws = tmp_path / "workspace"
        _init_repo(ws)
        _create_branch_with_commit(ws, "issue-1-feat")

        _make_queue(ws, "issue-1-feat")

        with patch("close.discover_repo_topology") as mock_topo:
            mock_topo.return_value = [
                (ws, "main", "direct", None, "origin", ""),
            ]
            targets = resolve(ws)

        assert len(targets) == 1
        assert targets[0].is_workspace is True

    def test_resolve_multi_repo(self, tmp_path: Path) -> None:
        """Two repos with the same branch → two targets."""
        from close import resolve

        proj = tmp_path / "project"
        _init_repo(proj)
        _create_branch_with_commit(proj, "issue-1-feat")

        ws = tmp_path / "workspace"
        _init_repo(ws)
        _create_branch_with_commit(ws, "issue-1-feat")

        _make_queue(ws, "issue-1-feat")

        with patch("close.discover_repo_topology") as mock_topo:
            mock_topo.return_value = [
                (proj, "main", "direct", None, "origin", ""),
                (ws, "main", "direct", None, "origin", ""),
            ]
            targets = resolve(ws)

        assert len(targets) == 2
        ws_target = [t for t in targets if t.is_workspace][0]
        proj_target = [t for t in targets if not t.is_workspace][0]
        assert ws_target.repo == ws
        assert proj_target.repo == proj


# --- preflight tests ---

class TestPreflight:
    def test_preflight_clean(self, tmp_path: Path) -> None:
        from close import preflight, CloseTarget

        repo = tmp_path / "project"
        _init_repo(repo)
        _create_branch_with_commit(repo, "issue-1-feat")

        target = CloseTarget(
            repo=repo, branch="issue-1-feat", base_branch="main",
            transport="direct", canonical=None,
            push_target="origin", mirror_target="",
            is_workspace=False,
        )
        result = preflight([target])
        assert result["errors"] == []

    def test_preflight_dirty_worktree(self, tmp_path: Path) -> None:
        from close import preflight, CloseTarget

        repo = tmp_path / "project"
        _init_repo(repo)
        _create_branch_with_commit(repo, "issue-1-feat")
        (repo / "uncommitted.txt").write_text("dirty")

        target = CloseTarget(
            repo=repo, branch="issue-1-feat", base_branch="main",
            transport="direct", canonical=None,
            push_target="origin", mirror_target="",
            is_workspace=False,
        )
        result = preflight([target])
        assert len(result["errors"]) == 1
        assert "uncommitted changes" in result["errors"][0]

    def test_preflight_no_base_branch(self, tmp_path: Path) -> None:
        from close import preflight, CloseTarget

        repo = tmp_path / "project"
        _init_repo(repo, branch="develop")
        _create_branch_with_commit(repo, "issue-1-feat")

        target = CloseTarget(
            repo=repo, branch="issue-1-feat", base_branch="main",
            transport="direct", canonical=None,
            push_target="origin", mirror_target="",
            is_workspace=False,
        )
        result = preflight([target])
        assert any("no main branch" in e for e in result["errors"])

    def test_preflight_rescues_local_only_commits(self, tmp_path: Path) -> None:
        from close import preflight, CloseTarget

        origin = tmp_path / "origin"
        _init_repo(origin)

        repo = tmp_path / "project"
        subprocess.run(["git", "clone", str(origin), str(repo)],
                       capture_output=True, check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@test.com"],
                       capture_output=True, check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"],
                       capture_output=True, check=True)

        (repo / "local-only.txt").write_text("local")
        subprocess.run(["git", "-C", str(repo), "add", "."],
                       capture_output=True, check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "local only"],
                       capture_output=True, check=True)

        _create_branch_with_commit(repo, "issue-1-feat")

        target = CloseTarget(
            repo=repo, branch="issue-1-feat", base_branch="main",
            transport="direct", canonical=None,
            push_target="origin", mirror_target="",
            is_workspace=False,
        )
        result = preflight([target])
        assert "project" in result["rescued"]
        assert result["rescued"]["project"] == "rescue-project"


# --- land tests ---

def _checkout(repo: Path, branch: str) -> None:
    subprocess.run(["git", "-C", str(repo), "checkout", branch],
                   capture_output=True, check=True)


def _commit_count(repo: Path, ref: str = "HEAD") -> int:
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-list", "--count", ref],
        capture_output=True, text=True, check=True)
    return int(result.stdout.strip())


def _log_oneline(repo: Path, n: int = 10) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), "log", "--oneline", f"-{n}"],
        capture_output=True, text=True, check=True)
    return result.stdout.strip().splitlines()


def _file_exists_on_branch(repo: Path, branch: str, filename: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "-e", f"{branch}:{filename}"],
        capture_output=True)
    return result.returncode == 0


class TestLand:
    def test_squash_merge_produces_single_commit(self, tmp_path: Path) -> None:
        from close import land, CloseTarget

        repo = tmp_path / "project"
        _init_repo(repo)
        _create_branch_with_commit(repo, "issue-1-feat")
        (repo / "second.txt").write_text("more work")
        subprocess.run(["git", "-C", str(repo), "add", "."],
                       capture_output=True, check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "second commit"],
                       capture_output=True, check=True)

        _checkout(repo, "main")
        main_count_before = _commit_count(repo)

        target = CloseTarget(
            repo=repo, branch="issue-1-feat", base_branch="main",
            transport="direct", canonical=None,
            push_target="origin", mirror_target="",
            is_workspace=False,
        )
        sha = land(target)

        assert sha != ""
        main_count_after = _commit_count(repo)
        assert main_count_after == main_count_before + 1
        assert _file_exists_on_branch(repo, "main", "issue-1-feat-file.txt")
        assert _file_exists_on_branch(repo, "main", "second.txt")

    def test_land_idempotent_already_landed(self, tmp_path: Path) -> None:
        from close import land, CloseTarget

        repo = tmp_path / "project"
        _init_repo(repo)
        _create_branch_with_commit(repo, "issue-1-feat")

        target = CloseTarget(
            repo=repo, branch="issue-1-feat", base_branch="main",
            transport="direct", canonical=None,
            push_target="origin", mirror_target="",
            is_workspace=False,
        )

        sha1 = land(target)
        _checkout(repo, "main")
        sha2 = land(target)
        assert sha2 == sha1

    def test_land_workspace_uses_non_ff_merge(self, tmp_path: Path) -> None:
        from close import land, CloseTarget

        ws = tmp_path / "workspace"
        _init_repo(ws)
        _create_branch_with_commit(ws, "issue-1-feat")

        target = CloseTarget(
            repo=ws, branch="issue-1-feat", base_branch="main",
            transport="direct", canonical=None,
            push_target="origin", mirror_target="",
            is_workspace=True,
        )
        sha = land(target)
        assert sha != ""

        _checkout(ws, "main")
        log = _log_oneline(ws, 5)
        has_merge_commit = any("Merge branch" in line for line in log)
        assert has_merge_commit

    def test_land_two_hop_workspace_returns_empty(self, tmp_path: Path) -> None:
        from close import land, CloseTarget

        ws = tmp_path / "workspace"
        _init_repo(ws)
        _create_branch_with_commit(ws, "issue-1-feat")

        target = CloseTarget(
            repo=ws, branch="issue-1-feat", base_branch="main",
            transport="two-hop", canonical=tmp_path / "canonical",
            push_target="origin", mirror_target="",
            is_workspace=True,
        )
        sha = land(target)
        assert sha == ""

    def test_land_strips_lifecycle_files(self, tmp_path: Path) -> None:
        from close import land, CloseTarget

        repo = tmp_path / "project"
        _init_repo(repo)
        subprocess.run(["git", "-C", str(repo), "checkout", "-b", "issue-1-feat"],
                       capture_output=True, check=True)
        (repo / "real-code.py").write_text("code")
        (repo / ".close-progress").write_text("ephemeral")
        (repo / "JOURNAL.md").write_text("journal")
        subprocess.run(["git", "-C", str(repo), "add", "."],
                       capture_output=True, check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "work with lifecycle files"],
                       capture_output=True, check=True)

        target = CloseTarget(
            repo=repo, branch="issue-1-feat", base_branch="main",
            transport="direct", canonical=None,
            push_target="origin", mirror_target="",
            is_workspace=False,
        )
        land(target)

        assert _file_exists_on_branch(repo, "main", "real-code.py")
        assert not _file_exists_on_branch(repo, "main", ".close-progress")
        assert not _file_exists_on_branch(repo, "main", "JOURNAL.md")


# --- stamp tests ---

def _last_commit_msg(repo: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "log", "-1", "--format=%s"],
        capture_output=True, text=True, check=True)
    return result.stdout.strip()


class TestStamp:
    def test_stamp_creates_empty_commit(self, tmp_path: Path) -> None:
        from close import stamp, CloseTarget

        repo = tmp_path / "project"
        _init_repo(repo)
        _create_branch_with_commit(repo, "issue-1-feat")

        target = CloseTarget(
            repo=repo, branch="issue-1-feat", base_branch="main",
            transport="direct", canonical=None,
            push_target="origin", mirror_target="",
            is_workspace=False,
        )
        stamp(target, "abc123")

        _checkout(repo, "issue-1-feat")
        msg = _last_commit_msg(repo)
        assert msg.startswith("chore: branch closed")
        assert "abc123" in msg
        assert "main" in msg

    def test_stamp_idempotent(self, tmp_path: Path) -> None:
        from close import stamp, CloseTarget

        repo = tmp_path / "project"
        _init_repo(repo)
        _create_branch_with_commit(repo, "issue-1-feat")

        target = CloseTarget(
            repo=repo, branch="issue-1-feat", base_branch="main",
            transport="direct", canonical=None,
            push_target="origin", mirror_target="",
            is_workspace=False,
        )
        stamp(target, "abc123")
        count_after_first = _commit_count(repo, "issue-1-feat")

        stamp(target, "abc123")
        count_after_second = _commit_count(repo, "issue-1-feat")
        assert count_after_second == count_after_first


# --- advance tests ---

class TestAdvance:
    def test_advance_marks_done_and_activates_next(self, tmp_path: Path) -> None:
        from close import advance

        ws = tmp_path / "workspace"
        ws.mkdir()
        write_queue(ws, Queue(
            items=[
                QueueItem(ref="R#1", title="First", completed=False, active=True),
                QueueItem(ref="R#2", title="Second", completed=False, active=False),
            ],
            state=QueueState(branch="b", issue_repo="R", status="active"),
        ))

        next_item = advance(ws, "R#1")
        assert next_item is not None
        assert next_item.ref == "R#2"
        assert next_item.active is True

        q = read_queue(ws)
        assert q.items[0].completed is True
        assert q.items[0].active is False
        assert q.items[1].active is True
        assert q.state.status == "active"

    def test_advance_last_item_drains(self, tmp_path: Path) -> None:
        from close import advance

        ws = tmp_path / "workspace"
        ws.mkdir()
        write_queue(ws, Queue(
            items=[
                QueueItem(ref="R#1", title="Only", completed=False, active=True),
            ],
            state=QueueState(branch="b", issue_repo="R", status="active"),
        ))

        next_item = advance(ws, "R#1")
        assert next_item is None

        q = read_queue(ws)
        assert q.items[0].completed is True
        assert q.state.status == "drained"

    def test_advance_idempotent_wrong_issue(self, tmp_path: Path) -> None:
        from close import advance

        ws = tmp_path / "workspace"
        ws.mkdir()
        write_queue(ws, Queue(
            items=[
                QueueItem(ref="R#1", title="First", completed=False, active=True),
                QueueItem(ref="R#2", title="Second", completed=False, active=False),
            ],
            state=QueueState(branch="b", issue_repo="R", status="active"),
        ))

        advance(ws, "R#1")
        next_item = advance(ws, "R#1")
        assert next_item is not None
        assert next_item.ref == "R#2"

        q = read_queue(ws)
        assert q.items[1].active is True
        assert not q.items[1].completed


# --- elevate_queue tests ---

class TestElevateQueue:
    def test_elevate_copies_to_slot_root(self, tmp_path: Path) -> None:
        from close import elevate_queue

        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / ".queue").write_text("queue content")

        slot_root = tmp_path / "slot"
        slot_root.mkdir()

        elevate_queue(ws, slot_root)
        assert (slot_root / ".queue").exists()
        assert (slot_root / ".queue").read_text() == "queue content"

    def test_elevate_skips_non_slot(self, tmp_path: Path) -> None:
        from close import elevate_queue

        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / ".queue").write_text("queue content")

        elevate_queue(ws, None)

    def test_elevate_refuses_overwrite(self, tmp_path: Path) -> None:
        from close import elevate_queue

        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / ".queue").write_text("workspace queue")

        slot_root = tmp_path / "slot"
        slot_root.mkdir()
        (slot_root / ".queue").write_text("slot-level epic queue")

        elevate_queue(ws, slot_root)
        assert (slot_root / ".queue").read_text() == "slot-level epic queue"


# --- close orchestration integration test ---

class TestCloseIntegration:
    def test_full_ceremony_single_repo(self, tmp_path: Path) -> None:
        """End-to-end: create repos, branch, queue, run close(), verify result."""
        from close import close, CloseTarget

        proj = tmp_path / "project"
        _init_repo(proj)
        _create_branch_with_commit(proj, "issue-1-feat")

        ws = tmp_path / "workspace"
        _init_repo(ws)
        _create_branch_with_commit(ws, "issue-1-feat")

        write_queue(ws, Queue(
            items=[
                QueueItem(ref="R#1", title="First", completed=False, active=True),
                QueueItem(ref="R#2", title="Second", completed=False, active=False),
            ],
            state=QueueState(branch="issue-1-feat", issue_repo="R", status="active"),
        ))
        subprocess.run(["git", "-C", str(ws), "add", ".queue"],
                       capture_output=True, check=True)
        subprocess.run(["git", "-C", str(ws), "commit", "-m", "add queue"],
                       capture_output=True, check=True)
        _checkout(ws, "issue-1-feat")
        subprocess.run(["git", "-C", str(ws), "merge", "main", "--no-edit"],
                       capture_output=True, check=True)

        from unittest.mock import patch
        with patch("close.discover_repo_topology") as mock_topo, \
             patch("close._detect_slot_root", return_value=None):
            mock_topo.return_value = [
                (proj, "main", "direct", None, "origin", ""),
                (ws, "main", "direct", None, "origin", ""),
            ]
            result = close(ws)

        assert result.success is True
        assert result.next_item is not None
        assert result.next_item.ref == "R#2"

        assert _file_exists_on_branch(proj, "main", "issue-1-feat-file.txt")
        assert _file_exists_on_branch(ws, "main", "issue-1-feat-file.txt")

        current_proj = subprocess.run(
            ["git", "-C", str(proj), "branch", "--show-current"],
            capture_output=True, text=True).stdout.strip()
        current_ws = subprocess.run(
            ["git", "-C", str(ws), "branch", "--show-current"],
            capture_output=True, text=True).stdout.strip()
        assert current_proj == "main"
        assert current_ws == "main"

    def test_stamp_sha_is_verifiable(self, tmp_path: Path) -> None:
        """The stamp commit's SHA reference must be verifiable via git cat-file."""
        from close import close

        proj = tmp_path / "project"
        _init_repo(proj)
        _create_branch_with_commit(proj, "issue-1-feat")

        ws = tmp_path / "workspace"
        _init_repo(ws)
        _create_branch_with_commit(ws, "issue-1-feat")

        write_queue(ws, Queue(
            items=[QueueItem(ref="R#1", title="Feat", completed=False, active=True)],
            state=QueueState(branch="issue-1-feat", issue_repo="R", status="active"),
        ))
        subprocess.run(["git", "-C", str(ws), "add", ".queue"],
                       capture_output=True, check=True)
        subprocess.run(["git", "-C", str(ws), "commit", "-m", "add queue"],
                       capture_output=True, check=True)
        _checkout(ws, "issue-1-feat")
        subprocess.run(["git", "-C", str(ws), "merge", "main", "--no-edit"],
                       capture_output=True, check=True)

        with patch("close.discover_repo_topology") as mock_topo, \
             patch("close._detect_slot_root", return_value=None):
            mock_topo.return_value = [
                (proj, "main", "direct", None, "origin", ""),
                (ws, "main", "direct", None, "origin", ""),
            ]
            result = close(ws)

        assert result.success is True

        stamp_msg = subprocess.run(
            ["git", "-C", str(proj), "log", "-1", "--format=%s", "issue-1-feat"],
            capture_output=True, text=True).stdout.strip()
        assert "branch closed" in stamp_msg
        assert "landed as" in stamp_msg
        landed_sha = stamp_msg.split("landed as ")[1].split(" on ")[0]
        cat = subprocess.run(
            ["git", "-C", str(proj), "cat-file", "-e", landed_sha],
            capture_output=True)
        assert cat.returncode == 0, f"stamp SHA {landed_sha} must be verifiable"

    def test_landed_sha_exists_and_matches_main(self, tmp_path: Path) -> None:
        """Issue #501: reported LANDED_* SHA must exist and match main HEAD."""
        from close import close

        proj = tmp_path / "project"
        _init_repo(proj)
        _multi_commit_branch(proj, "issue-1-feat", 4)

        ws = tmp_path / "workspace"
        _init_repo(ws)
        _create_branch_with_commit(ws, "issue-1-feat")

        write_queue(ws, Queue(
            items=[QueueItem(ref="R#1", title="Feat", completed=False, active=True)],
            state=QueueState(branch="issue-1-feat", issue_repo="R", status="active"),
        ))
        subprocess.run(["git", "-C", str(ws), "add", ".queue"],
                       capture_output=True, check=True)
        subprocess.run(["git", "-C", str(ws), "commit", "-m", "add queue"],
                       capture_output=True, check=True)
        _checkout(ws, "issue-1-feat")
        subprocess.run(["git", "-C", str(ws), "merge", "main", "--no-edit"],
                       capture_output=True, check=True)

        with patch("close.discover_repo_topology") as mock_topo, \
             patch("close._detect_slot_root", return_value=None):
            mock_topo.return_value = [
                (proj, "main", "direct", None, "origin", ""),
                (ws, "main", "direct", None, "origin", ""),
            ]
            result = close(ws)

        assert result.success is True

        for repo_name, sha in result.landed.items():
            if not sha:
                continue
            cat = subprocess.run(
                ["git", "-C", str(proj if repo_name == "project" else ws),
                 "cat-file", "-e", sha], capture_output=True)
            assert cat.returncode == 0, f"LANDED_{repo_name}={sha} must exist"

        proj_head = subprocess.run(
            ["git", "-C", str(proj), "rev-parse", "HEAD"],
            capture_output=True, text=True).stdout.strip()
        assert proj_head == result.landed.get("project", ""), \
            f"project main HEAD ({proj_head}) must match reported SHA"

        for repo in [proj, ws]:
            status = subprocess.run(
                ["git", "-C", str(repo), "status", "--porcelain"],
                capture_output=True, text=True).stdout.strip()
            assert status == "", f"{repo.name}: working tree must be clean, got: {status}"

    def test_close_no_targets_returns_error(self, tmp_path: Path) -> None:
        from close import close

        ws = tmp_path / "workspace"
        ws.mkdir()
        write_queue(ws, Queue(
            items=[QueueItem(ref="R#1", title="Feat", completed=False, active=True)],
            state=QueueState(branch="nonexistent", issue_repo="R", status="active"),
        ))

        from unittest.mock import patch
        with patch("close.discover_repo_topology") as mock_topo:
            mock_topo.return_value = []
            result = close(ws)

        assert result.success is False
        assert len(result.errors) > 0


def _multi_commit_branch(repo: Path, branch: str, num_commits: int = 3) -> None:
    subprocess.run(["git", "-C", str(repo), "checkout", "-b", branch],
                   capture_output=True, check=True)
    for i in range(num_commits):
        (repo / f"file{i}.txt").write_text(f"content {i}")
        subprocess.run(["git", "-C", str(repo), "add", "."],
                       capture_output=True, check=True)
        subprocess.run(["git", "-C", str(repo), "commit",
                        "-m", f"feat: change {i} Refs #1"],
                       capture_output=True, check=True)


class TestSquashMergeCommit:
    """Issue #501: squash_merge must commit on main, not just stage."""

    def test_squash_merge_creates_commit_on_main(self, tmp_path):
        from close import squash_merge
        repo = tmp_path / "repo"
        _init_repo(repo)
        _multi_commit_branch(repo, "feat", 3)
        pre_sha = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "main"],
            capture_output=True, text=True).stdout.strip()
        sha = squash_merge(repo, "feat", "main")
        post_sha = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "main"],
            capture_output=True, text=True).stdout.strip()
        assert post_sha != pre_sha, "main HEAD must advance after squash_merge"
        assert post_sha == sha, "returned SHA must match main HEAD"

    def test_squash_merge_clean_working_tree(self, tmp_path):
        from close import squash_merge
        repo = tmp_path / "repo"
        _init_repo(repo)
        _multi_commit_branch(repo, "feat", 3)
        squash_merge(repo, "feat", "main")
        status = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain"],
            capture_output=True, text=True).stdout.strip()
        assert status == "", f"working tree must be clean after squash_merge, got: {status}"

    def test_squash_merge_sha_exists(self, tmp_path):
        from close import squash_merge
        repo = tmp_path / "repo"
        _init_repo(repo)
        _multi_commit_branch(repo, "feat", 3)
        sha = squash_merge(repo, "feat", "main")
        result = subprocess.run(
            ["git", "-C", str(repo), "cat-file", "-e", sha],
            capture_output=True)
        assert result.returncode == 0, f"reported SHA {sha} must exist"

    def test_squash_merge_single_commit_on_main(self, tmp_path):
        from close import squash_merge
        repo = tmp_path / "repo"
        _init_repo(repo)
        _multi_commit_branch(repo, "feat", 5)
        sha = squash_merge(repo, "feat", "main")
        log = subprocess.run(
            ["git", "-C", str(repo), "log", "--oneline", f"main~1..main"],
            capture_output=True, text=True).stdout.strip()
        assert log.count("\n") == 0, "squash must produce exactly one commit on main"

    def test_squash_merge_preserves_commit_messages(self, tmp_path):
        from close import squash_merge
        repo = tmp_path / "repo"
        _init_repo(repo)
        _multi_commit_branch(repo, "feat", 3)
        squash_merge(repo, "feat", "main")
        msg = subprocess.run(
            ["git", "-C", str(repo), "log", "-1", "--format=%B", "main"],
            capture_output=True, text=True).stdout.strip()
        assert "feat: change 0" in msg, "squash commit must include original messages"
        assert "feat: change 2" in msg

    def test_squash_merge_raises_on_commit_failure(self, tmp_path):
        from close import squash_merge
        repo = tmp_path / "repo"
        _init_repo(repo)
        _multi_commit_branch(repo, "feat", 2)
        hooks_dir = repo / ".git" / "hooks"
        hooks_dir.mkdir(exist_ok=True)
        hook = hooks_dir / "pre-commit"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        subprocess.run(["git", "-C", str(repo), "config", "--local",
                        "core.hooksPath", str(hooks_dir)],
                       capture_output=True, check=True)
        with pytest.raises(RuntimeError, match="commit failed"):
            squash_merge(repo, "feat", "main")
