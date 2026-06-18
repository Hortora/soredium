"""Tests for work-resume/resume_exec.py."""

import subprocess
import pytest
from pathlib import Path


@pytest.fixture
def resume_exec(tmp_path):
    """Return path to resume_exec.py script."""
    script_path = Path(__file__).parent.parent / "work-resume" / "resume_exec.py"
    assert script_path.exists(), f"resume_exec.py not found at {script_path}"
    return str(script_path)


@pytest.fixture
def dual_repos(tmp_path):
    """Create two git repos: project and workspace."""
    project = tmp_path / "project"
    workspace = tmp_path / "workspace"

    project.mkdir()
    workspace.mkdir()

    # Initialize both repos
    subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True)
    subprocess.run(["git", "init"], cwd=workspace, check=True, capture_output=True)

    # Configure git
    for repo in [project, workspace]:
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@test"], cwd=repo, check=True)

    # Create initial commits on main
    for repo in [project, workspace]:
        (repo / "file.txt").write_text("initial")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=repo, check=True)

    return {"project": str(project), "workspace": str(workspace)}


def run_script(resume_exec, *args):
    """Run resume_exec.py and return (exit_code, stdout, stderr)."""
    result = subprocess.run(
        ["python3", resume_exec, *args],
        capture_output=True,
        text=True
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


class TestCheckoutBranches:
    """Tests for checkout-branches subcommand."""

    def test_checkout_existing_branch(self, resume_exec, dual_repos):
        """Checkout should succeed when branch exists in both repos."""
        # Create branch in both repos
        for repo in [dual_repos["project"], dual_repos["workspace"]]:
            subprocess.run(["git", "checkout", "-b", "feature"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "checkout", "main"], cwd=repo, check=True, capture_output=True)

        # Checkout via script
        exit_code, stdout, stderr = run_script(
            resume_exec,
            "checkout-branches",
            dual_repos["project"],
            dual_repos["workspace"],
            "branch=feature"
        )

        assert exit_code == 0
        assert stdout == "CHECKED_OUT=yes"

        # Verify both repos are on feature branch
        for repo in [dual_repos["project"], dual_repos["workspace"]]:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=repo,
                capture_output=True,
                text=True,
                check=True
            )
            assert result.stdout.strip() == "feature"

    def test_checkout_missing_branch(self, resume_exec, dual_repos):
        """Checkout should fail when branch doesn't exist."""
        exit_code, stdout, stderr = run_script(
            resume_exec,
            "checkout-branches",
            dual_repos["project"],
            dual_repos["workspace"],
            "branch=nonexistent"
        )

        assert exit_code == 1
        assert stdout == "ERROR=branch_not_found"

    def test_checkout_missing_in_one_repo(self, resume_exec, dual_repos):
        """Checkout should fail when branch exists in only one repo."""
        # Create branch only in project
        subprocess.run(
            ["git", "checkout", "-b", "feature"],
            cwd=dual_repos["project"],
            check=True,
            capture_output=True
        )
        subprocess.run(
            ["git", "checkout", "main"],
            cwd=dual_repos["project"],
            check=True,
            capture_output=True
        )

        exit_code, stdout, stderr = run_script(
            resume_exec,
            "checkout-branches",
            dual_repos["project"],
            dual_repos["workspace"],
            "branch=feature"
        )

        assert exit_code == 1
        assert stdout == "ERROR=branch_not_found"


