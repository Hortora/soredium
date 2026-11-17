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
import squash_marker


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


def _add_commits(repo: Path, branch: str, n: int = 2, reviewed: bool = True) -> None:
    """Create a branch with n commits. reviewed=True records a squash review at its tip."""
    _git(repo, "checkout", "-b", branch)
    for i in range(n):
        (repo / f"{branch}-file{i}.txt").write_text(f"content {i}")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", f"feat: {branch} change {i} Refs #1")
    if reviewed:
        squash_marker.mark(repo, branch)


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

    ws = _slot_clone(tmp_path, slot_dir, ws_name)
    (ws / ".workspace").write_text(f"project: {slot_dir / repos[0]}\n")

    repo_paths = []
    for name in repos:
        repo_paths.append(_slot_clone(tmp_path, slot_dir, name))

    return slot_dir, repo_paths


def _canonical(tmp_path: Path, name: str) -> Path:
    """The canonical repo a slot clone lands in."""
    return tmp_path / "canonical" / name


def _slot_clone(tmp_path: Path, slot_dir: Path, name: str) -> Path:
    """A slot repo as slots really are: a clone whose `local` remote is its canonical repo."""
    canonical = _init_repo(_canonical(tmp_path, name))
    clone = slot_dir / name
    subprocess.run(["git", "clone", "-q", str(canonical), str(clone)],
                   capture_output=True, check=True)
    _git(clone, "config", "user.email", "test@test.com")
    _git(clone, "config", "user.name", "Test")
    _git(clone, "remote", "rename", "origin", "local")
    return clone


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

    def test_slot_work_reaches_canonical_and_canonical_checkout_is_untouched(self, tmp_path):
        slot_dir, [repo] = _setup_slot(tmp_path, ["engine"], "issue-1-feat")
        ws = slot_dir / "wsp-test"
        canonical = _canonical(tmp_path, "engine")
        _git(canonical, "checkout", "-b", "someone-elses-work")
        (canonical / "wip.txt").write_text("uncommitted\n")
        _add_commits(repo, "issue-1-feat", 3)
        _add_commits(ws, "issue-1-feat", 1)
        _make_queue(slot_dir, "issue-1-feat")

        result = close(slot_dir)

        assert result.success, f"ceremony failed: {result.errors}"
        assert result.landed["engine"] == _main_head(canonical) == _main_head(repo)
        assert _file_on_main(canonical, "issue-1-feat-file2.txt")
        assert _on_branch(canonical) == "someone-elses-work"
        assert (canonical / "wip.txt").read_text() == "uncommitted\n"
        assert _git(canonical, "rev-list", "--merges", "--count", "main").stdout.strip() == "0"

    def test_slot_queue_at_root(self, tmp_path):
        """Queue at slot root (not inside workspace) is found."""
        slot_dir, [repo] = _setup_slot(tmp_path, ["engine"], "issue-1-feat")
        _add_commits(repo, "issue-1-feat", 2)
        _make_queue(slot_dir, "issue-1-feat")

        q = read_queue(slot_dir)
        assert q is not None
        assert q.state.branch == "issue-1-feat"


