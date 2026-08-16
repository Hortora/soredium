"""Tests for work-end/branch_cleanup.py — scaffold cleanup and checkout_main."""

import subprocess
import sys
from pathlib import Path

import pytest

skill_dir = Path(__file__).parent.parent / "work-end"
sys.path.insert(0, str(skill_dir))

from branch_cleanup import checkout_main, cleanup_scaffold


def init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t.com"], capture_output=True)
    subprocess.run(["git", "-C", str(path), "commit", "--allow-empty", "-m", "init"],
                   capture_output=True, check=True)
    return path


class TestCleanupScaffold:
    def test_removes_meta_and_journal(self, tmp_path):
        ws = init_repo(tmp_path / "workspace")
        design = ws / "design"
        design.mkdir()
        (design / ".meta").write_text("branch: test\n")
        (design / "JOURNAL.md").write_text("# Journal\n")
        subprocess.run(["git", "-C", str(ws), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(ws), "commit", "-m", "scaffold"], capture_output=True)
        result = cleanup_scaffold(str(ws), {})
        assert result == 0
        assert not (design / ".meta").exists()
        assert not (design / "JOURNAL.md").exists()

    def test_removes_epic_file(self, tmp_path):
        ws = init_repo(tmp_path / "workspace")
        design = ws / "design"
        design.mkdir()
        (design / ".meta").write_text("branch: test\n")
        (design / ".epic").write_text("## Issue\nrepo#100\nType: epic\n")
        (design / "JOURNAL.md").write_text("# Journal\n")
        subprocess.run(["git", "-C", str(ws), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(ws), "commit", "-m", "scaffold"], capture_output=True)
        result = cleanup_scaffold(str(ws), {})
        assert result == 0
        assert not (design / ".meta").exists()
        assert not (design / ".epic").exists()
        assert not (design / "JOURNAL.md").exists()

    def test_no_scaffold_files(self, tmp_path):
        ws = init_repo(tmp_path / "workspace")
        result = cleanup_scaffold(str(ws), {})
        assert result == 0

    def test_only_epic_file(self, tmp_path):
        ws = init_repo(tmp_path / "workspace")
        design = ws / "design"
        design.mkdir()
        (design / ".epic").write_text("## Issue\nrepo#100\nType: epic\n")
        subprocess.run(["git", "-C", str(ws), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(ws), "commit", "-m", "scaffold"], capture_output=True)
        result = cleanup_scaffold(str(ws), {})
        assert result == 0
        assert not (design / ".epic").exists()


def _init_bare(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--bare", str(path)], capture_output=True, check=True)
    return path


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", "-C", str(repo)] + list(args),
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"git {' '.join(args)} failed: {r.stderr}"
    return r.stdout.strip()


class TestCheckoutMainTopology:
    def test_checkout_main_uses_upstream_for_fork_model(self, tmp_path):
        """checkout_main should pull from upstream (blessed) for fork repos."""
        blessed = _init_bare(tmp_path / "blessed.git")
        fork = _init_bare(tmp_path / "fork.git")
        project = init_repo(tmp_path / "project")
        workspace = init_repo(tmp_path / "workspace")

        _git(project, "remote", "add", "origin", str(fork))
        _git(project, "remote", "add", "upstream", str(blessed))
        _git(project, "push", "origin", "main")
        _git(project, "push", "upstream", "main")

        ws_remote = _init_bare(tmp_path / "ws_remote.git")
        _git(workspace, "remote", "add", "origin", str(ws_remote))
        _git(workspace, "push", "origin", "main")

        # Push a commit to upstream only (not to origin/fork)
        other = tmp_path / "other"
        subprocess.run(["git", "clone", str(blessed), str(other)],
                       capture_output=True, check=True)
        _git(other, "config", "user.email", "other@test.com")
        _git(other, "config", "user.name", "Other")
        (other / "upstream-only.txt").write_text("from upstream\n")
        _git(other, "add", "upstream-only.txt")
        _git(other, "commit", "-m", "feat: upstream only")
        _git(other, "push", "origin", "main")

        # Create branches so checkout_main has something to switch from
        _git(project, "checkout", "-b", "feature")
        _git(workspace, "checkout", "-b", "feature")

        result = checkout_main(str(project), str(workspace))
        assert result == 0

        log = _git(project, "log", "--oneline", "main")
        assert "feat: upstream only" in log

    def test_checkout_main_uses_origin_for_direct_model(self, tmp_path):
        """checkout_main should pull from origin for non-fork repos."""
        remote = _init_bare(tmp_path / "remote.git")
        project = init_repo(tmp_path / "project")
        workspace = init_repo(tmp_path / "workspace")

        _git(project, "remote", "add", "origin", str(remote))
        _git(project, "push", "origin", "main")

        ws_remote = _init_bare(tmp_path / "ws_remote.git")
        _git(workspace, "remote", "add", "origin", str(ws_remote))
        _git(workspace, "push", "origin", "main")

        _git(project, "checkout", "-b", "feature")
        _git(workspace, "checkout", "-b", "feature")

        result = checkout_main(str(project), str(workspace))
        assert result == 0

        branch = _git(project, "branch", "--show-current")
        assert branch == "main"