class TestRebase:
    """Tests for rebase subcommand."""

    def test_rebase_simple(self, resume_exec, dual_repos):
        """Rebase should succeed when no conflicts."""
        # Create commits on main in project
        (Path(dual_repos["project"]) / "main.txt").write_text("main work")
        subprocess.run(["git", "add", "."], cwd=dual_repos["project"], check=True)
        subprocess.run(["git", "commit", "-m", "Work on main"], cwd=dual_repos["project"], check=True)

        # Create feature branch from earlier point
        subprocess.run(["git", "checkout", "HEAD~1"], cwd=dual_repos["project"], check=True, capture_output=True)
        subprocess.run(["git", "checkout", "-b", "feature"], cwd=dual_repos["project"], check=True, capture_output=True)
        (Path(dual_repos["project"]) / "feature.txt").write_text("feature work")
        subprocess.run(["git", "add", "."], cwd=dual_repos["project"], check=True)
        subprocess.run(["git", "commit", "-m", "Work on feature"], cwd=dual_repos["project"], check=True)

        # Create matching branch in workspace
        subprocess.run(["git", "checkout", "-b", "feature"], cwd=dual_repos["workspace"], check=True, capture_output=True)

        # Rebase via script
        exit_code, stdout, stderr = run_script(
            resume_exec,
            "rebase",
            dual_repos["project"],
            dual_repos["workspace"],
            "base-branch=main"
        )

        assert exit_code == 0
        assert stdout == "REBASED=yes"

    def test_rebase_already_up_to_date(self, resume_exec, dual_repos):
        """Rebase should report skipped when already up to date."""
        # Create feature branch at same point as main
        for repo in [dual_repos["project"], dual_repos["workspace"]]:
            subprocess.run(["git", "checkout", "-b", "feature"], cwd=repo, check=True, capture_output=True)

        # Rebase via script
        exit_code, stdout, stderr = run_script(
            resume_exec,
            "rebase",
            dual_repos["project"],
            dual_repos["workspace"],
            "base-branch=main"
        )

        assert exit_code == 0
        assert stdout == "REBASED=skipped"

    def test_rebase_conflict(self, resume_exec, dual_repos):
        """Rebase should report conflict when it occurs."""
        # Create conflicting commits
        # On main: modify file.txt
        (Path(dual_repos["project"]) / "file.txt").write_text("main version")
        subprocess.run(["git", "add", "."], cwd=dual_repos["project"], check=True)
        subprocess.run(["git", "commit", "-m", "Main change"], cwd=dual_repos["project"], check=True)

        # On feature branch: modify same file differently
        subprocess.run(["git", "checkout", "HEAD~1"], cwd=dual_repos["project"], check=True, capture_output=True)
        subprocess.run(["git", "checkout", "-b", "feature"], cwd=dual_repos["project"], check=True, capture_output=True)
        (Path(dual_repos["project"]) / "file.txt").write_text("feature version")
        subprocess.run(["git", "add", "."], cwd=dual_repos["project"], check=True)
        subprocess.run(["git", "commit", "-m", "Feature change"], cwd=dual_repos["project"], check=True)

        # Create matching branch in workspace
        subprocess.run(["git", "checkout", "-b", "feature"], cwd=dual_repos["workspace"], check=True, capture_output=True)

        # Rebase via script
        exit_code, stdout, stderr = run_script(
            resume_exec,
            "rebase",
            dual_repos["project"],
            dual_repos["workspace"],
            "base-branch=main"
        )

        assert exit_code == 1
        assert stdout == "ERROR=rebase_conflict"

        # Clean up conflict state
        subprocess.run(["git", "rebase", "--abort"], cwd=dual_repos["project"], check=True, capture_output=True)


