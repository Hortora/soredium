"""Post-landing verification and queue-stamp reconciliation (#625)."""
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
    close, verify_landing_advanced, reconcile_stamps, CloseTarget,
)
from canonical_sync import LandResult
import squash_marker
import branch_base
import closure_refs


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


class TestVerifyLandingAdvanced:
    """#607: verify main's SHA advanced and history is linear after landing."""

    def test_no_errors_when_sha_advanced(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        before = _main_head(repo)
        (repo / "file.txt").write_text("content\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "work")
        after = _main_head(repo)

        target = CloseTarget(
            repo=repo, branch="main", base_branch="main",
            transport="direct", canonical=None, push_target="", mirror_target="",
            is_workspace=False)
        result = LandResult(repo=repo, branch="feature", sha=after, before_sha=before)

        errors = verify_landing_advanced({target: result})
        assert errors == []

    def test_error_when_sha_unchanged(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        sha = _main_head(repo)

        target = CloseTarget(
            repo=repo, branch="feature", base_branch="main",
            transport="direct", canonical=None, push_target="", mirror_target="",
            is_workspace=False)
        result = LandResult(repo=repo, branch="feature", sha=sha, before_sha=sha)

        errors = verify_landing_advanced({target: result})
        assert len(errors) == 1
        assert "did not advance" in errors[0]

    def test_skips_already_landed(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        sha = _main_head(repo)

        target = CloseTarget(
            repo=repo, branch="feature", base_branch="main",
            transport="direct", canonical=None, push_target="", mirror_target="",
            is_workspace=False)
        result = LandResult(repo=repo, branch="feature", sha=sha, before_sha=sha,
                            already_landed=True)

        errors = verify_landing_advanced({target: result})
        assert errors == []

    def test_error_on_empty_sha(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")

        target = CloseTarget(
            repo=repo, branch="feature", base_branch="main",
            transport="direct", canonical=None, push_target="", mirror_target="",
            is_workspace=False)
        result = LandResult(repo=repo, branch="feature", sha="", before_sha="abc")

        errors = verify_landing_advanced({target: result})
        assert len(errors) == 1
        assert "no SHA" in errors[0]


class TestReconcileStamps:
    """#603: flag stamps whose SHA is not reachable from main."""

    def test_no_warnings_when_stamps_valid(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        sha = _main_head(repo)
        closure_refs.record(repo, "issue-1-feat",
                            landed_sha=sha, base_branch="main", issue="R#1")

        warnings = reconcile_stamps(repo)
        assert warnings == []

    def test_warns_on_orphaned_stamp(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _git(repo, "checkout", "-b", "orphan")
        (repo / "orphan.txt").write_text("content\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "orphan commit")
        orphan_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
        _git(repo, "checkout", "main")

        closure_refs.record(repo, "issue-1-feat",
                            landed_sha=orphan_sha, base_branch="main", issue="R#1")

        warnings = reconcile_stamps(repo)
        assert len(warnings) == 1
        assert "not reachable" in warnings[0]
        assert "issue-1-feat" in warnings[0]

    def test_no_warnings_when_no_stamps(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        warnings = reconcile_stamps(repo)
        assert warnings == []

    def test_mixed_valid_and_orphaned(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        valid_sha = _main_head(repo)
        closure_refs.record(repo, "issue-1-feat",
                            landed_sha=valid_sha, base_branch="main", issue="R#1")

        _git(repo, "checkout", "-b", "orphan")
        (repo / "orphan.txt").write_text("content\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "orphan commit")
        orphan_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
        _git(repo, "checkout", "main")
        closure_refs.record(repo, "issue-2-broken",
                            landed_sha=orphan_sha, base_branch="main", issue="R#2")

        warnings = reconcile_stamps(repo)
        assert len(warnings) == 1
        assert "issue-2-broken" in warnings[0]


class TestEndToEndVerification:
    """Both verifications run during a real ceremony."""

    @pytest.fixture
    def clone_world(self, tmp_path):
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

        write_queue(ws_clone, Queue(
            items=[QueueItem(ref="R#1", title="Task", completed=False, active=True)],
            state=QueueState(branch=branch, issue_repo="R", status="active"),
        ))
        _git(ws_clone, "add", ".queue")
        if subprocess.run(["git", "-C", str(ws_clone), "diff", "--cached", "--quiet"],
                          capture_output=True).returncode != 0:
            _git(ws_clone, "commit", "-m", "chore: set queue branch")

        return family, canonical_p, canonical_w, clone_target, project_clone, ws_clone, branch

    def test_ceremony_succeeds_with_valid_landing(self, clone_world):
        family, canonical_p, canonical_w, clone_target, project_clone, ws_clone, branch = clone_world
        result = close(ws_clone)
        assert result.success, f"close failed: {result.errors}"
        assert not any("not reachable" in w for w in result.warnings)
