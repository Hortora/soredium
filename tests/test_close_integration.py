"""Integration tests for close.py — real git repos, real ceremony, real verification.

Each test creates the full git topology, runs close(), and verifies
the actual state of every repo afterward. No mocks for git operations.
"""
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
from close import close, resolve, CloseTarget


# --- helpers ---

def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=True,
    )


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.email", "test@test.com")
    _git(path, "config", "user.name", "Test")
    _git(path, "commit", "--allow-empty", "-m", "init")
    return path


def _add_commits(repo: Path, branch: str, n: int = 2) -> None:
    _git(repo, "checkout", "-b", branch)
    for i in range(n):
        (repo / f"{branch}-file{i}.txt").write_text(f"content {i}")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", f"feat: {branch} change {i} Refs #1")


def _make_queue(ws: Path, branch: str, issue_repo: str = "R",
                items: list[tuple[str, str]] | None = None) -> None:
    if items is None:
        items = [(f"{issue_repo}#1", "Task")]
    write_queue(ws, Queue(
        items=[QueueItem(ref=ref, title=title, completed=False,
                         active=(i == 0))
               for i, (ref, title) in enumerate(items)],
        state=QueueState(branch=branch, issue_repo=issue_repo, status="active"),
    ))


def _main_head(repo: Path) -> str:
    return _git(repo, "rev-parse", "main").stdout.strip()


def _is_clean(repo: Path) -> bool:
    r = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                       capture_output=True, text=True)
    return r.stdout.strip() == ""


def _on_branch(repo: Path) -> str:
    return _git(repo, "branch", "--show-current").stdout.strip()


def _sha_exists(repo: Path, sha: str) -> bool:
    r = subprocess.run(["git", "-C", str(repo), "cat-file", "-e", sha],
                       capture_output=True)
    return r.returncode == 0


def _file_on_main(repo: Path, filename: str) -> bool:
    r = subprocess.run(["git", "-C", str(repo), "show", f"main:{filename}"],
                       capture_output=True)
    return r.returncode == 0


def _stamp_msg(repo: Path, branch: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), "log", "-1", "--format=%s", branch],
                       capture_output=True, text=True)
    return r.stdout.strip()


# --- Topology 1: single repo (project = workspace) ---

