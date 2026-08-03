"""Tests for project/safe_commit.py — branch-guarded workspace commits."""

import subprocess
import sys
from pathlib import Path

import pytest

skill_dir = Path(__file__).parent.parent / "project"
sys.path.insert(0, str(skill_dir))

import safe_commit


def init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@test.com"], capture_output=True)
    subprocess.run(["git", "commit", "--allow-empty", "-m", "init"], cwd=str(path),
                   capture_output=True, check=True)
    return path


class TestCommitToMain:
    """Test committing a file to main regardless of current branch."""

    def test_commit_on_main(self, tmp_path):
        """When already on main, commit directly."""
        repo = init_repo(tmp_path / "repo")
        (repo / "test.md").write_text("content")

        rc = safe_commit.commit_file_to_main(
            str(repo), "test.md", "test commit",
        )
        assert rc == 0
        # Verify file is committed
        result = subprocess.run(
            ["git", "-C", str(repo), "show", "HEAD:test.md"],
            capture_output=True, text=True,
        )
        assert result.stdout.strip() == "content"

    def test_commit_from_feature_branch(self, tmp_path):
        """When on a feature branch, switch to main, commit, switch back."""
        repo = init_repo(tmp_path / "repo")
        subprocess.run(["git", "-C", str(repo), "checkout", "-b", "feature"],
                       capture_output=True)
        (repo / "blog.md").write_text("blog entry")

        rc = safe_commit.commit_file_to_main(
            str(repo), "blog.md", "docs: add blog",
        )
        assert rc == 0

        # Should be back on feature branch
        result = subprocess.run(
            ["git", "-C", str(repo), "branch", "--show-current"],
            capture_output=True, text=True,
        )
        assert result.stdout.strip() == "feature"

        # File should be on main
        result = subprocess.run(
            ["git", "-C", str(repo), "show", "main:blog.md"],
            capture_output=True, text=True,
        )
        assert result.stdout.strip() == "blog entry"

        # File should NOT be on the feature branch (it was committed to main)
        result = subprocess.run(
            ["git", "-C", str(repo), "show", "feature:blog.md"],
            capture_output=True, text=True,
        )
        assert result.returncode != 0

    def test_preserves_feature_branch_changes(self, tmp_path):
        """Uncommitted changes on the feature branch survive the main commit."""
        repo = init_repo(tmp_path / "repo")
        subprocess.run(["git", "-C", str(repo), "checkout", "-b", "feature"],
                       capture_output=True)
        # Create a file on the feature branch (uncommitted)
        (repo / "feature-work.py").write_text("work in progress")
        # Create the file to commit to main
        (repo / "blog.md").write_text("blog entry")

        rc = safe_commit.commit_file_to_main(
            str(repo), "blog.md", "docs: add blog",
        )
        assert rc == 0

        # Feature branch uncommitted work should still be there
        assert (repo / "feature-work.py").exists()
        assert (repo / "feature-work.py").read_text() == "work in progress"

    def test_multiple_files(self, tmp_path):
        """Can commit multiple files to main."""
        repo = init_repo(tmp_path / "repo")
        subprocess.run(["git", "-C", str(repo), "checkout", "-b", "feature"],
                       capture_output=True)
        (repo / "blog").mkdir()
        (repo / "blog" / "entry.md").write_text("entry")
        (repo / "blog" / "INDEX.md").write_text("index")

        rc = safe_commit.commit_file_to_main(
            str(repo), "blog/entry.md,blog/INDEX.md", "docs: add blog",
        )
        assert rc == 0

        result = subprocess.run(
            ["git", "-C", str(repo), "show", "main:blog/entry.md"],
            capture_output=True, text=True,
        )
        assert result.stdout.strip() == "entry"

    def test_returns_error_if_file_missing(self, tmp_path):
        """Returns error code if the file doesn't exist."""
        repo = init_repo(tmp_path / "repo")
        rc = safe_commit.commit_file_to_main(
            str(repo), "nonexistent.md", "test",
        )
        assert rc != 0


class TestEnsureOnMain:
    """Test the ensure_on_main context manager."""

    def test_already_on_main(self, tmp_path):
        """No-op when already on main."""
        repo = init_repo(tmp_path / "repo")
        with safe_commit.ensure_on_main(str(repo)) as ok:
            assert ok is True
            result = subprocess.run(
                ["git", "-C", str(repo), "branch", "--show-current"],
                capture_output=True, text=True,
            )
            assert result.stdout.strip() == "main"

    def test_switches_from_feature_branch(self, tmp_path):
        """Switches to main, restores feature branch on exit."""
        repo = init_repo(tmp_path / "repo")
        subprocess.run(["git", "-C", str(repo), "checkout", "-b", "feat"],
                       capture_output=True)

        with safe_commit.ensure_on_main(str(repo)) as ok:
            assert ok is True
            result = subprocess.run(
                ["git", "-C", str(repo), "branch", "--show-current"],
                capture_output=True, text=True,
            )
            assert result.stdout.strip() == "main"

        # After context manager exits, should be back on feature
        result = subprocess.run(
            ["git", "-C", str(repo), "branch", "--show-current"],
            capture_output=True, text=True,
        )
        assert result.stdout.strip() == "feat"

    def test_restores_on_exception(self, tmp_path):
        """Restores branch even if exception is raised inside context."""
        repo = init_repo(tmp_path / "repo")
        subprocess.run(["git", "-C", str(repo), "checkout", "-b", "feat"],
                       capture_output=True)

        with pytest.raises(ValueError):
            with safe_commit.ensure_on_main(str(repo)) as ok:
                assert ok is True
                raise ValueError("test error")

        result = subprocess.run(
            ["git", "-C", str(repo), "branch", "--show-current"],
            capture_output=True, text=True,
        )
        assert result.stdout.strip() == "feat"
