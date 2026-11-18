"""End-to-end test: one piece of work through a permanent clone.

Creates a family with canonical project + workspace, creates a permanent
clone, does one branch of work, and runs close.close() for real.
Modelled on test_close_integration.py and test_canonical_sync.py fixtures.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "work-end"))
sys.path.insert(0, str(Path(__file__).parent.parent / "project"))
sys.path.insert(0, str(Path(__file__).parent.parent / "work-slot"))

from queue_io import write_queue, Queue, QueueItem, QueueState
from close import close, render
import squash_marker
import branch_base


HOOK = Path(__file__).parent.parent / "hooks" / "push-guard.py"


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=check,
    )


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.email", "test@test.com")
    _git(path, "config", "user.name", "Test")
    _git(path, "commit", "--allow-empty", "-m", "init")
    return path


def _main_head(repo: Path) -> str:
    return _git(repo, "rev-parse", "main").stdout.strip()


def _merge_count(repo: Path) -> int:
    return int(_git(repo, "rev-list", "--merges", "--count", "main").stdout.strip())


def _push_guard_hook(command: str, cwd: Path) -> subprocess.CompletedProcess:
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
               "tool_input": {"command": command}, "cwd": str(cwd)}
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                          capture_output=True, text=True)


@pytest.fixture
def clone_world(tmp_path):
    """Family with canonical P and W, permanent clone, one branch of work done.

    Returns (family, canonical_p, canonical_w, clone_target, project_clone,
             ws_clone, branch).
    """
    family = tmp_path / "family"
    family.mkdir()
    (family / "slots").mkdir()

    # Canonical project repo P
    canonical_p = _init_repo(family / "P")
    (canonical_p / "src.txt").write_text("source\n")
    _git(canonical_p, "add", ".")
    _git(canonical_p, "commit", "-m", "add source")

    # Canonical workspace W with proj -> P, and a committed .queue
    canonical_w = _init_repo(family / "W")
    proj_link = canonical_w / "proj"
    proj_link.symlink_to(os.path.relpath(canonical_p, canonical_w))
    write_queue(canonical_w, Queue(
        items=[QueueItem(ref="R#1", title="Task", completed=False, active=True)],
        state=QueueState(branch="", issue_repo="R", status="active"),
    ))
    _git(canonical_w, "add", ".")
    _git(canonical_w, "commit", "-m", "workspace init with queue")

    # P/wksp -> W
    wksp_link = canonical_p / "wksp"
    wksp_link.symlink_to(os.path.relpath(canonical_w, canonical_p))
    _git(canonical_p, "add", ".")
    _git(canonical_p, "commit", "-m", "add wksp symlink")

    # Create permanent clone
    from clone_manager import create_clone
    result = create_clone(family, "P")
    assert result["CREATED"] == "yes", f"create_clone failed: {result}"

    clone_target = family / "clone" / "P"
    project_clone = clone_target / "P"

    # Find workspace clone
    ws_dirs = [d for d in clone_target.iterdir()
               if d.is_dir() and d.name != "P"
               and (d / ".git").exists()
               and (d / ".workspace").exists()]
    assert ws_dirs, "workspace clone not found"
    ws_clone = ws_dirs[0]

    branch = "issue-1-x"

    # Create branch in project clone
    main_sha_p = _main_head(project_clone)
    _git(project_clone, "checkout", "-b", branch)
    branch_base.record(project_clone, branch, main_sha_p)
    (project_clone / "feature.txt").write_text("new feature\n")
    _git(project_clone, "add", ".")
    _git(project_clone, "commit", "-m", "feat: add feature Refs #1")
    squash_marker.mark(project_clone, branch)

    # Create branch in workspace clone
    main_sha_w = _main_head(ws_clone)
    _git(ws_clone, "checkout", "-b", branch)
    branch_base.record(ws_clone, branch, main_sha_w)
    (ws_clone / "notes.md").write_text("work notes\n")
    _git(ws_clone, "add", ".")
    _git(ws_clone, "commit", "-m", "docs: work notes Refs #1")
    squash_marker.mark(ws_clone, branch)

    # Update queue with the branch name
    write_queue(ws_clone, Queue(
        items=[QueueItem(ref="R#1", title="Task", completed=False, active=True)],
        state=QueueState(branch=branch, issue_repo="R", status="active"),
    ))
    _git(ws_clone, "add", ".queue")
    _git(ws_clone, "commit", "-m", "chore: set queue branch")

    return family, canonical_p, canonical_w, clone_target, project_clone, ws_clone, branch


class TestCloneWorkEnd:

    def test_close_succeeds(self, clone_world):
        """Assertion 1: result.success"""
        family, canonical_p, canonical_w, clone_target, project_clone, ws_clone, branch = clone_world
        result = close(ws_clone)
        assert result.success, f"close failed: {result.errors}"

    def test_work_reaches_canonical_no_merges(self, clone_world):
        """Assertion 2: canonical P main has the project commit, canonical W main
        has the workspace commit, neither has merge commits."""
        family, canonical_p, canonical_w, clone_target, project_clone, ws_clone, branch = clone_world
        result = close(ws_clone)
        assert result.success, f"close failed: {result.errors}"

        p_show = subprocess.run(
            ["git", "-C", str(canonical_p), "show", "main:feature.txt"],
            capture_output=True, text=True,
        )
        assert p_show.returncode == 0, "feature.txt not on canonical P main"

        w_show = subprocess.run(
            ["git", "-C", str(canonical_w), "show", "main:notes.md"],
            capture_output=True, text=True,
        )
        assert w_show.returncode == 0, "notes.md not on canonical W main"

        assert _merge_count(canonical_p) == 0, "canonical P has merge commits"
        assert _merge_count(canonical_w) == 0, "canonical W has merge commits"

    def test_clone_structure_survives(self, clone_world):
        """Assertion 3: <family>/clone/P still exists with .slot and .permanent."""
        family, canonical_p, canonical_w, clone_target, project_clone, ws_clone, branch = clone_world
        close(ws_clone)
        assert clone_target.is_dir()
        assert (clone_target / ".slot").exists()
        assert (clone_target / ".permanent").exists()

    def test_no_landed_marker(self, clone_world):
        """Assertion 4: <family>/clone/P/.landed does NOT exist."""
        family, canonical_p, canonical_w, clone_target, project_clone, ws_clone, branch = clone_world
        close(ws_clone)
        assert not (clone_target / ".landed").exists(), \
            ".landed was written — permanent clone should not be marked for archive"

    def test_no_slot_ready_for_archive(self, clone_world):
        """Assertion 5: render output does not contain SLOT_READY_FOR_ARCHIVE."""
        family, canonical_p, canonical_w, clone_target, project_clone, ws_clone, branch = clone_world
        result = close(ws_clone)
        lines = render(result)
        archive_lines = [l for l in lines if "SLOT_READY_FOR_ARCHIVE" in l]
        assert archive_lines == [], \
            f"close offered to archive a permanent clone: {archive_lines}"

    def test_clone_main_equals_canonical_main(self, clone_world):
        """Assertion 6: after close, project clone's main equals canonical P main
        and workspace clone's main equals canonical W main."""
        family, canonical_p, canonical_w, clone_target, project_clone, ws_clone, branch = clone_world
        close(ws_clone)
        assert _main_head(project_clone) == _main_head(canonical_p), \
            "project clone main diverged from canonical"
        assert _main_head(ws_clone) == _main_head(canonical_w), \
            "workspace clone main diverged from canonical"

    def test_push_guard_blocks_clone(self, clone_world):
        """Assertion 7: git push from the project clone is refused by push-guard.py."""
        family, canonical_p, canonical_w, clone_target, project_clone, ws_clone, branch = clone_world
        verdict = _push_guard_hook("git push", project_clone)
        assert verdict.returncode == 2, \
            f"push-guard did not block (rc={verdict.returncode}): {verdict.stderr}"
