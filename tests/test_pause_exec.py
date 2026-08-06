"""Tests for work-pause/pause_exec.py"""

import subprocess
from pathlib import Path
import pytest


PAUSE_EXEC = Path(__file__).parent.parent / "work-pause" / "pause_exec.py"


@pytest.fixture
def clean_git_repo(tmp_path):
    """Create a clean git repository."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    # Initial commit
    (repo / "README.md").write_text("test")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True)
    return repo


@pytest.fixture
def dirty_git_repo(clean_git_repo):
    """Create a repo with uncommitted changes."""
    (clean_git_repo / "file.txt").write_text("dirty")
    return clean_git_repo


@pytest.fixture
def workspace_with_stack(tmp_path):
    """Create workspace with design/.pause-stack directory."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    subprocess.run(["git", "init"], cwd=workspace, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=workspace, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=workspace, check=True)

    # Create design dir and stack
    design = workspace / "design"
    design.mkdir()
    stack = design / ".pause-stack"
    stack.write_text("")

    # Initial commit
    subprocess.run(["git", "add", "."], cwd=workspace, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=workspace, check=True)
    # Ensure we're on main (already default branch in modern git)
    subprocess.run(["git", "branch", "-M", "main"], cwd=workspace, check=True, capture_output=True)

    return workspace


# ---------------------------------------------------------------------------
# commit-wip tests
# ---------------------------------------------------------------------------