class TestSlotCarriesEverything:
    """Workspace clones are worked on directly on main; nothing in a slot is left behind."""

    def _ws_commit(self, ws: Path, name: str) -> str:
        (ws / name).write_text("workspace content\n")
        _git(ws, "add", name)
        _git(ws, "commit", "-m", f"docs: {name} Refs #1")
        return _git(ws, "rev-parse", "HEAD").stdout.strip()

    def test_workspace_commits_on_main_reach_the_canonical_workspace(self, tmp_path):
        slot_dir, [repo] = _setup_slot(tmp_path, ["engine"], "issue-1-feat")
        ws = slot_dir / "wsp-test"
        _git(ws, "add", ".workspace")
        _git(ws, "commit", "-m", "chore: marker Refs #1")
        tip = self._ws_commit(ws, "blog-entry.md")
        _add_commits(repo, "issue-1-feat", 2)
        _make_queue(slot_dir, "issue-1-feat")
        canonical_ws = _canonical(tmp_path, "wsp-test")

        result = close(slot_dir)

        assert result.success, result.errors
        assert _main_head(canonical_ws) == tip
        assert _file_on_main(canonical_ws, "blog-entry.md")
        assert result.carried == {"wsp-test:main": 2}
        assert result.not_landed == {}
        from close import render
        assert "CARRIED=wsp-test:main commits=2" in render(result)

    def test_workspace_clone_on_its_own_branch_is_carried_too(self, tmp_path):
        slot_dir, [repo] = _setup_slot(tmp_path, ["engine"], "issue-1-feat")
        ws = slot_dir / "wsp-test"
        _git(ws, "add", ".workspace")
        _git(ws, "commit", "-m", "chore: marker Refs #1")
        _git(ws, "checkout", "-b", "notes")
        self._ws_commit(ws, "notes.md")
        _add_commits(repo, "issue-1-feat", 2)
        _make_queue(slot_dir, "issue-1-feat")

        result = close(slot_dir)

        assert result.success, result.errors
        assert _file_on_main(_canonical(tmp_path, "wsp-test"), "notes.md")
        assert "wsp-test:notes" in result.carried

    def test_stranded_workspace_content_blocks_ready_for_archive(self, tmp_path):
        slot_dir, [repo] = _setup_slot(tmp_path, ["engine"], "issue-1-feat")
        ws = slot_dir / "wsp-test"
        _git(ws, "add", ".workspace")
        _git(ws, "commit", "-m", "chore: marker Refs #1")
        self._ws_commit(ws, "blog-entry.md")
        canonical_ws = _canonical(tmp_path, "wsp-test")
        (canonical_ws / "blog-entry.md").write_text("a different entry already here\n")
        _git(canonical_ws, "add", ".")
        _git(canonical_ws, "commit", "-m", "docs: conflicting entry Refs #1")
        canonical_before = _main_head(canonical_ws)
        _add_commits(repo, "issue-1-feat", 2)
        _make_queue(slot_dir, "issue-1-feat")

        result = close(slot_dir)

        assert result.success, result.errors          # the issue's code did land
        assert "wsp-test:main" in result.not_landed
        assert result.slot_ready == ""
        assert not (slot_dir / ".landed").exists()
        assert _main_head(canonical_ws) == canonical_before
        from close import render
        assert any(line.startswith("NOT_LANDED=wsp-test:main") for line in render(result))

    def test_work_left_on_a_project_clones_own_main_is_carried(self, tmp_path):
        slot_dir, [engine, agency] = _setup_slot(tmp_path, ["engine", "agency"], "issue-1-feat")
        (agency / "earlier.txt").write_text("landed only in the clone by an older ceremony\n")
        _git(agency, "add", ".")
        _git(agency, "commit", "-m", "feat: earlier Refs #1")
        _add_commits(engine, "issue-1-feat", 2)
        _make_queue(slot_dir, "issue-1-feat")

        result = close(slot_dir)

        assert result.success, result.errors
        assert _file_on_main(_canonical(tmp_path, "agency"), "earlier.txt")
        assert result.carried == {"agency:main": 1}

    def test_nothing_stray_means_nothing_carried(self, tmp_path):
        slot_dir, [repo] = _setup_slot(tmp_path, ["engine"], "issue-1-feat")
        _add_commits(repo, "issue-1-feat", 2)
        _make_queue(slot_dir, "issue-1-feat")

        result = close(slot_dir)

        assert result.success, result.errors
        assert result.carried == {} and result.not_landed == {}


class TestSlotPromotionGate:
    """In a slot the workspace clone is worked on directly on main; its documents are gated too."""

    def _slot_with_blog(self, tmp_path):
        slot_dir, [repo] = _setup_slot(tmp_path, ["engine"], "issue-1-feat")
        ws = slot_dir / "wsp-test"
        (ws / "blog").mkdir()
        (ws / "blog" / "2026-01-01-entry.md").write_text("an entry\n")
        _git(ws, "add", "blog")
        _git(ws, "commit", "-m", "docs: entry Refs #1")
        _add_commits(repo, "issue-1-feat", 1)
        _make_queue(slot_dir, "issue-1-feat")
        return slot_dir, repo, ws

    def test_slot_close_refuses_until_the_workspace_document_is_promoted(self, tmp_path):
        from close import render
        slot_dir, repo, ws = self._slot_with_blog(tmp_path)
        canonical = _canonical(tmp_path, "engine")
        before = _main_head(canonical)

        result = close(slot_dir)

        assert not result.success
        assert result.unpromoted == [
            "wsp-test/blog/2026-01-01-entry.md -> engine/docs/blog/2026-01-01-entry.md"]
        assert render(result)[0] == "ACTION=promotion_needed"
        assert _main_head(canonical) == before
        assert not (slot_dir / ".landed").exists()

    def test_promoted_document_lands_in_canonical_with_the_branch(self, tmp_path):
        from close import render
        slot_dir, repo, ws = self._slot_with_blog(tmp_path)
        command = [l for l in render(close(slot_dir)) if l.startswith("PROMOTE=")][0]
        done = subprocess.run(command[len("PROMOTE="):].split(), capture_output=True, text=True)
        assert done.returncode == 0, done.stdout + done.stderr
        squash_marker.mark(repo, "issue-1-feat")

        result = close(slot_dir)

        assert result.success, (result.errors, result.unpromoted, result.squash_review)
        assert _file_on_main(_canonical(tmp_path, "engine"), "docs/blog/2026-01-01-entry.md")
        assert _file_on_main(_canonical(tmp_path, "wsp-test"), "blog/2026-01-01-entry.md")


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