class TestResetWip:
    """Tests for reset-wip subcommand."""

    def test_reset_wip_both_repos(self, resume_exec, dual_repos):
        """Reset should work when both repos have WIP commits."""
        # Create WIP commits in both repos
        for repo in [dual_repos["project"], dual_repos["workspace"]]:
            (Path(repo) / "wip.txt").write_text("wip work")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "WIP: work in progress"], cwd=repo, check=True)

        # Reset via script
        exit_code, stdout, stderr = run_script(
            resume_exec,
            "reset-wip",
            dual_repos["project"],
            dual_repos["workspace"]
        )

        assert exit_code == 0
        assert stdout == "RESET=yes"

        # Verify commits were reset but files remain
        for repo in [dual_repos["project"], dual_repos["workspace"]]:
            # Check that HEAD is now Initial commit
            result = subprocess.run(
                ["git", "log", "-1", "--format=%s"],
                cwd=repo,
                capture_output=True,
                text=True,
                check=True
            )
            assert result.stdout.strip() == "Initial"

            # Check that wip.txt still exists as unstaged change
            assert (Path(repo) / "wip.txt").exists()

    def test_reset_wip_no_wip_commits(self, resume_exec, dual_repos):
        """Reset should report no when no WIP commits present."""
        exit_code, stdout, stderr = run_script(
            resume_exec,
            "reset-wip",
            dual_repos["project"],
            dual_repos["workspace"]
        )

        assert exit_code == 0
        assert stdout == "RESET=no"

    def test_reset_wip_only_project(self, resume_exec, dual_repos):
        """Reset should work when only project has WIP commit."""
        # Create WIP commit only in project
        (Path(dual_repos["project"]) / "wip.txt").write_text("wip work")
        subprocess.run(["git", "add", "."], cwd=dual_repos["project"], check=True)
        subprocess.run(["git", "commit", "-m", "WIP: work in progress"], cwd=dual_repos["project"], check=True)

        # Reset via script
        exit_code, stdout, stderr = run_script(
            resume_exec,
            "reset-wip",
            dual_repos["project"],
            dual_repos["workspace"]
        )

        assert exit_code == 0
        assert stdout == "RESET=yes"

    def test_reset_wip_only_workspace(self, resume_exec, dual_repos):
        """Reset should work when only workspace has WIP commit."""
        # Create WIP commit only in workspace
        (Path(dual_repos["workspace"]) / "wip.txt").write_text("wip work")
        subprocess.run(["git", "add", "."], cwd=dual_repos["workspace"], check=True)
        subprocess.run(["git", "commit", "-m", "WIP: work in progress"], cwd=dual_repos["workspace"], check=True)

        # Reset via script
        exit_code, stdout, stderr = run_script(
            resume_exec,
            "reset-wip",
            dual_repos["project"],
            dual_repos["workspace"]
        )

        assert exit_code == 0
        assert stdout == "RESET=yes"


class TestArgParsing:
    """Tests for argument parsing and usage."""

    def test_no_arguments(self, resume_exec):
        """Should print usage when no arguments."""
        exit_code, stdout, stderr = run_script(resume_exec)
        assert exit_code == 1

    def test_unknown_command(self, resume_exec):
        """Should print usage for unknown command."""
        exit_code, stdout, stderr = run_script(resume_exec, "unknown")
        assert exit_code == 1
        assert "Unknown command" in stdout

    def test_checkout_wrong_arg_count(self, resume_exec):
        """Should print usage when wrong arg count for checkout."""
        exit_code, stdout, stderr = run_script(resume_exec, "checkout-branches", "/tmp")
        assert exit_code == 1
        assert "Usage:" in stdout

    def test_checkout_wrong_arg_format(self, resume_exec, dual_repos):
        """Should error when branch arg not in branch=<name> format."""
        exit_code, stdout, stderr = run_script(
            resume_exec,
            "checkout-branches",
            dual_repos["project"],
            dual_repos["workspace"],
            "feature"
        )
        assert exit_code == 1
        assert "branch=" in stdout

    def test_rebase_wrong_arg_count(self, resume_exec):
        """Should print usage when wrong arg count for rebase."""
        exit_code, stdout, stderr = run_script(resume_exec, "rebase", "/tmp")
        assert exit_code == 1
        assert "Usage:" in stdout

    def test_rebase_wrong_arg_format(self, resume_exec, dual_repos):
        """Should error when base-branch arg not in base-branch=<name> format."""
        exit_code, stdout, stderr = run_script(
            resume_exec,
            "rebase",
            dual_repos["project"],
            dual_repos["workspace"],
            "main"
        )
        assert exit_code == 1
        assert "base-branch=" in stdout

    def test_reset_wip_wrong_arg_count(self, resume_exec):
        """Should print usage when wrong arg count for reset-wip."""
        exit_code, stdout, stderr = run_script(resume_exec, "reset-wip", "/tmp")
        assert exit_code == 1
        assert "Usage:" in stdout