def test_commit_wip_clean_repo(clean_git_repo):
    """commit-wip on clean repo outputs COMMITTED=clean."""
    result = subprocess.run(
        ["python3", str(PAUSE_EXEC), "commit-wip", str(clean_git_repo), "message=WIP test"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0
    assert "COMMITTED=clean" in result.stdout


def test_commit_wip_dirty_repo(dirty_git_repo):
    """commit-wip on dirty repo creates WIP commit."""
    result = subprocess.run(
        ["python3", str(PAUSE_EXEC), "commit-wip", str(dirty_git_repo), "message=WIP test"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0
    assert "COMMITTED=yes" in result.stdout

    # Verify commit was created
    log_result = subprocess.run(
        ["git", "-C", str(dirty_git_repo), "log", "-1", "--format=%s"],
        capture_output=True,
        text=True
    )
    assert "WIP test" in log_result.stdout


def test_commit_wip_missing_message():
    """commit-wip without message= fails."""
    result = subprocess.run(
        ["python3", str(PAUSE_EXEC), "commit-wip", "/tmp"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 1
    assert "ERROR=missing_message" in result.stdout or "ERROR=missing_args" in result.stdout


def test_commit_wip_invalid_repo():
    """commit-wip on non-git directory fails."""
    result = subprocess.run(
        ["python3", str(PAUSE_EXEC), "commit-wip", "/tmp", "message=test"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 1
    assert "ERROR=git_status_failed" in result.stdout


# ---------------------------------------------------------------------------
# push-and-stack tests
# ---------------------------------------------------------------------------

def test_push_and_stack_happy_path(workspace_with_stack, clean_git_repo, tmp_path):
    """push-and-stack succeeds with repos on working branch."""
    # Create working branch in both repos
    workspace = workspace_with_stack
    project = clean_git_repo

    subprocess.run(["git", "-C", str(workspace), "checkout", "-b", "issue-1-test"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(project), "checkout", "-b", "issue-1-test"], check=True, capture_output=True)

    result = subprocess.run(
        ["python3", str(PAUSE_EXEC), "push-and-stack",
         str(workspace), str(project),
         "branch=issue-1-test", "issue=1", "base-branch=main"],
        capture_output=True,
        text=True
    )

    # Should succeed even though push fails (no remotes)
    assert result.returncode == 0
    assert "STACKED=yes" in result.stdout
    assert "PROJECT_PUSHED=no" in result.stdout  # no remote
    assert "WORKSPACE_PUSHED=no" in result.stdout  # no remote

    # Verify stack entry was added
    stack_file = workspace / "design" / ".pause-stack"
    stack_content = stack_file.read_text()
    assert "branch: issue-1-test" in stack_content
    assert "issue: 1" in stack_content


def test_push_and_stack_push_failures_non_fatal(workspace_with_stack, clean_git_repo):
    """push-and-stack succeeds even when push to origin fails."""
    workspace = workspace_with_stack
    project = clean_git_repo

    subprocess.run(["git", "-C", str(workspace), "checkout", "-b", "issue-2-test"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(project), "checkout", "-b", "issue-2-test"], check=True, capture_output=True)

    result = subprocess.run(
        ["python3", str(PAUSE_EXEC), "push-and-stack",
         str(workspace), str(project),
         "branch=issue-2-test", "issue=2", "base-branch=main"],
        capture_output=True,
        text=True
    )

    # Push failures are non-fatal
    assert result.returncode == 0
    assert "PROJECT_PUSHED=no" in result.stdout
    assert "WORKSPACE_PUSHED=no" in result.stdout
    assert "STACKED=yes" in result.stdout


def test_push_and_stack_missing_branch_arg():
    """push-and-stack without branch= fails."""
    result = subprocess.run(
        ["python3", str(PAUSE_EXEC), "push-and-stack", "/tmp/ws", "/tmp/proj", "issue=1"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 1
    assert "ERROR=" in result.stdout


def test_push_and_stack_missing_issue_arg():
    """push-and-stack without issue= fails."""
    result = subprocess.run(
        ["python3", str(PAUSE_EXEC), "push-and-stack", "/tmp/ws", "/tmp/proj", "branch=test"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 1
    assert "ERROR=" in result.stdout


def test_push_and_stack_checkout_main(workspace_with_stack, clean_git_repo):
    """push-and-stack checks out base-branch in project and main in workspace."""
    workspace = workspace_with_stack
    project = clean_git_repo

    subprocess.run(["git", "-C", str(workspace), "checkout", "-b", "issue-3-test"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(project), "checkout", "-b", "issue-3-test"], check=True, capture_output=True)

    result = subprocess.run(
        ["python3", str(PAUSE_EXEC), "push-and-stack",
         str(workspace), str(project),
         "branch=issue-3-test", "issue=3", "base-branch=main"],
        capture_output=True,
        text=True
    )

    assert result.returncode == 0

    # Verify repos are on correct branches
    ws_branch = subprocess.run(
        ["git", "-C", str(workspace), "branch", "--show-current"],
        capture_output=True,
        text=True
    ).stdout.strip()
    assert ws_branch == "main"

    proj_branch = subprocess.run(
        ["git", "-C", str(project), "branch", "--show-current"],
        capture_output=True,
        text=True
    ).stdout.strip()
    assert proj_branch == "main"


# ---------------------------------------------------------------------------
# General tests
# ---------------------------------------------------------------------------

def test_unknown_subcommand():
    """Unknown subcommand fails."""
    result = subprocess.run(
        ["python3", str(PAUSE_EXEC), "unknown"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 1
    assert "ERROR=unknown_subcommand" in result.stdout


def test_missing_subcommand():
    """No subcommand fails."""
    result = subprocess.run(
        ["python3", str(PAUSE_EXEC)],
        capture_output=True,
        text=True
    )
    assert result.returncode == 1
    assert "ERROR=missing_subcommand" in result.stdout


# ---------------------------------------------------------------------------
# Slot-aware pause tests (clone context)
# ---------------------------------------------------------------------------

@pytest.fixture
def slot_clone_setup(tmp_path):
    """Create a slot layout: original repos + clone-based slot.

    Layout:
      tmp_path/
        family/
          project/          <- original project repo
          worktrees/
            3/
              project/      <- git clone --shared of family/project
              work/         <- git clone --shared of workspace
        workspace/          <- original workspace repo (with design/.pause-stack)
    """
    family = tmp_path / "family"
    family.mkdir()

    # Original project repo
    orig_project = family / "project"
    orig_project.mkdir()
    subprocess.run(["git", "init"], cwd=orig_project, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=orig_project, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=orig_project, check=True)
    (orig_project / "README.md").write_text("project")
    subprocess.run(["git", "add", "."], cwd=orig_project, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=orig_project, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=orig_project, check=True, capture_output=True)

    # Original workspace repo
    orig_workspace = tmp_path / "workspace"
    orig_workspace.mkdir()
    subprocess.run(["git", "init"], cwd=orig_workspace, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=orig_workspace, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=orig_workspace, check=True)
    design = orig_workspace / "design"
    design.mkdir()
    (design / ".pause-stack").write_text("")
    subprocess.run(["git", "add", "."], cwd=orig_workspace, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=orig_workspace, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=orig_workspace, check=True, capture_output=True)

    # Create slot directory
    slot_dir = family / "worktrees" / "3"
    slot_dir.mkdir(parents=True)

    # Clone project into slot
    slot_project = slot_dir / "project"
    subprocess.run(
        ["git", "clone", "--shared", str(orig_project), str(slot_project)],
        check=True, capture_output=True,
    )
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=slot_project, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=slot_project, check=True)
    subprocess.run(["git", "-C", str(slot_project), "checkout", "-b", "issue-50-feature"],
                   check=True, capture_output=True)

    # Clone workspace into slot
    slot_workspace = slot_dir / "work"
    subprocess.run(
        ["git", "clone", "--shared", str(orig_workspace), str(slot_workspace)],
        check=True, capture_output=True,
    )
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=slot_workspace, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=slot_workspace, check=True)
    subprocess.run(["git", "-C", str(slot_workspace), "checkout", "-b", "issue-50-feature"],
                   check=True, capture_output=True)
    # Ensure design dir exists in workspace clone
    (slot_workspace / "design").mkdir(exist_ok=True)

    return {
        "family": family,
        "orig_project": orig_project,
        "orig_workspace": orig_workspace,
        "slot_dir": slot_dir,
        "slot_project": slot_project,
        "slot_workspace": slot_workspace,
    }


def test_pause_in_slot_writes_to_original_workspace(slot_clone_setup):
    """When pausing from a slot clone, stack entry should be written to
    the original workspace's pause stack, not the clone's."""
    s = slot_clone_setup

    result = subprocess.run(
        ["python3", str(PAUSE_EXEC), "push-and-stack",
         str(s["slot_workspace"]), str(s["slot_project"]),
         "branch=issue-50-feature", "issue=50", "base-branch=main"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "STACKED=yes" in result.stdout

    # Stack entry should be on the ORIGINAL workspace, not the clone
    orig_stack = s["orig_workspace"] / "design" / ".pause-stack"
    orig_content = orig_stack.read_text()
    assert "branch: issue-50-feature" in orig_content


def test_pause_in_slot_includes_slot_path(slot_clone_setup):
    """Stack entry written from a slot should include the slot directory path."""
    s = slot_clone_setup

    subprocess.run(
        ["python3", str(PAUSE_EXEC), "push-and-stack",
         str(s["slot_workspace"]), str(s["slot_project"]),
         "branch=issue-50-feature", "issue=50", "base-branch=main"],
        capture_output=True,
        text=True,
    )

    orig_stack = s["orig_workspace"] / "design" / ".pause-stack"
    orig_content = orig_stack.read_text()
    assert f"slot: {s['slot_dir']}" in orig_content


def test_pause_outside_slot_has_no_slot_field(workspace_with_stack, clean_git_repo):
    """When pausing from a normal (non-slot) repo, no slot field should appear."""
    workspace = workspace_with_stack
    project = clean_git_repo

    subprocess.run(["git", "-C", str(workspace), "checkout", "-b", "issue-1-test"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(project), "checkout", "-b", "issue-1-test"],
                   check=True, capture_output=True)

    subprocess.run(
        ["python3", str(PAUSE_EXEC), "push-and-stack",
         str(workspace), str(project),
         "branch=issue-1-test", "issue=1", "base-branch=main"],
        capture_output=True,
        text=True,
    )

    stack_file = workspace / "design" / ".pause-stack"
    content = stack_file.read_text()
    assert "slot:" not in content


class TestPauseIntent:
    def test_write_intent_creates_file(self, tmp_path):
        workspace = tmp_path / "workspace"
        (workspace / "design").mkdir(parents=True)
        result = subprocess.run(
            ["python3", str(PAUSE_EXEC), "write-intent",
             str(workspace), "branch=issue-42-foo"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "INTENT=written" in result.stdout
        intent = (workspace / "design" / ".pausing").read_text()
        assert "branch: issue-42-foo" in intent
        assert "wip_project: pending" in intent
        assert "checkout_main: pending" in intent

    def test_update_intent_marks_step_done(self, tmp_path):
        workspace = tmp_path / "workspace"
        (workspace / "design").mkdir(parents=True)
        subprocess.run(
            ["python3", str(PAUSE_EXEC), "write-intent",
             str(workspace), "branch=issue-42-foo"],
            capture_output=True, text=True, check=True,
        )
        result = subprocess.run(
            ["python3", str(PAUSE_EXEC), "update-intent",
             str(workspace), "step=wip_project"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        intent = (workspace / "design" / ".pausing").read_text()
        assert "wip_project: done" in intent
        assert "wip_workspace: pending" in intent

    def test_clear_intent_removes_file(self, tmp_path):
        workspace = tmp_path / "workspace"
        (workspace / "design").mkdir(parents=True)
        subprocess.run(
            ["python3", str(PAUSE_EXEC), "write-intent",
             str(workspace), "branch=issue-42-foo"],
            capture_output=True, text=True, check=True,
        )
        assert (workspace / "design" / ".pausing").exists()
        result = subprocess.run(
            ["python3", str(PAUSE_EXEC), "clear-intent", str(workspace)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert not (workspace / "design" / ".pausing").exists()

    def test_update_intent_noop_when_no_file(self, tmp_path):
        workspace = tmp_path / "workspace"
        (workspace / "design").mkdir(parents=True)
        result = subprocess.run(
            ["python3", str(PAUSE_EXEC), "update-intent",
             str(workspace), "step=wip_project"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