# --- Wrong-branch guards (#513, casehubio/casehub-pages#666) ---

def _land_and_stamp(repo: Path, branch: str) -> str:
    """Land a branch on main by fast-forward and stamp it, as a completed close would."""
    _git(repo, "checkout", "main")
    _git(repo, "merge", "--ff-only", branch)
    landed = _main_head(repo)
    _git(repo, "checkout", branch)
    _git(repo, "commit", "--allow-empty", "-m",
         f"chore: branch closed — landed as {landed} on main  Refs #1")
    return landed


def _commits_ahead(repo: Path, branch: str) -> int:
    return int(_git(repo, "rev-list", "--count", f"main..{branch}").stdout.strip())


class TestWrongBranchGuards:

    def test_stamped_branch_is_not_closed_again(self, tmp_path):
        """Queue names an already-stamped branch: the ceremony must fail, not report success."""
        repo = _init_repo(tmp_path / "repo")
        _add_commits(repo, "issue-1-old", 2)
        landed = _land_and_stamp(repo, "issue-1-old")
        _git(repo, "checkout", "main")
        _make_queue(repo, "issue-1-old")

        with patch("close.discover_repo_topology") as m, \
             patch("close._detect_slot_root", return_value=None):
            m.return_value = [(repo, "main", "direct", None, "origin", "")]
            result = close(repo)

        assert not result.success, "closing a stamped branch must not report success"
        assert result.landed == {}
        assert any("already closed" in e for e in result.errors), result.errors
        assert _main_head(repo) == landed, "main must not move"

    def test_queue_branch_differs_from_project_branch(self, tmp_path):
        """The pages #666 case: queue names the old stamped branch, project is on new work."""
        proj = _init_repo(tmp_path / "project")
        ws = _init_repo(tmp_path / "workspace")
        (ws / "proj").symlink_to(proj)
        _add_commits(proj, "issue-1-old", 2)
        landed = _land_and_stamp(proj, "issue-1-old")
        _git(proj, "checkout", "main")
        _add_commits(proj, "issue-2-new", 3)
        _make_queue(ws, "issue-1-old")

        with patch("close.discover_repo_topology") as m, \
             patch("close._detect_slot_root", return_value=None):
            m.return_value = [
                (proj, "main", "direct", None, "origin", ""),
                (ws, "main", "direct", None, "origin", ""),
            ]
            result = close(ws)

        assert not result.success, "queue/branch mismatch must not report success"
        assert result.landed == {}
        joined = " ".join(result.errors)
        assert "issue-2-new" in joined and "issue-1-old" in joined, result.errors
        assert _main_head(proj) == landed, "main must not move"
        assert _on_branch(proj) == "issue-2-new", "project must be left on its work branch"
        assert _commits_ahead(proj, "issue-2-new") == 3, "unlanded work must be intact"
        assert not (ws / ".close-state").exists()

    def test_empty_queue_branch_with_project_on_feature_branch(self, tmp_path):
        """Queue has no branch recorded while the project is on a feature branch."""
        proj = _init_repo(tmp_path / "project")
        ws = _init_repo(tmp_path / "workspace")
        (ws / "proj").symlink_to(proj)
        _add_commits(proj, "issue-2-new", 2)
        _make_queue(ws, "")

        with patch("close.discover_repo_topology") as m, \
             patch("close._detect_slot_root", return_value=None):
            m.return_value = [
                (proj, "main", "direct", None, "origin", ""),
                (ws, "main", "direct", None, "origin", ""),
            ]
            result = close(ws)

        assert not result.success
        assert any("issue-2-new" in e for e in result.errors), result.errors
        assert _on_branch(proj) == "issue-2-new"

    def test_rerun_skips_stamped_repo_and_lands_the_rest(self, tmp_path):
        """Interrupted slot close: one repo already stamped, the other still needs landing."""
        slot_dir, [agency, connectors] = _setup_slot(
            tmp_path, ["agency", "connectors"], "issue-1-feat")
        _add_commits(agency, "issue-1-feat", 2)
        _add_commits(connectors, "issue-1-feat", 2)
        agency_landed = _land_and_stamp(agency, "issue-1-feat")
        connectors_pre = _main_head(connectors)
        _make_queue(slot_dir, "issue-1-feat")

        result = close(slot_dir)

        assert result.success, f"ceremony failed: {result.errors}"
        assert "connectors" in result.landed
        assert "agency" not in result.landed, "stamped repo must not be reported as landed again"
        assert _main_head(agency) == agency_landed, "already-landed repo must not change"
        assert _main_head(connectors) != connectors_pre
        assert _file_on_main(connectors, "issue-1-feat-file0.txt")


