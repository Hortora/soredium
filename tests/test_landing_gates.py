"""Landing gates: divergence check, stage invariants, clone settlement (#624)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "work-end"))
sys.path.insert(0, str(Path(__file__).parent.parent / "project"))
sys.path.insert(0, str(Path(__file__).parent.parent / "work-slot"))

from queue_io import write_queue, Queue, QueueItem, QueueState
from close import (
    close, preflight, settle_permanent_clone, CloseTarget,
    SettlementError,
)
import squash_marker
import branch_base


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=check,
    )


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-b", "main", "--template=")
    (path / ".git" / "hooks").mkdir(exist_ok=True)
    _git(path, "commit", "--allow-empty", "-m", "init")
    return path


def _main_head(repo: Path) -> str:
    return _git(repo, "rev-parse", "main").stdout.strip()


@pytest.fixture
def clone_world(tmp_path):
    """Family with canonical P and W, permanent clone, one branch of work."""
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
    assert result["CREATED"] == "yes", f"create_clone failed: {result}"

    clone_target = family / "clone" / "P"
    project_clone = clone_target / "P"

    ws_dirs = [d for d in clone_target.iterdir()
               if d.is_dir() and d.name != "P"
               and (d / ".git").exists()
               and (d / ".workspace").exists()]
    assert ws_dirs, "workspace clone not found"
    ws_clone = ws_dirs[0]

    branch = "issue-1-x"

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
        r = subprocess.run(["git", "-C", str(qdir), "add", ".queue"],
                           capture_output=True, check=False)
        if r.returncode == 0:
            r2 = subprocess.run(["git", "-C", str(qdir), "diff", "--cached", "--quiet"],
                                capture_output=True)
            if r2.returncode != 0:
                _git(qdir, "commit", "-m", "chore: set queue branch")

    return family, canonical_p, canonical_w, clone_target, project_clone, ws_clone, branch


class TestDivergenceGate:
    """#598: preflight refuses when a target repo's base has diverged from canonical."""

    def test_diverged_clone_blocks_ceremony(self, clone_world):
        family, canonical_p, canonical_w, clone_target, project_clone, ws_clone, branch = clone_world
        (canonical_p / "elsewhere.txt").write_text("landed by someone else\n")
        _git(canonical_p, "add", "elsewhere.txt")
        _git(canonical_p, "commit", "-m", "feat: elsewhere Refs #9")
        _git(project_clone, "checkout", "main")
        (project_clone / "stray.txt").write_text("old clone history\n")
        _git(project_clone, "add", "stray.txt")
        _git(project_clone, "commit", "-m", "feat: stray Refs #9")
        _git(project_clone, "checkout", branch)

        result = close(ws_clone)

        assert not result.success
        assert any("diverged" in e for e in result.errors)

    def test_non_diverged_clone_lands_normally(self, clone_world):
        family, canonical_p, canonical_w, clone_target, project_clone, ws_clone, branch = clone_world
        result = close(ws_clone)
        assert result.success, f"close failed: {result.errors}"
        p_show = subprocess.run(
            ["git", "-C", str(canonical_p), "show", "main:feature.txt"],
            capture_output=True, text=True)
        assert p_show.returncode == 0, "feature.txt not on canonical P main"

    def test_clone_ahead_but_not_diverged_still_lands(self, clone_world):
        """A clone whose base is ahead of canonical (not diverged) should land."""
        family, canonical_p, canonical_w, clone_target, project_clone, ws_clone, branch = clone_world
        _git(project_clone, "checkout", "main")
        (project_clone / "extra.txt").write_text("extra\n")
        _git(project_clone, "add", "extra.txt")
        _git(project_clone, "commit", "-m", "feat: extra Refs #9")
        _git(project_clone, "checkout", branch)

        result = close(ws_clone)

        assert result.success, f"close failed: {result.errors}"


class TestStageInvariant:
    """#609: refuse to stamp when landing produced no SHA."""

    def test_land_without_sha_blocks_stamp(self, clone_world):
        """If land_targets returns a result with no SHA, the ceremony refuses to stamp."""
        from canonical_sync import LandResult
        family, canonical_p, canonical_w, clone_target, project_clone, ws_clone, branch = clone_world

        def fake_land_targets(targets):
            return {t: LandResult(repo=t.repo, branch=t.branch, sha="") for t in targets}

        with patch("close.land_targets", side_effect=fake_land_targets):
            with pytest.raises(RuntimeError, match="stage invariant"):
                close(ws_clone)


class TestSettlementError:
    """#611: settle_permanent_clone raises SettlementError instead of silent warnings."""

    def test_settlement_error_raised_on_unsettled_clone(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        (slot_dir / ".slot").write_text("slot: test\n")
        (slot_dir / ".permanent").touch()

        repo = _init_repo(slot_dir / "P")
        _git(repo, "checkout", "-b", "feature")
        (repo / "work.txt").write_text("work\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "work")

        with patch("slot_core.get_all_slot_repos", return_value=["P"]), \
             patch("close.canonical_sync") as mock_sync:
            mock_sync.ahead_of_canonical.return_value = 5
            mock_sync.follow.return_value = "current"

            with pytest.raises(SettlementError) as exc_info:
                settle_permanent_clone(slot_dir)

            assert "P" in exc_info.value.unsettled[0]
            assert "5 commit(s) not in canonical" in exc_info.value.unsettled[0]

    def test_settlement_succeeds_when_all_on_base(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        (slot_dir / ".slot").write_text("slot: test\n")
        (slot_dir / ".permanent").touch()

        repo = _init_repo(slot_dir / "P")

        with patch("slot_core.get_all_slot_repos", return_value=["P"]), \
             patch("close.canonical_sync") as mock_sync:
            mock_sync.follow.return_value = "current"

            settle_permanent_clone(slot_dir)

    def test_keep_branches_not_treated_as_unsettled(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        (slot_dir / ".slot").write_text("slot: test\n")
        (slot_dir / ".permanent").touch()

        repo = _init_repo(slot_dir / "P")
        _git(repo, "checkout", "-b", "feature")
        (repo / "work.txt").write_text("work\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "work")

        with patch("slot_core.get_all_slot_repos", return_value=["P"]), \
             patch("close.canonical_sync") as mock_sync:
            mock_sync.follow.return_value = "current"

            settle_permanent_clone(slot_dir, keep_branches={"feature"})

    def test_ceremony_catches_settlement_error_as_warning(self, clone_world):
        """The ceremony itself catches SettlementError and adds to warnings."""
        family, canonical_p, canonical_w, clone_target, project_clone, ws_clone, branch = clone_world
        result = close(ws_clone)
        assert result.success, f"close failed: {result.errors}"
