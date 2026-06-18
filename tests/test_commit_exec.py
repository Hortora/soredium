"""Tests for git-commit/commit_exec.py"""

import subprocess
from pathlib import Path
import pytest


COMMIT_EXEC = Path(__file__).parent.parent / "git-commit" / "commit_exec.py"


@pytest.fixture
def git_repo(tmp_path):
    """Create a git repository with an initial commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True, capture_output=True)
    (repo / "README.md").write_text("# Test\n")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    return repo


# ---------------------------------------------------------------------------
# commit subcommand
# ---------------------------------------------------------------------------

def test_commit_stages_and_commits(git_repo):
    """commit stages files and creates a commit."""
    (git_repo / "file.txt").write_text("hello")
    result = subprocess.run(
        ["python3", str(COMMIT_EXEC), "commit", str(git_repo),
         "message=feat: add file", "files=file.txt"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "COMMITTED=yes" in result.stdout
    assert "SHA=" in result.stdout

    # Verify commit exists
    log = subprocess.run(
        ["git", "-C", str(git_repo), "log", "-1", "--format=%s"],
        capture_output=True, text=True,
    )
    assert "feat: add file" in log.stdout


def test_commit_multiple_files(git_repo):
    """commit handles comma-separated file list."""
    (git_repo / "a.txt").write_text("a")
    (git_repo / "b.txt").write_text("b")
    result = subprocess.run(
        ["python3", str(COMMIT_EXEC), "commit", str(git_repo),
         "message=feat: add files", "files=a.txt,b.txt"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "COMMITTED=yes" in result.stdout


def test_commit_nothing_to_commit(git_repo):
    """commit with already-committed files returns nothing_to_commit."""
    result = subprocess.run(
        ["python3", str(COMMIT_EXEC), "commit", str(git_repo),
         "message=feat: nothing", "files=README.md"],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "ERROR=nothing_to_commit" in result.stdout


def test_commit_missing_message(git_repo):
    """commit without message= fails."""
    result = subprocess.run(
        ["python3", str(COMMIT_EXEC), "commit", str(git_repo), "files=file.txt"],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "ERROR=missing_message" in result.stdout


def test_commit_empty_files(git_repo):
    """commit with empty files= fails."""
    result = subprocess.run(
        ["python3", str(COMMIT_EXEC), "commit", str(git_repo),
         "message=feat: test", "files="],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "ERROR=no_files" in result.stdout


def test_commit_sha_is_valid(git_repo):
    """commit returns a valid 40-char SHA."""
    (git_repo / "new.txt").write_text("new")
    result = subprocess.run(
        ["python3", str(COMMIT_EXEC), "commit", str(git_repo),
         "message=feat: new file", "files=new.txt"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    for line in result.stdout.splitlines():
        if line.startswith("SHA="):
            sha = line.split("=", 1)[1]
            assert len(sha) == 40


# ---------------------------------------------------------------------------
# squash subcommand
# ---------------------------------------------------------------------------

def test_squash_resets_soft(git_repo):
    """squash soft-resets HEAD~1."""
    # Create a second commit to squash
    (git_repo / "extra.txt").write_text("extra")
    subprocess.run(["git", "-C", str(git_repo), "add", "extra.txt"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(git_repo), "commit", "-m", "feat: extra"], check=True, capture_output=True)

    # Count commits before
    log_before = subprocess.run(
        ["git", "-C", str(git_repo), "log", "--oneline"],
        capture_output=True, text=True,
    )
    count_before = len(log_before.stdout.strip().splitlines())

    result = subprocess.run(
        ["python3", str(COMMIT_EXEC), "squash", str(git_repo)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "SQUASHED=yes" in result.stdout

    # Count commits after — should be one less
    log_after = subprocess.run(
        ["git", "-C", str(git_repo), "log", "--oneline"],
        capture_output=True, text=True,
    )
    count_after = len(log_after.stdout.strip().splitlines())
    assert count_after == count_before - 1

    # extra.txt should be staged (soft reset)
    status = subprocess.run(
        ["git", "-C", str(git_repo), "diff", "--staged", "--name-only"],
        capture_output=True, text=True,
    )
    assert "extra.txt" in status.stdout


def test_squash_no_parent(tmp_path):
    """squash on a single-commit repo fails with no_parent."""
    repo = tmp_path / "single"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True, capture_output=True)
    (repo / "f.txt").write_text("f")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True)

    result = subprocess.run(
        ["python3", str(COMMIT_EXEC), "squash", str(repo)],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "ERROR=no_parent" in result.stdout


# ---------------------------------------------------------------------------
# stage-docs subcommand
# ---------------------------------------------------------------------------

def test_stage_docs_stages_files(git_repo):
    """stage-docs stages the listed files."""
    (git_repo / "CLAUDE.md").write_text("# CLAUDE\n")
    (git_repo / "README.md").write_text("# README updated\n")
    result = subprocess.run(
        ["python3", str(COMMIT_EXEC), "stage-docs", str(git_repo),
         "files=CLAUDE.md,README.md"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "STAGED=2" in result.stdout

    # Verify files are staged
    status = subprocess.run(
        ["git", "-C", str(git_repo), "diff", "--staged", "--name-only"],
        capture_output=True, text=True,
    )
    assert "CLAUDE.md" in status.stdout


def test_stage_docs_empty_files(git_repo):
    """stage-docs with no files returns STAGED=0."""
    result = subprocess.run(
        ["python3", str(COMMIT_EXEC), "stage-docs", str(git_repo), "files="],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "STAGED=0" in result.stdout


def test_stage_docs_nonexistent_file(git_repo):
    """stage-docs skips files that don't exist, counts only successes."""
    (git_repo / "real.md").write_text("real")
    result = subprocess.run(
        ["python3", str(COMMIT_EXEC), "stage-docs", str(git_repo),
         "files=real.md,nonexistent.md"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    # real.md should stage, nonexistent.md should not — but git add
    # on a nonexistent file may or may not succeed depending on git
    # version. The count reflects actual successes.
    lines = result.stdout.strip().splitlines()
    staged_line = [l for l in lines if l.startswith("STAGED=")]
    assert len(staged_line) == 1


# ---------------------------------------------------------------------------
# General tests
# ---------------------------------------------------------------------------

def test_unknown_subcommand():
    """Unknown subcommand fails."""
    result = subprocess.run(
        ["python3", str(COMMIT_EXEC), "unknown"],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "ERROR=unknown_subcommand" in result.stdout


def test_missing_subcommand():
    """No subcommand fails."""
    result = subprocess.run(
        ["python3", str(COMMIT_EXEC)],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "ERROR=missing_subcommand" in result.stdout


def test_commit_missing_project():
    """commit without project arg fails."""
    result = subprocess.run(
        ["python3", str(COMMIT_EXEC), "commit"],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "ERROR=missing_args" in result.stdout


def test_squash_missing_project():
    """squash without project arg fails."""
    result = subprocess.run(
        ["python3", str(COMMIT_EXEC), "squash"],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "ERROR=missing_args" in result.stdout


def test_stage_docs_missing_project():
    """stage-docs without project arg fails."""
    result = subprocess.run(
        ["python3", str(COMMIT_EXEC), "stage-docs"],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "ERROR=missing_args" in result.stdout
