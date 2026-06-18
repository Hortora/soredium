#!/usr/bin/env python3
"""Tests for retro-issues/retro_create.py."""

import subprocess
import tempfile
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parent.parent / "retro-issues" / "retro_create.py"


@pytest.fixture
def temp_body_file():
    """Create a temporary body file for testing."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write("## Overview\nTest epic body\n")
        return f.name


@pytest.fixture
def temp_git_repo():
    """Create a temporary git repository for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir) / "test-repo"
        repo_path.mkdir()
        subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=repo_path,
            check=True,
            capture_output=True
        )
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=repo_path,
            check=True,
            capture_output=True
        )
        yield repo_path


class TestArgumentValidation:
    """Test argument validation for all subcommands."""

    def test_create_epic_missing_title(self, temp_body_file):
        """create-epic requires title=."""
        result = subprocess.run(
            ["python3", str(SCRIPT), "create-epic", "owner/repo",
             f"body-file={temp_body_file}"],
            capture_output=True,
            text=True
        )
        assert result.returncode != 0
        assert "ERROR=missing_title" in result.stdout

    def test_create_epic_missing_body_file(self):
        """create-epic requires body-file=."""
        result = subprocess.run(
            ["python3", str(SCRIPT), "create-epic", "owner/repo",
             "title=Test Epic"],
            capture_output=True,
            text=True
        )
        assert result.returncode != 0
        assert "ERROR=missing_body_file" in result.stdout

    def test_create_issue_missing_labels(self, temp_body_file):
        """create-issue requires labels=."""
        result = subprocess.run(
            ["python3", str(SCRIPT), "create-issue", "owner/repo",
             "title=Test Issue", f"body-file={temp_body_file}",
             "close=no"],
            capture_output=True,
            text=True
        )
        assert result.returncode != 0
        assert "ERROR=missing_labels" in result.stdout

    def test_create_issue_missing_close(self, temp_body_file):
        """create-issue requires close=."""
        result = subprocess.run(
            ["python3", str(SCRIPT), "create-issue", "owner/repo",
             "title=Test Issue", f"body-file={temp_body_file}",
             "labels=enhancement"],
            capture_output=True,
            text=True
        )
        assert result.returncode != 0
        assert "ERROR=missing_close" in result.stdout

    def test_create_issue_invalid_close_value(self, temp_body_file):
        """create-issue close= must be yes or no."""
        result = subprocess.run(
            ["python3", str(SCRIPT), "create-issue", "owner/repo",
             "title=Test Issue", f"body-file={temp_body_file}",
             "labels=enhancement", "close=maybe"],
            capture_output=True,
            text=True
        )
        assert result.returncode != 0
        assert "ERROR=invalid_close_value" in result.stdout

    def test_close_issue_missing_issue(self):
        """close-issue requires issue=."""
        result = subprocess.run(
            ["python3", str(SCRIPT), "close-issue", "owner/repo"],
            capture_output=True,
            text=True
        )
        assert result.returncode != 0
        assert "ERROR=missing_issue" in result.stdout

    def test_commit_mapping_missing_file(self, temp_git_repo):
        """commit-mapping requires file=."""
        result = subprocess.run(
            ["python3", str(SCRIPT), "commit-mapping", str(temp_git_repo)],
            capture_output=True,
            text=True
        )
        assert result.returncode != 0


class TestBodyFileValidation:
    """Test body file existence checks."""

    def test_create_epic_nonexistent_body_file(self):
        """create-epic fails if body file doesn't exist."""
        result = subprocess.run(
            ["python3", str(SCRIPT), "create-epic", "owner/repo",
             "title=Test Epic", "body-file=/tmp/nonexistent-12345.md"],
            capture_output=True,
            text=True
        )
        assert result.returncode != 0
        assert "ERROR=body_file_not_found" in result.stdout

    def test_create_issue_nonexistent_body_file(self):
        """create-issue fails if body file doesn't exist."""
        result = subprocess.run(
            ["python3", str(SCRIPT), "create-issue", "owner/repo",
             "title=Test Issue", "body-file=/tmp/nonexistent-12345.md",
             "labels=enhancement", "close=no"],
            capture_output=True,
            text=True
        )
        assert result.returncode != 0
        assert "ERROR=body_file_not_found" in result.stdout