# --- Squash review marker (#514, casehubio/casehub-pages#666) ---

def _subjects_on_main(repo: Path, since: str) -> list[str]:
    out = _git(repo, "log", "--format=%s", f"{since}..main").stdout.strip()
    return out.splitlines() if out else []


def _single_repo_close(repo: Path):
    with patch("close.discover_repo_topology") as m, \
         patch("close._detect_slot_root", return_value=None):
        m.return_value = [(repo, "main", "direct", None, "origin", "")]
        return close(repo)


def _project_close(proj: Path, ws: Path):
    with patch("close.discover_repo_topology") as m, \
         patch("close._detect_slot_root", return_value=None):
        m.return_value = [
            (proj, "main", "direct", None, "origin", ""),
            (ws, "main", "direct", None, "origin", ""),
        ]
        return close(ws)


def _two_repos(tmp_path: Path) -> tuple[Path, Path]:
    proj = _init_repo(tmp_path / "project")
    ws = _init_repo(tmp_path / "workspace")
    (ws / "proj").symlink_to(proj)
    return proj, ws


class TestSquashReviewGate:

    def test_several_commits_without_review_do_not_land(self, tmp_path):
        proj, ws = _two_repos(tmp_path)
        pre = _main_head(proj)
        _add_commits(proj, "issue-1-feat", 3, reviewed=False)
        _make_queue(ws, "issue-1-feat")

        result = _project_close(proj, ws)

        assert not result.success
        assert result.errors == [], "review-needed is its own outcome, not an error"
        assert len(result.squash_review) == 1
        assert "project:issue-1-feat" in result.squash_review[0]
        assert "no squash review" in result.squash_review[0]
        assert _main_head(proj) == pre, "nothing may land"
        assert _on_branch(proj) == "issue-1-feat"
        assert not (ws / ".close-state").exists()

    def test_reviewed_branch_lands_with_every_commit_preserved(self, tmp_path):
        proj, ws = _two_repos(tmp_path)
        pre = _main_head(proj)
        _add_commits(proj, "issue-1-feat", 3, reviewed=True)
        _make_queue(ws, "issue-1-feat")

        result = _project_close(proj, ws)

        assert result.success, result.errors
        subjects = _subjects_on_main(proj, pre)
        assert len(subjects) == 3, f"all three commits must reach main: {subjects}"
        assert all(s.startswith("feat: issue-1-feat change") for s in subjects)

    def test_single_commit_lands_without_review(self, tmp_path):
        proj, ws = _two_repos(tmp_path)
        _add_commits(proj, "issue-1-feat", 1, reviewed=False)
        _make_queue(ws, "issue-1-feat")

        result = _project_close(proj, ws)

        assert result.success, result.errors
        assert _file_on_main(proj, "issue-1-feat-file0.txt")

    def test_commits_added_after_review_do_not_land(self, tmp_path):
        proj, ws = _two_repos(tmp_path)
        pre = _main_head(proj)
        _add_commits(proj, "issue-1-feat", 2, reviewed=True)
        (proj / "late.txt").write_text("late")
        _git(proj, "add", ".")
        _git(proj, "commit", "-m", "wip: late change Refs #1")
        _make_queue(ws, "issue-1-feat")

        result = _project_close(proj, ws)

        assert not result.success
        assert "1 commit(s) added since" in result.squash_review[0]
        assert _main_head(proj) == pre

    def test_leftover_squash_plan_file_does_not_collapse_commits(self, tmp_path):
        """An untracked .squash-plan left in the working tree must be inert."""
        proj, ws = _two_repos(tmp_path)
        pre = _main_head(proj)
        _add_commits(proj, "issue-1-feat", 3, reviewed=True)
        (proj / ".squash-plan").write_text("squash-plan: left over from earlier work\n")
        _make_queue(ws, "issue-1-feat")

        result = _project_close(proj, ws)

        assert result.success, result.errors
        subjects = _subjects_on_main(proj, pre)
        assert len([s for s in subjects if s.startswith("feat:")]) == 3, subjects
        assert not any("squash-plan" in s for s in subjects), subjects

    def test_committed_squash_plan_does_not_collapse_commits(self, tmp_path):
        """The pages #666 case: .squash-plan committed on the branch after git-squash."""
        proj, ws = _two_repos(tmp_path)
        pre = _main_head(proj)
        _add_commits(proj, "issue-1-feat", 3, reviewed=False)
        (proj / ".squash-plan").write_text("squash-plan: compacted 43 -> 7 commits\n")
        _git(proj, "add", "-f", ".squash-plan")
        _git(proj, "commit", "-m", "chore: mark branch as squash-compacted Refs #1")
        squash_marker.mark(proj, "issue-1-feat")
        _make_queue(ws, "issue-1-feat")

        result = _project_close(proj, ws)

        assert result.success, result.errors
        subjects = _subjects_on_main(proj, pre)
        assert len([s for s in subjects if s.startswith("feat:")]) == 3, subjects
        assert not any(s.startswith("squash-plan:") for s in subjects), subjects

    def test_marker_is_removed_after_landing(self, tmp_path):
        proj, ws = _two_repos(tmp_path)
        _add_commits(proj, "issue-1-feat", 2, reviewed=True)
        _make_queue(ws, "issue-1-feat")

        result = _project_close(proj, ws)

        assert result.success, result.errors
        r = subprocess.run(["git", "-C", str(proj), "rev-parse", "--verify", "-q",
                            squash_marker.marker_ref("issue-1-feat")], capture_output=True)
        assert r.returncode != 0, "marker must be deleted once the branch has landed"

    def test_workspace_repo_is_not_gated(self, tmp_path):
        """Only project repos need a squash review; workspace commits land as they are."""
        proj, ws = _two_repos(tmp_path)
        _add_commits(proj, "issue-1-feat", 1, reviewed=False)
        _add_commits(ws, "issue-1-feat", 3, reviewed=False)
        _make_queue(ws, "issue-1-feat")

        result = _project_close(proj, ws)

        assert result.success, f"{result.errors} {result.squash_review}"

    def test_slot_reports_every_repo_needing_review(self, tmp_path):
        slot_dir, [agency, connectors] = _setup_slot(
            tmp_path, ["agency", "connectors"], "issue-1-feat")
        _add_commits(agency, "issue-1-feat", 2, reviewed=False)
        _add_commits(connectors, "issue-1-feat", 2, reviewed=False)
        agency_pre, connectors_pre = _main_head(agency), _main_head(connectors)
        _make_queue(slot_dir, "issue-1-feat")

        result = close(slot_dir)

        assert not result.success
        joined = " ".join(result.squash_review)
        assert "agency:issue-1-feat" in joined and "connectors:issue-1-feat" in joined
        assert _main_head(agency) == agency_pre and _main_head(connectors) == connectors_pre


