"""
Tests for publish-blog/blog_publish.py
"""

import subprocess
import tempfile
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parent.parent / "publish-blog" / "blog_publish.py"


def test_copy_entry_success():
    """Test copy-entry copies file to destination."""
    with tempfile.TemporaryDirectory() as tmpdir:
        source = Path(tmpdir) / "source.md"
        source.write_text("# Test Entry\nContent here.")

        dest_dir = Path(tmpdir) / "dest"

        result = subprocess.run(
            ["python3", str(SCRIPT), "copy-entry", str(source), str(dest_dir)],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "COPIED=yes" in result.stdout

        dest_file = dest_dir / "source.md"
        assert dest_file.exists()
        assert dest_file.read_text() == "# Test Entry\nContent here."


def test_copy_entry_creates_dest_dir():
    """Test copy-entry creates destination directory if missing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        source = Path(tmpdir) / "entry.md"
        source.write_text("content")

        dest_dir = Path(tmpdir) / "nested" / "dest"
        assert not dest_dir.exists()

        result = subprocess.run(
            ["python3", str(SCRIPT), "copy-entry", str(source), str(dest_dir)],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert dest_dir.exists()
        assert (dest_dir / "entry.md").exists()


def test_copy_entry_source_not_found():
    """Test copy-entry returns ERROR=source_not_found for missing source."""
    with tempfile.TemporaryDirectory() as tmpdir:
        source = Path(tmpdir) / "missing.md"
        dest_dir = Path(tmpdir) / "dest"

        result = subprocess.run(
            ["python3", str(SCRIPT), "copy-entry", str(source), str(dest_dir)],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 1
        assert "ERROR=source_not_found" in result.stdout


def test_commit_destination_success():
    """Test commit-destination adds, commits, and attempts push."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir) / "repo"
        repo.mkdir()

        # Initialize git repo
        subprocess.run(["git", "-C", str(repo), "init"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"],
                       check=True, capture_output=True)

        # Create a file to commit
        entry = repo / "entry.md"
        entry.write_text("# Entry")

        result = subprocess.run(
            ["python3", str(SCRIPT), "commit-destination", str(repo),
             "files=entry.md", "message=test commit"],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        lines = result.stdout.strip().splitlines()
        assert "COMMITTED=yes" in lines
        # Push will fail (no remote), but that's non-fatal
        assert "PUSHED=no" in lines

        # Verify commit exists
        log_result = subprocess.run(
            ["git", "-C", str(repo), "log", "--oneline"],
            capture_output=True,
            text=True,
        )
        assert "test commit" in log_result.stdout


def test_commit_destination_multiple_files():
    """Test commit-destination handles multiple files in CSV."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir) / "repo"
        repo.mkdir()

        subprocess.run(["git", "-C", str(repo), "init"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"],
                       check=True, capture_output=True)

        # Create multiple files
        (repo / "entry1.md").write_text("# Entry 1")
        (repo / "entry2.md").write_text("# Entry 2")

        result = subprocess.run(
            ["python3", str(SCRIPT), "commit-destination", str(repo),
             "files=entry1.md,entry2.md", "message=multi-file commit"],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "COMMITTED=yes" in result.stdout

        # Verify both files committed
        status_result = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain"],
            capture_output=True,
            text=True,
        )
        assert status_result.stdout == ""  # Clean working tree


def test_remove_source_success():
    """Test remove-source removes files and commits."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir) / "repo"
        repo.mkdir()

        # Initialize repo with files
        subprocess.run(["git", "-C", str(repo), "init"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"],
                       check=True, capture_output=True)

        entry = repo / "entry.md"
        entry.write_text("# Entry")
        subprocess.run(["git", "-C", str(repo), "add", "entry.md"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "initial"],
                       check=True, capture_output=True)

        # Remove the file
        result = subprocess.run(
            ["python3", str(SCRIPT), "remove-source", str(repo), "files=entry.md"],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "REMOVED=1" in result.stdout

        # Verify file removed from working tree
        assert not entry.exists()

        # Verify removal committed
        log_result = subprocess.run(
            ["git", "-C", str(repo), "log", "--oneline"],
            capture_output=True,
            text=True,
        )
        assert "remove published blog entries" in log_result.stdout


def test_remove_source_multiple_files():
    """Test remove-source handles multiple files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir) / "repo"
        repo.mkdir()

        subprocess.run(["git", "-C", str(repo), "init"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"],
                       check=True, capture_output=True)

        # Create and commit multiple files
        (repo / "entry1.md").write_text("# Entry 1")
        (repo / "entry2.md").write_text("# Entry 2")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "initial"],
                       check=True, capture_output=True)

        result = subprocess.run(
            ["python3", str(SCRIPT), "remove-source", str(repo),
             "files=entry1.md,entry2.md"],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "REMOVED=2" in result.stdout

        assert not (repo / "entry1.md").exists()
        assert not (repo / "entry2.md").exists()


def test_invalid_subcommand():
    """Test unknown subcommand returns error."""
    result = subprocess.run(
        ["python3", str(SCRIPT), "unknown"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "Unknown subcommand" in result.stderr


def test_copy_entry_missing_args():
    """Test copy-entry with missing args shows usage."""
    result = subprocess.run(
        ["python3", str(SCRIPT), "copy-entry"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "Usage" in result.stderr


def test_commit_destination_invalid_format():
    """Test commit-destination validates argument format."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = subprocess.run(
            ["python3", str(SCRIPT), "commit-destination", tmpdir,
             "invalid", "message=test"],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 1
        assert "must be files=" in result.stderr


def test_remove_source_invalid_format():
    """Test remove-source validates argument format."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = subprocess.run(
            ["python3", str(SCRIPT), "remove-source", tmpdir, "invalid"],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 1
        assert "must be files=" in result.stderr