class TestCommitMapping:
    """Test commit-mapping subcommand (fully testable without gh CLI)."""

    def test_commit_mapping_success(self, temp_git_repo):
        """commit-mapping adds and commits the file."""
        # Create a mapping file in the repo
        mapping_file = temp_git_repo / "docs" / "retro-issues.md"
        mapping_file.parent.mkdir(parents=True, exist_ok=True)
        mapping_file.write_text("# Retrospective Issue Mapping\n")

        result = subprocess.run(
            ["python3", str(SCRIPT), "commit-mapping", str(temp_git_repo),
             f"file={mapping_file}"],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        assert "COMMITTED=yes" in result.stdout

        # Verify commit exists
        log_result = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=temp_git_repo,
            capture_output=True,
            text=True,
            check=True
        )
        assert "docs: retrospective issue mapping" in log_result.stdout

    def test_commit_mapping_nonexistent_project(self):
        """commit-mapping fails if project path doesn't exist."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md') as f:
            f.write("# Test\n")
            f.flush()

            result = subprocess.run(
                ["python3", str(SCRIPT), "commit-mapping", "/tmp/nonexistent-repo-12345",
                 f"file={f.name}"],
                capture_output=True,
                text=True
            )

            assert result.returncode != 0
            assert "ERROR=project_not_found" in result.stdout

    def test_commit_mapping_nonexistent_file(self, temp_git_repo):
        """commit-mapping fails if file doesn't exist."""
        result = subprocess.run(
            ["python3", str(SCRIPT), "commit-mapping", str(temp_git_repo),
             "file=/tmp/nonexistent-file-12345.md"],
            capture_output=True,
            text=True
        )

        assert result.returncode != 0
        assert "ERROR=file_not_found" in result.stdout

    def test_commit_mapping_file_already_committed(self, temp_git_repo):
        """commit-mapping fails when there's nothing to commit (no changes)."""
        # Create and commit a file
        mapping_file = temp_git_repo / "docs" / "retro-issues.md"
        mapping_file.parent.mkdir(parents=True, exist_ok=True)
        mapping_file.write_text("# Retrospective Issue Mapping\n")

        subprocess.run(
            ["git", "add", str(mapping_file)],
            cwd=temp_git_repo,
            check=True,
            capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            cwd=temp_git_repo,
            check=True,
            capture_output=True
        )

        # Now try commit-mapping again with same file (no changes)
        result = subprocess.run(
            ["python3", str(SCRIPT), "commit-mapping", str(temp_git_repo),
             f"file={mapping_file}"],
            capture_output=True,
            text=True
        )

        # Should fail because git commit will fail with "nothing to commit"
        assert result.returncode != 0


class TestOutputFormat:
    """Test output format for each subcommand."""

    def test_commit_mapping_output_format(self, temp_git_repo):
        """commit-mapping outputs COMMITTED=yes on success."""
        mapping_file = temp_git_repo / "docs" / "retro-issues.md"
        mapping_file.parent.mkdir(parents=True, exist_ok=True)
        mapping_file.write_text("# Retrospective Issue Mapping\n")

        result = subprocess.run(
            ["python3", str(SCRIPT), "commit-mapping", str(temp_git_repo),
             f"file={mapping_file}"],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        assert result.stdout.strip() == "COMMITTED=yes"


class TestNoSubcommand:
    """Test behavior when no subcommand is provided."""

    def test_no_subcommand_fails(self):
        """Script fails if no subcommand is provided."""
        result = subprocess.run(
            ["python3", str(SCRIPT)],
            capture_output=True,
            text=True
        )
        assert result.returncode != 0


class TestUnknownSubcommand:
    """Test unknown subcommand handling."""

    def test_unknown_subcommand(self):
        """Script fails with ERROR on unknown subcommand."""
        result = subprocess.run(
            ["python3", str(SCRIPT), "bogus", "owner/repo"],
            capture_output=True,
            text=True
        )
        assert result.returncode != 0
        assert "ERROR=unknown_subcommand" in result.stdout