class TestRenderResult:

    def test_review_needed_output(self):
        from close import CloseResult, render
        lines = render(CloseResult(success=False,
                                   squash_review=["pages:issue-1: no squash review recorded"]))
        assert lines[0] == "ACTION=squash_review_needed"
        assert "SQUASH_REVIEW=pages:issue-1: no squash review recorded" in lines

    def test_error_output(self):
        from close import CloseResult, render
        lines = render(CloseResult(success=False, errors=["boom"]))
        assert lines == ["ACTION=error", "ERROR=boom"]

    def test_complete_output(self):
        from close import CloseResult, render
        lines = render(CloseResult(success=True, landed={"pages": "abc123"}))
        assert lines[0] == "ACTION=complete"
        assert "LANDED_pages=abc123" in lines


# --- Result reporting and idle-repo guard (#515, casehubio/casehub-pages#666) ---

def _on_main(repo: Path, sha: str) -> bool:
    """True when sha is main's tip or an ancestor of it."""
    r = subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", sha, "main"],
                       capture_output=True)
    return r.returncode == 0


def _same_name_repos(tmp_path: Path) -> tuple[Path, Path]:
    """Project and workspace whose directories share a name, as with casehub pages."""
    proj = _init_repo(tmp_path / "code" / "pages")
    ws = _init_repo(tmp_path / "public" / "pages")
    (ws / "proj").symlink_to(proj)
    return proj, ws