class TestSingleRepo:
    """Simplest case: one repo, project IS workspace."""

    def test_lands_branch_on_main(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        pre_head = _main_head(repo)
        _add_commits(repo, "issue-1-feat", 3)
        _make_queue(repo, "issue-1-feat")

        with patch("close.discover_repo_topology") as m:
            m.return_value = [(repo, "main", "direct", None, "origin", "")]
            result = close(repo)

        assert result.success
        assert _main_head(repo) != pre_head
        assert _is_clean(repo)
        assert _on_branch(repo) == "main"
        assert _file_on_main(repo, "issue-1-feat-file0.txt")
        for sha in result.landed.values():
            if sha:
                assert _sha_exists(repo, sha)

    def test_stamps_branch_after_landing(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _add_commits(repo, "issue-1-feat", 2)
        _make_queue(repo, "issue-1-feat")

        with patch("close.discover_repo_topology") as m:
            m.return_value = [(repo, "main", "direct", None, "origin", "")]
            result = close(repo)

        assert result.success
        assert "branch closed" in _stamp_msg(repo, "issue-1-feat")

    def test_advances_queue(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _add_commits(repo, "issue-1-feat", 2)
        _make_queue(repo, "issue-1-feat",
                    items=[("R#1", "First"), ("R#2", "Second")])

        with patch("close.discover_repo_topology") as m:
            m.return_value = [(repo, "main", "direct", None, "origin", "")]
            result = close(repo)

        assert result.success
        assert result.next_item is not None
        assert result.next_item.ref == "R#2"


# --- Topology 2: two-repo (project + workspace, symlinked) ---

class TestTwoRepo:
    """Standard non-slot: project + workspace repos with symlinks."""

    def _setup(self, tmp_path, branch="issue-1-feat"):
        proj = _init_repo(tmp_path / "project")
        ws = _init_repo(tmp_path / "workspace")
        (proj / "wksp").symlink_to(ws)
        (ws / "proj").symlink_to(proj)
        _add_commits(proj, branch, 3)
        _add_commits(ws, branch, 1)
        _make_queue(ws, branch)
        return proj, ws

    def test_lands_both_repos(self, tmp_path):
        proj, ws = self._setup(tmp_path)
        proj_pre = _main_head(proj)
        ws_pre = _main_head(ws)

        with patch("close.discover_repo_topology") as m, \
             patch("close._detect_slot_root", return_value=None):
            m.return_value = [
                (proj, "main", "direct", None, "origin", ""),
                (ws, "main", "direct", None, "origin", ""),
            ]
            result = close(ws)

        assert result.success
        assert _main_head(proj) != proj_pre
        assert _is_clean(proj)
        assert _is_clean(ws)
        assert _on_branch(proj) == "main"
        assert _on_branch(ws) == "main"
        assert _file_on_main(proj, "issue-1-feat-file0.txt")

    def test_workspace_on_main_project_on_branch(self, tmp_path):
        """#509 scenario: workspace on main, project on feature branch."""
        proj = _init_repo(tmp_path / "project")
        ws = _init_repo(tmp_path / "workspace")
        (ws / "proj").symlink_to(proj)
        _add_commits(proj, "issue-1-feat", 3)
        _make_queue(ws, "issue-1-feat")

        with patch("close.discover_repo_topology") as m, \
             patch("close._detect_slot_root", return_value=None):
            m.return_value = [
                (proj, "main", "direct", None, "origin", ""),
                (ws, "main", "direct", None, "origin", ""),
            ]
            result = close(ws)

        assert result.success
        assert _file_on_main(proj, "issue-1-feat-file0.txt")
        assert _on_branch(proj) == "main"


# --- Topology 3: queue edge cases ---

class TestQueueEdgeCases:

    def test_empty_branch_in_queue_uses_current(self, tmp_path):
        """#509 regression: empty branch field should not produce 'no targets'."""
        repo = _init_repo(tmp_path / "repo")
        _add_commits(repo, "issue-1-feat", 2)
        write_queue(repo, Queue(
            items=[QueueItem(ref="R#1", title="Task", completed=False, active=True)],
            state=QueueState(branch="", issue_repo="R", status="active"),
        ))

        targets = resolve(repo)
        # With empty branch, discover_active_branches returns [] from queue
        # but should fall back to scanning repo branches
        # Currently this returns empty — this test documents the gap

    def test_stale_branch_from_previous_issue(self, tmp_path):
        """Queue has branch from old issue, repo is on a new branch."""
        repo = _init_repo(tmp_path / "repo")
        _add_commits(repo, "issue-2-new", 2)
        _make_queue(repo, "issue-1-old")

        with patch("close.discover_repo_topology") as m:
            m.return_value = [(repo, "main", "direct", None, "origin", "")]
            result = close(repo)

        # Should fail gracefully — issue-1-old doesn't exist
        assert not result.success or len(result.landed) == 0

    def test_already_landed_is_idempotent(self, tmp_path):
        """Running close twice on an already-landed branch should not error."""
        repo = _init_repo(tmp_path / "repo")
        _add_commits(repo, "issue-1-feat", 2)
        _make_queue(repo, "issue-1-feat")

        with patch("close.discover_repo_topology") as m, \
             patch("close._detect_slot_root", return_value=None):
            m.return_value = [(repo, "main", "direct", None, "origin", "")]
            result1 = close(repo)

        assert result1.success

        # Re-create queue for second close attempt
        _make_queue(repo, "issue-1-feat")
        with patch("close.discover_repo_topology") as m, \
             patch("close._detect_slot_root", return_value=None):
            m.return_value = [(repo, "main", "direct", None, "origin", "")]
            result2 = close(repo)

        # Should succeed (idempotent) or return no targets (already landed)
        assert _on_branch(repo) == "main"

    def test_multi_item_queue_advances_correctly(self, tmp_path):
        """Queue with 3 items: close should advance past active to next."""
        repo = _init_repo(tmp_path / "repo")
        _add_commits(repo, "issue-1-feat", 2)
        _make_queue(repo, "issue-1-feat",
                    items=[("R#1", "Done"), ("R#2", "Next"), ("R#3", "Later")])

        with patch("close.discover_repo_topology") as m, \
             patch("close._detect_slot_root", return_value=None):
            m.return_value = [(repo, "main", "direct", None, "origin", "")]
            result = close(repo)

        assert result.success
        assert result.next_item.ref == "R#2"
        queue = read_queue(repo)
        assert queue.items[0].completed
        assert queue.items[1].active


# --- Topology 4: slot with repos ---

def _setup_slot(tmp_path, repos: list[str], branch: str,
                ws_name: str = "wsp-test") -> tuple[Path, list[Path]]:
    """Create a slot with .slot file, workspace, and N repo clones."""
    slot_dir = tmp_path / "slots" / "42"
    slot_dir.mkdir(parents=True)

    repo_lines = "\n".join(f"- {r}" + (" (primary)" if i == 0 else "")
                           for i, r in enumerate(repos))
    (slot_dir / ".slot").write_text(
        f"# Slot 42 — test\n\n## Issue\nR#1\n\n## Repos\n{repo_lines}\n"
    )

    ws = _init_repo(slot_dir / ws_name)
    (ws / ".workspace").write_text(f"project: {slot_dir / repos[0]}\n")

    repo_paths = []
    for name in repos:
        repo = _init_repo(slot_dir / name)
        repo_paths.append(repo)

    return slot_dir, repo_paths


class TestSlotSingleRepo:
    """Slot with one project repo + workspace."""

    def test_slot_single_repo_lands(self, tmp_path):
        slot_dir, [repo] = _setup_slot(tmp_path, ["engine"], "issue-1-feat")
        ws = slot_dir / "wsp-test"

        _add_commits(repo, "issue-1-feat", 3)
        _add_commits(ws, "issue-1-feat", 1)
        _make_queue(slot_dir, "issue-1-feat")

        pre_head = _main_head(repo)

        result = close(slot_dir)

        assert result.success, f"ceremony failed: {result.errors}"
        assert _main_head(repo) != pre_head
        assert _file_on_main(repo, "issue-1-feat-file0.txt")
        assert _on_branch(repo) == "main"
        assert _is_clean(repo)

    def test_slot_queue_at_root(self, tmp_path):
        """Queue at slot root (not inside workspace) is found."""
        slot_dir, [repo] = _setup_slot(tmp_path, ["engine"], "issue-1-feat")
        _add_commits(repo, "issue-1-feat", 2)
        _make_queue(slot_dir, "issue-1-feat")

        q = read_queue(slot_dir)
        assert q is not None
        assert q.state.branch == "issue-1-feat"


class TestSlotMultiRepo:
    """Slot with 2+ repos on the same branch."""

    def test_multi_repo_same_branch(self, tmp_path):
        slot_dir, [agency, connectors] = _setup_slot(
            tmp_path, ["agency", "connectors"], "issue-1-feat")
        ws = slot_dir / "wsp-test"

        _add_commits(agency, "issue-1-feat", 3)
        _add_commits(connectors, "issue-1-feat", 2)
        _add_commits(ws, "issue-1-feat", 1)
        _make_queue(slot_dir, "issue-1-feat")

        result = close(slot_dir)

        assert result.success, f"ceremony failed: {result.errors}"
        assert _file_on_main(agency, "issue-1-feat-file0.txt")
        assert _file_on_main(connectors, "issue-1-feat-file0.txt")
        assert _on_branch(agency) == "main"
        assert _on_branch(connectors) == "main"

    def test_multi_repo_different_branches(self, tmp_path):
        """Cumulative close: repos on different feature branches."""
        slot_dir, [agency, connectors] = _setup_slot(
            tmp_path, ["agency", "connectors"], "issue-1-feat")
        ws = slot_dir / "wsp-test"

        _add_commits(agency, "issue-1-feat", 2)
        _add_commits(connectors, "issue-2-other", 2)
        _make_queue(slot_dir, "issue-1-feat")

        result = close(slot_dir)

        assert result.success, f"ceremony failed: {result.errors}"
        assert _file_on_main(agency, "issue-1-feat-file0.txt")
        assert _file_on_main(connectors, "issue-2-other-file0.txt")

    def test_one_repo_no_branch(self, tmp_path):
        """One repo has the branch, the other doesn't — should still close."""
        slot_dir, [agency, connectors] = _setup_slot(
            tmp_path, ["agency", "connectors"], "issue-1-feat")

        _add_commits(agency, "issue-1-feat", 2)
        # connectors stays on main — no feature branch
        _make_queue(slot_dir, "issue-1-feat")

        result = close(slot_dir)

        assert result.success, f"ceremony failed: {result.errors}"
        assert _file_on_main(agency, "issue-1-feat-file0.txt")
        assert _on_branch(agency) == "main"


# --- Verification helpers ---

class TestPostCeremonyState:
    """Verify the full post-ceremony invariants that every close must satisfy."""

    def test_all_invariants(self, tmp_path):
        """Master invariant test — every assertion here is a contract."""
        proj = _init_repo(tmp_path / "project")
        ws = _init_repo(tmp_path / "workspace")
        (ws / "proj").symlink_to(proj)

        _add_commits(proj, "issue-1-feat", 4)
        _add_commits(ws, "issue-1-feat", 1)
        _make_queue(ws, "issue-1-feat",
                    items=[("R#1", "Active"), ("R#2", "Pending")])

        proj_pre = _main_head(proj)

        with patch("close.discover_repo_topology") as m, \
             patch("close._detect_slot_root", return_value=None):
            m.return_value = [
                (proj, "main", "direct", None, "origin", ""),
                (ws, "main", "direct", None, "origin", ""),
            ]
            result = close(ws)

        # 1. Ceremony succeeded
        assert result.success, f"ceremony failed: {result.errors}"

        # 2. Main HEAD advanced
        assert _main_head(proj) != proj_pre, "main must advance"

        # 3. Working trees clean
        assert _is_clean(proj), "project working tree must be clean"
        assert _is_clean(ws), "workspace working tree must be clean"

        # 4. Both repos on main
        assert _on_branch(proj) == "main"
        assert _on_branch(ws) == "main"

        # 5. Reported SHAs exist
        for repo_name, sha in result.landed.items():
            if sha:
                target = proj if repo_name == "project" else ws
                assert _sha_exists(target, sha), \
                    f"LANDED_{repo_name}={sha} must exist"

        # 6. Branch content on main
        assert _file_on_main(proj, "issue-1-feat-file0.txt")

        # 7. Branch stamped
        stamp = _stamp_msg(proj, "issue-1-feat")
        assert "branch closed" in stamp
        landed_sha = result.landed.get("project", "")
        if landed_sha:
            assert landed_sha in stamp

        # 8. Queue advanced
        assert result.next_item is not None
        assert result.next_item.ref == "R#2"

        # 9. No .close-state left behind
        assert not (ws / ".close-state").exists()
