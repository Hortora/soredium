"""Tests for handover/handover_commit.py"""

import subprocess
from pathlib import Path
import pytest


HANDOVER_COMMIT = Path(__file__).parent.parent / "handover" / "handover_commit.py"


@pytest.fixture
def workspace_repo(tmp_path):
    """Create a workspace git repo on main with HANDOFF.md."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    subprocess.run(["git", "init"], cwd=ws, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=ws, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=ws, check=True, capture_output=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=ws, check=True, capture_output=True)
    (ws / "README.md").write_text("# Workspace\n")
    subprocess.run(["git", "add", "README.md"], cwd=ws, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=ws, check=True, capture_output=True)
    return ws


# ---------------------------------------------------------------------------
# commit-to-main on main branch
# ---------------------------------------------------------------------------

def test_commit_to_main_on_main(workspace_repo):
    """commit-to-main on main branch commits HANDOFF.md directly."""
    ws = workspace_repo
    (ws / "HANDOFF.md").write_text("# Handover\n\nTest session.\n")

    result = subprocess.run(
        ["python3", str(HANDOVER_COMMIT), "commit-to-main", str(ws), "branch=main"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "COMMITTED=yes" in result.stdout
    assert "PUSHED=no" in result.stdout  # no remote

    # Verify commit
    log = subprocess.run(
        ["git", "-C", str(ws), "log", "-1", "--format=%s"],
        capture_output=True, text=True,
    )
    assert "session handover" in log.stdout


def test_commit_to_main_still_on_main(workspace_repo):
    """After commit-to-main on main, repo stays on main."""
    ws = workspace_repo
    (ws / "HANDOFF.md").write_text("# Handover\n")

    subprocess.run(
        ["python3", str(HANDOVER_COMMIT), "commit-to-main", str(ws), "branch=main"],
        capture_output=True, text=True,
    )

    branch = subprocess.run(
        ["git", "-C", str(ws), "branch", "--show-current"],
        capture_output=True, text=True,
    ).stdout.strip()
    assert branch == "main"


# ---------------------------------------------------------------------------
# commit-to-main from a branch
# ---------------------------------------------------------------------------

def test_commit_to_main_from_branch(workspace_repo):
    """commit-to-main from a branch stashes, commits on main, returns."""
    ws = workspace_repo
    subprocess.run(["git", "-C", str(ws), "checkout", "-b", "issue-42-test"],
                    check=True, capture_output=True)

    # Create branch-specific work
    (ws / "branch-work.txt").write_text("branch work")

    # Write HANDOFF.md
    (ws / "HANDOFF.md").write_text("# Handover from branch\n")

    result = subprocess.run(
        ["python3", str(HANDOVER_COMMIT), "commit-to-main", str(ws),
         "branch=issue-42-test"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "COMMITTED=yes" in result.stdout

    # Verify we're back on the original branch
    branch = subprocess.run(
        ["git", "-C", str(ws), "branch", "--show-current"],
        capture_output=True, text=True,
    ).stdout.strip()
    assert branch == "issue-42-test"


def test_commit_to_main_from_branch_preserves_work(workspace_repo):
    """commit-to-main from branch preserves uncommitted work via stash."""
    ws = workspace_repo
    subprocess.run(["git", "-C", str(ws), "checkout", "-b", "issue-99-wip"],
                    check=True, capture_output=True)

    # Create uncommitted file on the branch
    (ws / "wip.txt").write_text("work in progress")

    # Write HANDOFF.md
    (ws / "HANDOFF.md").write_text("# Handover\n")

    result = subprocess.run(
        ["python3", str(HANDOVER_COMMIT), "commit-to-main", str(ws),
         "branch=issue-99-wip"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0

    # wip.txt should still exist on the branch
    assert (ws / "wip.txt").exists()


def test_commit_to_main_handoff_on_main_branch(workspace_repo):
    """HANDOFF.md commit appears on main, not on the branch."""
    ws = workspace_repo
    subprocess.run(["git", "-C", str(ws), "checkout", "-b", "issue-7-feature"],
                    check=True, capture_output=True)

    (ws / "HANDOFF.md").write_text("# Session handover\n")

    subprocess.run(
        ["python3", str(HANDOVER_COMMIT), "commit-to-main", str(ws),
         "branch=issue-7-feature"],
        capture_output=True, text=True,
    )

    # Check main has the handover commit
    main_log = subprocess.run(
        ["git", "-C", str(ws), "log", "main", "-1", "--format=%s"],
        capture_output=True, text=True,
    ).stdout.strip()
    assert "session handover" in main_log


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

def test_missing_branch_arg():
    """commit-to-main without branch= fails."""
    result = subprocess.run(
        ["python3", str(HANDOVER_COMMIT), "commit-to-main", "/tmp"],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "ERROR=missing_branch" in result.stdout


def test_missing_workspace_arg():
    """commit-to-main without workspace arg fails."""
    result = subprocess.run(
        ["python3", str(HANDOVER_COMMIT), "commit-to-main"],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "ERROR=missing_args" in result.stdout


def test_unknown_subcommand():
    """Unknown subcommand fails."""
    result = subprocess.run(
        ["python3", str(HANDOVER_COMMIT), "unknown"],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "ERROR=unknown_subcommand" in result.stdout


def test_missing_subcommand():
    """No subcommand fails."""
    result = subprocess.run(
        ["python3", str(HANDOVER_COMMIT)],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "ERROR=missing_subcommand" in result.stdout
