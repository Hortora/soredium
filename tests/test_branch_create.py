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

    # Create scaffold files at workspace root
    (ws / ".plan").write_text("# Work Plan — issue-5\n\n## State\nbranch: issue-5-scaffold\nstate: scaffolded\n\n## Queue\n(empty)\n")
    (ws / "JOURNAL.md").write_text("# Design Journal\n")

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


def test_commit_scaffold_includes_plan_file(workspace_repo):
    """commit-scaffold includes .plan (unified format)."""
    ws = workspace_repo
    subprocess.run(["git", "-C", str(ws), "checkout", "-b", "issue-99-epic"],
                    check=True, capture_output=True)

    (ws / ".plan").write_text("# Work Plan — issue-99\n\n## State\nbranch: issue-99-epic\nstate: scaffolded\n\n## Queue\n- [ ] #99 — Epic ← active\n")
    (ws / "JOURNAL.md").write_text("# Design Journal\n")

    result = subprocess.run(
        ["python3", str(BRANCH_CREATE), "commit-scaffold", str(ws),
         "branch=issue-99-epic"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "COMMITTED=yes" in result.stdout

    show = subprocess.run(
        ["git", "-C", str(ws), "show", "--name-only", "--format="],
        capture_output=True, text=True,
    ).stdout.strip()
    assert ".plan" in show


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


# ---------------------------------------------------------------------------
# sync-main subcommand
# ---------------------------------------------------------------------------

def _init_repo_with_bare(tmp_path, name, remote_name="origin"):
    """Create a repo cloned from a bare, simulating a remote."""
    bare = tmp_path / f".{name}-bare.git"
    bare.mkdir(parents=True)
    subprocess.run(["git", "init", "--bare", str(bare)], capture_output=True, check=True)
    repo = tmp_path / name
    subprocess.run(["git", "clone", str(bare), str(repo)], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@test.com"], capture_output=True)
    subprocess.run(["git", "-C", str(repo), "checkout", "-b", "main"], capture_output=True)
    (repo / "README.md").write_text(f"# {name}\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(repo), "push", "-u", "origin", "main"], capture_output=True)
    return repo, bare


def test_sync_main_single_remote(tmp_path):
    """sync-main with no fork: fetch + rebase only."""
    project, bare = _init_repo_with_bare(tmp_path, "project")
    workspace, _ = _init_repo_with_bare(tmp_path, "workspace")

    result = subprocess.run(
        ["python3", str(BRANCH_CREATE), "sync-main",
         str(project), str(workspace), "base=main"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "SYNCED=yes" in result.stdout


def test_sync_main_with_upstream_remote(tmp_path):
    """sync-main with upstream remote: fetch upstream, rebase, push origin."""
    blessed, blessed_bare = _init_repo_with_bare(tmp_path, "blessed")
    fork, fork_bare = _init_repo_with_bare(tmp_path, "fork")
    subprocess.run(
        ["git", "-C", str(fork), "remote", "add", "upstream", str(blessed_bare)],
        capture_output=True, check=True,
    )

    (blessed / "upstream-change.md").write_text("from upstream")
    subprocess.run(["git", "-C", str(blessed), "add", "."], capture_output=True)
    subprocess.run(["git", "-C", str(blessed), "commit", "-m", "upstream work"], capture_output=True)
    subprocess.run(["git", "-C", str(blessed), "push", "origin", "main"], capture_output=True)

    workspace, _ = _init_repo_with_bare(tmp_path, "workspace")

    result = subprocess.run(
        ["python3", str(BRANCH_CREATE), "sync-main",
         str(fork), str(workspace), "base=main"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "MODEL=upstream" in result.stdout
    if "SYNCED=yes" in result.stdout:
        assert (fork / "upstream-change.md").exists()
    else:
        assert "SYNCED=partial" in result.stdout
        assert "WARN=rebase_upstream_failed" in result.stdout


def test_sync_main_with_fork_remote(tmp_path):
    """sync-main with fork remote: fetch origin (blessed), rebase, push to fork."""
    blessed, blessed_bare = _init_repo_with_bare(tmp_path, "blessed")
    fork_bare = tmp_path / ".fork-bare.git"
    fork_bare.mkdir()
    subprocess.run(["git", "init", "--bare", str(fork_bare)], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(blessed), "remote", "add", "fork", str(fork_bare)],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(blessed), "push", "fork", "main"],
        capture_output=True,
    )

    workspace, _ = _init_repo_with_bare(tmp_path, "workspace")

    result = subprocess.run(
        ["python3", str(BRANCH_CREATE), "sync-main",
         str(blessed), str(workspace), "base=main"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "SYNCED=yes" in result.stdout
    assert "MODEL=fork" in result.stdout


def test_sync_main_missing_args():
    """sync-main without enough args fails."""
    result = subprocess.run(
        ["python3", str(BRANCH_CREATE), "sync-main"],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "ERROR=missing_args" in result.stdout


def test_sync_main_network_failure_non_fatal(tmp_path):
    """sync-main with unreachable remote warns but does not fail."""
    project, _ = _init_repo_with_bare(tmp_path, "project")
    workspace, _ = _init_repo_with_bare(tmp_path, "workspace")
    subprocess.run(
        ["git", "-C", str(project), "remote", "set-url", "origin", "https://unreachable.invalid/repo.git"],
        capture_output=True,
    )

    result = subprocess.run(
        ["python3", str(BRANCH_CREATE), "sync-main",
         str(project), str(workspace), "base=main"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "SYNCED=partial" in result.stdout
    assert "WARN=" in result.stdout
