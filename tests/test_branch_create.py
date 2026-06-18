"""Tests for work-start/branch_create.py"""

import subprocess
from pathlib import Path
import pytest


BRANCH_CREATE = Path(__file__).parent.parent / "work-start" / "branch_create.py"


@pytest.fixture
def project_repo(tmp_path):
    """Create a project git repo with initial commit."""
    repo = tmp_path / "project"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=repo, check=True, capture_output=True)
    (repo / "README.md").write_text("# Project\n")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    return repo


@pytest.fixture
def workspace_repo(tmp_path):
    """Create a workspace git repo with initial commit."""
    repo = tmp_path / "workspace"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=repo, check=True, capture_output=True)
    (repo / "README.md").write_text("# Workspace\n")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    return repo


# ---------------------------------------------------------------------------
# create-branches subcommand
# ---------------------------------------------------------------------------

def test_create_branches_happy_path(project_repo, workspace_repo):
    """create-branches creates matching branches in both repos."""
    result = subprocess.run(
        ["python3", str(BRANCH_CREATE), "create-branches",
         str(project_repo), str(workspace_repo),
         "branch=issue-42-feature"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "CREATED=yes" in result.stdout

    # Verify project is on the new branch
    proj_branch = subprocess.run(
        ["git", "-C", str(project_repo), "branch", "--show-current"],
        capture_output=True, text=True,
    ).stdout.strip()
    assert proj_branch == "issue-42-feature"

    # Verify workspace is on the new branch
    ws_branch = subprocess.run(
        ["git", "-C", str(workspace_repo), "branch", "--show-current"],
        capture_output=True, text=True,
    ).stdout.strip()
    assert ws_branch == "issue-42-feature"


def test_create_branches_with_base(project_repo, workspace_repo):
    """create-branches from a specified base branch."""
    # Create a base branch with a commit
    subprocess.run(["git", "-C", str(project_repo), "checkout", "-b", "base-branch"],
                    check=True, capture_output=True)
    (project_repo / "base.txt").write_text("base work")
    subprocess.run(["git", "-C", str(project_repo), "add", "base.txt"],
                    check=True, capture_output=True)
    subprocess.run(["git", "-C", str(project_repo), "commit", "-m", "base work"],
                    check=True, capture_output=True)

    result = subprocess.run(
        ["python3", str(BRANCH_CREATE), "create-branches",
         str(project_repo), str(workspace_repo),
         "branch=issue-10-stacked", "base=base-branch"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "CREATED=yes" in result.stdout

    # base.txt should be present (branched from base-branch)
    assert (project_repo / "base.txt").exists()


def test_create_branches_rollback_on_workspace_failure(project_repo, tmp_path):
    """If workspace branch fails, project branch is rolled back."""
    # Use a non-git dir as workspace to force failure
    bad_ws = tmp_path / "not-a-repo"
    bad_ws.mkdir()

    result = subprocess.run(
        ["python3", str(BRANCH_CREATE), "create-branches",
         str(project_repo), str(bad_ws),
         "branch=issue-99-fail"],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "ERROR=workspace_branch_failed" in result.stdout

    # Project should NOT have the branch
    branches = subprocess.run(
        ["git", "-C", str(project_repo), "branch"],
        capture_output=True, text=True,
    ).stdout
    assert "issue-99-fail" not in branches


def test_create_branches_duplicate_name(project_repo, workspace_repo):
    """create-branches fails if branch already exists in project."""
    # Create branch first
    subprocess.run(["git", "-C", str(project_repo), "checkout", "-b", "issue-1-dup"],
                    check=True, capture_output=True)
    subprocess.run(["git", "-C", str(project_repo), "checkout", "main"],
                    check=True, capture_output=True)

    result = subprocess.run(
        ["python3", str(BRANCH_CREATE), "create-branches",
         str(project_repo), str(workspace_repo),
         "branch=issue-1-dup"],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "ERROR=project_branch_failed" in result.stdout


def test_create_branches_missing_branch_arg(project_repo, workspace_repo):
    """create-branches without branch= fails."""
    result = subprocess.run(
        ["python3", str(BRANCH_CREATE), "create-branches",
         str(project_repo), str(workspace_repo)],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "ERROR=missing_branch" in result.stdout


# ---------------------------------------------------------------------------
# commit-scaffold subcommand
# ---------------------------------------------------------------------------

def test_commit_scaffold_happy_path(workspace_repo):
    """commit-scaffold commits design files."""
    ws = workspace_repo
    subprocess.run(["git", "-C", str(ws), "checkout", "-b", "issue-5-scaffold"],
                    check=True, capture_output=True)

    # Create scaffold files
    design = ws / "design"
    design.mkdir()
    (design / ".meta").write_text("branch: issue-5-scaffold\n")
    (design / "JOURNAL.md").write_text("# Design Journal\n")

    result = subprocess.run(
        ["python3", str(BRANCH_CREATE), "commit-scaffold", str(ws),
         "branch=issue-5-scaffold"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "COMMITTED=yes" in result.stdout
    assert "PUSHED=no" in result.stdout  # no remote

    # Verify commit message
    log = subprocess.run(
        ["git", "-C", str(ws), "log", "-1", "--format=%s"],
        capture_output=True, text=True,
    ).stdout.strip()
    assert "init(issue-5-scaffold): scaffold workspace branch" in log


def test_commit_scaffold_missing_branch_arg(workspace_repo):
    """commit-scaffold without branch= fails."""
    result = subprocess.run(
        ["python3", str(BRANCH_CREATE), "commit-scaffold", str(workspace_repo)],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "ERROR=missing_branch" in result.stdout


def test_commit_scaffold_no_design_dir(workspace_repo):
    """commit-scaffold fails if design/ files don't exist."""
    ws = workspace_repo
    subprocess.run(["git", "-C", str(ws), "checkout", "-b", "issue-6-nodir"],
                    check=True, capture_output=True)

    result = subprocess.run(
        ["python3", str(BRANCH_CREATE), "commit-scaffold", str(ws),
         "branch=issue-6-nodir"],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "ERROR=" in result.stdout


# ---------------------------------------------------------------------------
# General tests
# ---------------------------------------------------------------------------

def test_unknown_subcommand():
    """Unknown subcommand fails."""
    result = subprocess.run(
        ["python3", str(BRANCH_CREATE), "unknown"],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "ERROR=unknown_subcommand" in result.stdout


def test_missing_subcommand():
    """No subcommand fails."""
    result = subprocess.run(
        ["python3", str(BRANCH_CREATE)],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "ERROR=missing_subcommand" in result.stdout


def test_create_branches_missing_args():
    """create-branches without project/workspace args fails."""
    result = subprocess.run(
        ["python3", str(BRANCH_CREATE), "create-branches"],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "ERROR=missing_args" in result.stdout


def test_commit_scaffold_missing_workspace():
    """commit-scaffold without workspace arg fails."""
    result = subprocess.run(
        ["python3", str(BRANCH_CREATE), "commit-scaffold"],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "ERROR=missing_args" in result.stdout
