"""Tests for handover/handover_commit.py — branch-scoped handoffs"""

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
# commit on main branch
# ---------------------------------------------------------------------------

def test_commit_on_main(workspace_repo):
    """commit on main branch commits HANDOFF.md directly."""
    ws = workspace_repo
    (ws / "HANDOFF.md").write_text("# Handover\n\nTest session.\n")

    result = subprocess.run(
        ["python3", str(HANDOVER_COMMIT), "commit", str(ws)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "COMMITTED=yes" in result.stdout

    log = subprocess.run(
        ["git", "-C", str(ws), "log", "-1", "--format=%s"],
        capture_output=True, text=True,
    )
    assert "session handover" in log.stdout


def test_commit_stays_on_main(workspace_repo):
    """After commit on main, repo stays on main."""
    ws = workspace_repo
    (ws / "HANDOFF.md").write_text("# Handover\n")

    subprocess.run(
        ["python3", str(HANDOVER_COMMIT), "commit", str(ws)],
        capture_output=True, text=True,
    )

    branch = subprocess.run(
        ["git", "-C", str(ws), "branch", "--show-current"],
        capture_output=True, text=True,
    ).stdout.strip()
    assert branch == "main"


# ---------------------------------------------------------------------------
# commit from a feature branch — stays on the branch
# ---------------------------------------------------------------------------

def test_commit_from_branch(workspace_repo):
    """commit from a branch commits on that branch, not main."""
    ws = workspace_repo
    subprocess.run(["git", "-C", str(ws), "checkout", "-b", "issue-42-test"],
                    check=True, capture_output=True)

    (ws / "HANDOFF.md").write_text("# Handover from branch\n")

    result = subprocess.run(
        ["python3", str(HANDOVER_COMMIT), "commit", str(ws)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "COMMITTED=yes" in result.stdout

    branch = subprocess.run(
        ["git", "-C", str(ws), "branch", "--show-current"],
        capture_output=True, text=True,
    ).stdout.strip()
    assert branch == "issue-42-test"


def test_commit_from_branch_handoff_on_branch(workspace_repo):
    """HANDOFF.md commit appears on the branch, not on main."""
    ws = workspace_repo
    subprocess.run(["git", "-C", str(ws), "checkout", "-b", "issue-7-feature"],
                    check=True, capture_output=True)

    (ws / "HANDOFF.md").write_text("# Session handover\n")

    subprocess.run(
        ["python3", str(HANDOVER_COMMIT), "commit", str(ws)],
        capture_output=True, text=True,
    )

    branch_log = subprocess.run(
        ["git", "-C", str(ws), "log", "issue-7-feature", "-1", "--format=%s"],
        capture_output=True, text=True,
    ).stdout.strip()
    assert "session handover" in branch_log

    main_log = subprocess.run(
        ["git", "-C", str(ws), "log", "main", "-1", "--format=%s"],
        capture_output=True, text=True,
    ).stdout.strip()
    assert "session handover" not in main_log


# ---------------------------------------------------------------------------
# commit-to-main legacy alias
# ---------------------------------------------------------------------------

def test_commit_to_main_legacy_alias(workspace_repo):
    """commit-to-main still works as a legacy alias — commits on current branch."""
    ws = workspace_repo
    subprocess.run(["git", "-C", str(ws), "checkout", "-b", "issue-99-wip"],
                    check=True, capture_output=True)

    (ws / "HANDOFF.md").write_text("# Handover\n")

    result = subprocess.run(
        ["python3", str(HANDOVER_COMMIT), "commit-to-main", str(ws),
         "branch=issue-99-wip"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "COMMITTED=yes" in result.stdout


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

def test_missing_workspace_arg():
    """commit without workspace arg fails."""
    result = subprocess.run(
        ["python3", str(HANDOVER_COMMIT), "commit"],
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


# ---------------------------------------------------------------------------
# Per-project HANDOFF filename
# ---------------------------------------------------------------------------

def test_commit_project_handoff(workspace_repo):
    """commit with file= commits per-project HANDOFF file on current branch."""
    ws = workspace_repo
    (ws / "HANDOFF-engine.md").write_text("# Engine handover\n")

    result = subprocess.run(
        ["python3", str(HANDOVER_COMMIT), "commit", str(ws),
         "file=HANDOFF-engine.md"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "COMMITTED=yes" in result.stdout

    show = subprocess.run(
        ["git", "-C", str(ws), "show", "HEAD:HANDOFF-engine.md"],
        capture_output=True, text=True,
    )
    assert "Engine handover" in show.stdout


def test_commit_project_handoff_from_branch(workspace_repo):
    """commit from branch with file= commits per-project HANDOFF on the branch."""
    ws = workspace_repo
    subprocess.run(["git", "-C", str(ws), "checkout", "-b", "issue-42-test"],
                    check=True, capture_output=True)

    (ws / "HANDOFF-engine.md").write_text("# Engine branch handover\n")

    result = subprocess.run(
        ["python3", str(HANDOVER_COMMIT), "commit", str(ws),
         "file=HANDOFF-engine.md"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "COMMITTED=yes" in result.stdout

    show = subprocess.run(
        ["git", "-C", str(ws), "show", "HEAD:HANDOFF-engine.md"],
        capture_output=True, text=True,
    )
    assert "Engine branch handover" in show.stdout


def test_default_file_is_handoff_md(workspace_repo):
    """Without file= param, commits HANDOFF.md (backward compat)."""
    ws = workspace_repo
    (ws / "HANDOFF.md").write_text("# Generic\n")

    result = subprocess.run(
        ["python3", str(HANDOVER_COMMIT), "commit", str(ws)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0

    show = subprocess.run(
        ["git", "-C", str(ws), "show", "HEAD:HANDOFF.md"],
        capture_output=True, text=True,
    )
    assert "Generic" in show.stdout