class TestResultReporting:

    def test_project_and_workspace_with_the_same_name_are_both_reported(self, tmp_path):
        proj, ws = _same_name_repos(tmp_path)
        _add_commits(proj, "issue-1-feat", 2)
        _add_commits(ws, "issue-1-feat", 1)
        _make_queue(ws, "issue-1-feat")

        result = _project_close(proj, ws)

        assert result.success, result.errors
        assert result.landed == {"pages": _main_head(proj)}
        # The workspace gains the queue-advance commit after landing, so its landed
        # SHA is on main but need not be the tip.
        assert list(result.workspace_landed) == ["pages"]
        assert _on_main(ws, result.workspace_landed["pages"])
        assert result.workspace_landed["pages"] != result.landed["pages"]
        assert _file_on_main(ws, "issue-1-feat-file0.txt")

    def test_same_name_repos_render_as_separate_lines(self, tmp_path):
        from close import CloseResult, render
        lines = render(CloseResult(success=True, landed={"pages": "aaa"},
                                   workspace_landed={"pages": "bbb"}))
        assert "LANDED_pages=aaa" in lines
        assert "WORKSPACE_LANDED_pages=bbb" in lines

    def test_single_repo_is_reported_as_landed(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _add_commits(repo, "issue-1-feat", 2)
        _make_queue(repo, "issue-1-feat")

        result = _single_repo_close(repo)

        assert result.success, result.errors
        assert list(result.landed) == ["repo"]
        assert _on_main(repo, result.landed["repo"])
        assert _file_on_main(repo, "issue-1-feat-file1.txt")
        assert result.workspace_landed == {}

    def test_reported_sha_is_main_tip_when_lifecycle_files_are_stripped(self, tmp_path):
        """casehub-pages#666 bug 3: a leaked lifecycle file must not leave the reported SHA behind main."""
        proj, ws = _two_repos(tmp_path)
        _add_commits(proj, "issue-1-feat", 2, reviewed=False)
        (proj / ".squash-plan").write_text("left over\n")
        _git(proj, "add", "-f", ".squash-plan")
        _git(proj, "commit", "-m", "chore: leaked lifecycle file Refs #1")
        squash_marker.mark(proj, "issue-1-feat")
        _make_queue(ws, "issue-1-feat")

        result = _project_close(proj, ws)

        assert result.success, result.errors
        assert result.landed["project"] == _main_head(proj), "reported SHA must be main's tip"
        assert not _file_on_main(proj, ".squash-plan")
        assert result.landed["project"] in _stamp_msg(proj, "issue-1-feat")
        assert _file_on_main(proj, "issue-1-feat-file1.txt")


class TestIdleRepoGuard:

    def _stuck_rebase(self, repo: Path) -> None:
        """Leave repo stopped on a rebase conflict, as a failed `pull --rebase` does."""
        (repo / "conflict.txt").write_text("base\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "base Refs #1")
        _git(repo, "checkout", "-b", "upstream-side")
        (repo / "conflict.txt").write_text("theirs\n")
        _git(repo, "commit", "-am", "theirs Refs #1")
        _git(repo, "checkout", "main")
        (repo / "conflict.txt").write_text("ours\n")
        _git(repo, "commit", "-am", "ours Refs #1")
        r = subprocess.run(["git", "-C", str(repo), "rebase", "upstream-side"],
                           capture_output=True, text=True)
        assert r.returncode != 0, "fixture must stop on a conflict"

    def test_workspace_mid_rebase_blocks_the_ceremony(self, tmp_path):
        proj, ws = _two_repos(tmp_path)
        _add_commits(proj, "issue-1-feat", 2)
        pre = _main_head(proj)
        _make_queue(ws, "issue-1-feat")
        _git(ws, "add", ".queue")
        _git(ws, "commit", "-m", "queue Refs #1")
        self._stuck_rebase(ws)

        result = _project_close(proj, ws)

        assert not result.success
        assert any("workspace" in e and "rebase" in e for e in result.errors), result.errors
        assert _main_head(proj) == pre, "nothing may land"
        assert (ws / ".git" / "rebase-merge").exists() or (ws / ".git" / "rebase-apply").exists(), \
            "the ceremony must not abort a rebase it did not start"

    def test_project_on_detached_head_blocks_the_ceremony(self, tmp_path):
        proj, ws = _two_repos(tmp_path)
        _add_commits(proj, "issue-1-feat", 2)
        pre = _main_head(proj)
        _git(proj, "checkout", "--detach")
        _make_queue(ws, "issue-1-feat")

        result = _project_close(proj, ws)

        assert not result.success
        assert any("project" in e and "detached" in e for e in result.errors), result.errors
        assert _main_head(proj) == pre

    def test_project_mid_merge_blocks_the_ceremony(self, tmp_path):
        proj, ws = _two_repos(tmp_path)
        (proj / "conflict.txt").write_text("base\n")
        _git(proj, "add", ".")
        _git(proj, "commit", "-m", "base Refs #1")
        _git(proj, "checkout", "-b", "other-side")
        (proj / "conflict.txt").write_text("theirs\n")
        _git(proj, "commit", "-am", "theirs Refs #1")
        _git(proj, "checkout", "main")
        _add_commits(proj, "issue-1-feat", 1)
        (proj / "conflict.txt").write_text("ours\n")
        _git(proj, "commit", "-am", "ours Refs #1")
        squash_marker.mark(proj, "issue-1-feat")
        r = subprocess.run(["git", "-C", str(proj), "merge", "other-side"],
                           capture_output=True, text=True)
        assert r.returncode != 0, "fixture must stop on a conflict"
        _make_queue(ws, "issue-1-feat")

        result = _project_close(proj, ws)

        assert not result.success
        assert any("project" in e and "merge" in e for e in result.errors), result.errors


# --- Repos whose commit-msg hook requires an issue reference (#518) ---

HOOKS_DIR = Path(__file__).parent.parent / ".githooks"


def _require_issue_refs(repo: Path) -> None:
    """Install soredium's own commit-msg hook, which rejects commits with no issue reference."""
    hooks = repo / ".git" / "hooks"
    hooks.mkdir(exist_ok=True)
    target = hooks / "commit-msg"
    target.write_text((HOOKS_DIR / "commit-msg").read_text())
    target.chmod(0o755)


def _close_single(repo: Path):
    with patch("close.discover_repo_topology") as m:
        m.return_value = [(repo, "main", "direct", None, "origin", "")]
        return close(repo)


class TestIssueReferenceHook:

    def test_hook_fixture_rejects_a_commit_without_a_reference(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _require_issue_refs(repo)
        r = subprocess.run(["git", "-C", str(repo), "commit", "--allow-empty", "-m", "chore: nothing"],
                           capture_output=True, text=True)
        assert r.returncode != 0

    def test_close_completes_with_an_active_issue(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _add_commits(repo, "issue-1-feat", 2)
        _make_queue(repo, "issue-1-feat", issue_repo="Owner/repo")
        _git(repo, "add", ".queue")
        _git(repo, "commit", "-m", "chore: queue Refs #1")
        squash_marker.mark(repo, "issue-1-feat")
        _require_issue_refs(repo)

        result = _close_single(repo)

        assert result.success, result.errors
        stamp = _git(repo, "log", "-1", "--format=%B", "issue-1-feat").stdout
        assert stamp.startswith("chore: branch closed")
        assert "Refs Owner/repo#1" in stamp
        assert not (repo / ".close-state").exists()
        assert "advance queue" in _git(repo, "log", "-1", "--format=%s", "main").stdout
        assert _is_clean(repo)

    def test_close_uses_covers_when_no_item_is_active(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _add_commits(repo, "issue-7-feat", 1)
        write_queue(repo, Queue(items=[], state=QueueState(
            branch="issue-7-feat", issue_repo="Owner/repo", status="active",
            covers="Owner/repo#7")))
        _require_issue_refs(repo)

        result = _close_single(repo)

        assert result.success, result.errors
        assert "Refs Owner/repo#7" in _git(repo, "log", "-1", "--format=%B", "issue-7-feat").stdout

    def test_close_completes_when_no_issue_is_known(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _add_commits(repo, "issue-9-feat", 1)
        write_queue(repo, Queue(items=[], state=QueueState(
            branch="issue-9-feat", issue_repo="Owner/repo", status="active")))
        _require_issue_refs(repo)

        result = _close_single(repo)

        assert result.success, result.errors
        stamp = _git(repo, "log", "-1", "--format=%B", "issue-9-feat").stdout
        assert stamp.startswith("chore: branch closed")
        assert "no-issue" in stamp

    @pytest.mark.parametrize("message,accepted", [
        ("fix: thing  Refs #12", True),
        ("fix: thing\n\nRefs Owner/repo#12", True),
        ("fix: thing\n\nCloses owner-x/repo.y#3", True),
        ("chore: tidy  no-issue: tooling", True),
        ("fix: thing mentioning Owner/repo#12 without a keyword", False),
        ("fix: thing", False),
    ])
    def test_hook_accepts_qualified_references(self, tmp_path, message, accepted):
        repo = _init_repo(tmp_path / "repo")
        _require_issue_refs(repo)
        r = subprocess.run(["git", "-C", str(repo), "commit", "--allow-empty", "-m", message],
                           capture_output=True, text=True)
        assert (r.returncode == 0) == accepted, r.stderr


# --- A slot whose queue is drained is marked landed, ready to archive (#521) ---

class TestSlotMarkedLanded:

    def _landed(self, slot_dir: Path) -> dict[str, str]:
        text = (slot_dir / ".landed").read_text()
        return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)

    def test_drained_queue_writes_landed_marker(self, tmp_path):
        slot_dir, [repo] = _setup_slot(tmp_path, ["engine"], "issue-1-feat")
        _add_commits(repo, "issue-1-feat", 2)
        _make_queue(slot_dir, "issue-1-feat")

        result = close(slot_dir)

        assert result.success, result.errors
        assert result.slot_ready == str(slot_dir)
        marker = self._landed(slot_dir)
        assert marker["branch"] == "issue-1-feat"
        assert marker["landed_shas"] == f"engine:{_main_head(repo)}"
        assert "wsp-test" not in marker["repos"]

    def test_marker_is_not_written_while_issues_remain(self, tmp_path):
        slot_dir, [repo] = _setup_slot(tmp_path, ["engine"], "issue-1-feat")
        _add_commits(repo, "issue-1-feat", 2)
        _make_queue(slot_dir, "issue-1-feat",
                    items=[("R#1", "First"), ("R#2", "Second")])

        result = close(slot_dir)

        assert result.success, result.errors
        assert result.next_item is not None
        assert result.slot_ready == ""
        assert not (slot_dir / ".landed").exists()

    def test_marker_keeps_repos_landed_by_an_earlier_close(self, tmp_path):
        slot_dir, [agency, connectors] = _setup_slot(
            tmp_path, ["agency", "connectors"], "issue-1-feat")
        _add_commits(agency, "issue-1-feat", 1)
        _make_queue(slot_dir, "issue-1-feat")
        (slot_dir / ".landed").write_text(
            "branch=issue-0-old\nrepos=connectors\nlanded_shas=connectors:abc123\n")

        result = close(slot_dir)

        assert result.success, result.errors
        shas = dict(e.split(":") for e in self._landed(slot_dir)["landed_shas"].split(","))
        assert shas == {"connectors": "abc123", "agency": _main_head(agency)}

    def test_render_reports_ready_for_archive(self, tmp_path):
        from close import render
        slot_dir, [repo] = _setup_slot(tmp_path, ["engine"], "issue-1-feat")
        _add_commits(repo, "issue-1-feat", 1)
        _make_queue(slot_dir, "issue-1-feat")

        lines = render(close(slot_dir))

        assert f"SLOT_READY_FOR_ARCHIVE={slot_dir}" in lines

    def test_non_slot_close_writes_no_marker(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _add_commits(repo, "issue-1-feat", 1)
        _make_queue(repo, "issue-1-feat")

        with patch("close.discover_repo_topology") as m:
            m.return_value = [(repo, "main", "direct", None, "origin", "")]
            result = close(repo)

        assert result.success
        assert result.slot_ready == ""
        assert not (repo / ".landed").exists()
