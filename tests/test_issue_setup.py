"""Tests for issue-workflow/issue_setup.py"""

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Add parent directory to path so we can import the script
skill_dir = Path(__file__).parent.parent / "issue-workflow"
sys.path.insert(0, str(skill_dir))

import issue_setup


class TestCreateLabels:
    """Test create-labels subcommand."""

    def test_parse_args_create_labels(self):
        """Should parse create-labels with repo."""
        sys.argv = ["issue_setup.py", "create-labels", "owner/repo"]
        args = issue_setup.parse_args()
        assert args["subcommand"] == "create-labels"
        assert args["target"] == "owner/repo"

    def test_missing_repo_error(self, capsys):
        """Should error when repo is missing."""
        sys.argv = ["issue_setup.py", "create-labels"]
        with pytest.raises(SystemExit) as exc:
            issue_setup.main()
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "ERROR=missing_repo" in captured.out

    @patch("issue_setup.run_gh")
    def test_creates_all_labels(self, mock_gh, capsys):
        """Should create all standard + scale + complexity labels."""
        mock_gh.return_value = (0, "", "")  # Success for all
        sys.argv = ["issue_setup.py", "create-labels", "owner/repo"]
        issue_setup.main()
        captured = capsys.readouterr()
        # 7 standard + 5 scale + 3 complexity = 15 labels
        assert "CREATED=15" in captured.out
        assert mock_gh.call_count == 15

    @patch("issue_setup.run_gh")
    def test_skips_existing_labels(self, mock_gh, capsys):
        """Should count only newly created labels."""
        # First 5 succeed, rest fail (already exist)
        results = [(0, "", "")] * 5 + [(1, "", "already exists")] * 10
        mock_gh.side_effect = results
        sys.argv = ["issue_setup.py", "create-labels", "owner/repo"]
        issue_setup.main()
        captured = capsys.readouterr()
        assert "CREATED=5" in captured.out


class TestInstallHooks:
    """Test install-hooks subcommand."""

    def test_parse_args_install_hooks(self):
        """Should parse install-hooks with project path."""
        sys.argv = ["issue_setup.py", "install-hooks", "/path/to/project"]
        args = issue_setup.parse_args()
        assert args["subcommand"] == "install-hooks"
        assert args["target"] == "/path/to/project"

    def test_missing_project_error(self, capsys):
        """Should error when project path is missing."""
        sys.argv = ["issue_setup.py", "install-hooks"]
        with pytest.raises(SystemExit) as exc:
            issue_setup.main()
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "ERROR=missing_project_path" in captured.out

    def test_project_not_found_error(self, tmp_path, capsys):
        """Should error when project directory doesn't exist."""
        fake_path = tmp_path / "nonexistent"
        sys.argv = ["issue_setup.py", "install-hooks", str(fake_path)]
        with pytest.raises(SystemExit) as exc:
            issue_setup.main()
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "ERROR=project_not_found" in captured.out

    def test_hook_source_missing_error(self, tmp_path, capsys):
        """Should error when hook source file is missing."""
        # Create a project dir but no hook source
        project = tmp_path / "project"
        project.mkdir()
        # Initialize git repo
        subprocess.run(["git", "init"], cwd=project, check=True)

        # Temporarily break the hook source lookup
        with patch.object(Path, "is_file", return_value=False):
            sys.argv = ["issue_setup.py", "install-hooks", str(project)]
            with pytest.raises(SystemExit) as exc:
                issue_setup.main()
            assert exc.value.code == 1
            captured = capsys.readouterr()
            assert "ERROR=hook_source_missing" in captured.out

    def test_skips_if_hook_exists(self, tmp_path, capsys):
        """Should skip installation if hook already exists."""
        # Create project with git repo and existing hook
        project = tmp_path / "project"
        project.mkdir()
        subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True)

        githooks = project / ".githooks"
        githooks.mkdir()
        hook_dest = githooks / "commit-msg"
        hook_dest.write_text("#!/bin/bash\necho existing\n")

        sys.argv = ["issue_setup.py", "install-hooks", str(project)]
        issue_setup.main()
        captured = capsys.readouterr()
        assert "INSTALLED=skipped" in captured.out

    def test_installs_hook_successfully(self, tmp_path, capsys):
        """Should install hook, set executable, configure git, and commit."""
        # Create project with git repo
        project = tmp_path / "project"
        project.mkdir()
        subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=project,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=project,
            check=True,
            capture_output=True,
        )

        sys.argv = ["issue_setup.py", "install-hooks", str(project)]
        issue_setup.main()
        captured = capsys.readouterr()
        assert "INSTALLED=yes" in captured.out

        # Verify hook was created and is executable
        hook_path = project / ".githooks" / "commit-msg"
        assert hook_path.exists()
        assert hook_path.stat().st_mode & 0o100  # Executable bit set

        # Verify git config was set
        result = subprocess.run(
            ["git", "config", "core.hooksPath"],
            cwd=project,
            capture_output=True,
            text=True,
            check=True,
        )
        assert result.stdout.strip() == ".githooks"

        # Verify hook was committed
        result = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=project,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "commit-msg hook" in result.stdout


class TestCreateEpic:
    """Test create-epic subcommand."""

    def test_parse_args_create_epic(self):
        """Should parse create-epic with all args."""
        sys.argv = [
            "issue_setup.py", "create-epic", "owner/repo",
            "title=Add feature X", "body-file=/tmp/body.md"
        ]
        args = issue_setup.parse_args()
        assert args["subcommand"] == "create-epic"
        assert args["target"] == "owner/repo"
        assert args["title"] == "Add feature X"
        assert args["body-file"] == "/tmp/body.md"

    def test_missing_title_error(self, tmp_path, capsys):
        """Should error when title is missing."""
        body = tmp_path / "body.md"
        body.write_text("Epic body")
        sys.argv = [
            "issue_setup.py", "create-epic", "owner/repo",
            "body-file=" + str(body)
        ]
        with pytest.raises(SystemExit) as exc:
            issue_setup.main()
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "ERROR=missing_title" in captured.out

    def test_body_file_not_found_error(self, capsys):
        """Should error when body file doesn't exist."""
        sys.argv = [
            "issue_setup.py", "create-epic", "owner/repo",
            "title=Epic Title", "body-file=/nonexistent/body.md"
        ]
        with pytest.raises(SystemExit) as exc:
            issue_setup.main()
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "ERROR=body_file_not_found" in captured.out

    @patch("issue_setup.run_gh")
    def test_gh_command_failure(self, mock_gh, tmp_path, capsys):
        """Should error when gh command fails."""
        body = tmp_path / "body.md"
        body.write_text("Epic body")
        mock_gh.return_value = (1, "", "gh: not authenticated")
        sys.argv = [
            "issue_setup.py", "create-epic", "owner/repo",
            "title=Epic Title", "body-file=" + str(body)
        ]
        with pytest.raises(SystemExit) as exc:
            issue_setup.main()
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "ERROR=gh_failed" in captured.out

    @patch("issue_setup.run_gh")
    def test_creates_epic_successfully(self, mock_gh, tmp_path, capsys):
        """Should create epic and extract issue number."""
        body = tmp_path / "body.md"
        body.write_text("Epic body content")
        mock_gh.return_value = (
            0,
            "https://github.com/owner/repo/issues/42\n",
            ""
        )
        sys.argv = [
            "issue_setup.py", "create-epic", "owner/repo",
            "title=Add Terminal", "body-file=" + str(body)
        ]
        issue_setup.main()
        captured = capsys.readouterr()
        assert "ISSUE_NUMBER=42" in captured.out

        # Verify gh was called with correct args
        call_args = mock_gh.call_args[0][0]
        assert "issue" in call_args
        assert "create" in call_args
        assert "--title" in call_args
        assert "Add Terminal" in call_args
        assert "--label" in call_args
        assert "epic" in call_args


class TestCreateIssue:
    """Test create-issue subcommand."""

    def test_parse_args_create_issue(self):
        """Should parse create-issue with all args."""
        sys.argv = [
            "issue_setup.py", "create-issue", "owner/repo",
            "title=Fix bug Y", "body-file=/tmp/body.md",
            "labels=bug,scale: S,complexity: Low"
        ]
        args = issue_setup.parse_args()
        assert args["subcommand"] == "create-issue"
        assert args["target"] == "owner/repo"
        assert args["title"] == "Fix bug Y"
        assert args["labels"] == "bug,scale: S,complexity: Low"

    def test_missing_labels_error(self, tmp_path, capsys):
        """Should error when labels are missing."""
        body = tmp_path / "body.md"
        body.write_text("Issue body")
        sys.argv = [
            "issue_setup.py", "create-issue", "owner/repo",
            "title=Fix bug", "body-file=" + str(body)
        ]
        with pytest.raises(SystemExit) as exc:
            issue_setup.main()
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "ERROR=missing_labels" in captured.out

    @patch("issue_setup.run_gh")
    def test_creates_issue_with_multiple_labels(self, mock_gh, tmp_path, capsys):
        """Should create issue with comma-separated labels."""
        body = tmp_path / "body.md"
        body.write_text("Issue body content")
        mock_gh.return_value = (
            0,
            "https://github.com/owner/repo/issues/43\n",
            ""
        )
        sys.argv = [
            "issue_setup.py", "create-issue", "owner/repo",
            "title=Implement feature", "body-file=" + str(body),
            "labels=enhancement,scale: M,complexity: Med"
        ]
        issue_setup.main()
        captured = capsys.readouterr()
        assert "ISSUE_NUMBER=43" in captured.out

        # Verify labels were passed correctly
        call_args = mock_gh.call_args[0][0]
        assert "--label" in call_args
        # Count how many times --label appears (should be 3)
        label_count = call_args.count("--label")
        assert label_count == 3


class TestUpdateScope:
    """Test update-scope subcommand."""

    def test_parse_args_update_scope(self):
        """Should parse update-scope with all args."""
        sys.argv = [
            "issue_setup.py", "update-scope", "owner/repo",
            "epic=42", "body-file=/tmp/updated-body.md"
        ]
        args = issue_setup.parse_args()
        assert args["subcommand"] == "update-scope"
        assert args["target"] == "owner/repo"
        assert args["epic"] == "42"
        assert args["body-file"] == "/tmp/updated-body.md"

    def test_missing_epic_number_error(self, tmp_path, capsys):
        """Should error when epic number is missing."""
        body = tmp_path / "body.md"
        body.write_text("Updated body")
        sys.argv = [
            "issue_setup.py", "update-scope", "owner/repo",
            "body-file=" + str(body)
        ]
        with pytest.raises(SystemExit) as exc:
            issue_setup.main()
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "ERROR=missing_epic_number" in captured.out

    @patch("issue_setup.run_gh")
    def test_updates_epic_body(self, mock_gh, tmp_path, capsys):
        """Should update epic body with new content."""
        body = tmp_path / "updated-body.md"
        body.write_text("## Scope\n- [x] #43\n- [ ] #44\n")
        mock_gh.return_value = (0, "", "")
        sys.argv = [
            "issue_setup.py", "update-scope", "owner/repo",
            "epic=42", "body-file=" + str(body)
        ]
        issue_setup.main()
        captured = capsys.readouterr()
        assert "UPDATED=yes" in captured.out

        # Verify gh was called with correct args
        call_args = mock_gh.call_args[0][0]
        assert "issue" in call_args
        assert "edit" in call_args
        assert "42" in call_args
        assert "--body" in call_args


class TestMainEntryPoint:
    """Test main() error handling."""

    def test_no_args_shows_help(self, capsys):
        """Should show help when no args provided."""
        sys.argv = ["issue_setup.py"]
        with pytest.raises(SystemExit) as exc:
            issue_setup.main()
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "Subcommands:" in captured.err

    def test_unknown_subcommand_error(self, capsys):
        """Should error on unknown subcommand."""
        sys.argv = ["issue_setup.py", "unknown-cmd", "arg"]
        with pytest.raises(SystemExit) as exc:
            issue_setup.main()
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "ERROR=unknown_subcommand" in captured.err


class TestLabelDefinitions:
    """Test label constant definitions."""

    def test_standard_labels_count(self):
        """Should have 7 standard labels."""
        assert len(issue_setup.STANDARD_LABELS) == 7

    def test_scale_labels_count(self):
        """Should have 5 scale labels."""
        assert len(issue_setup.SCALE_LABELS) == 5

    def test_complexity_labels_count(self):
        """Should have 3 complexity labels."""
        assert len(issue_setup.COMPLEXITY_LABELS) == 3

    def test_all_labels_combined(self):
        """Should have 15 total labels."""
        assert len(issue_setup.ALL_LABELS) == 15

    def test_epic_label_present(self):
        """Should include epic label."""
        names = [name for name, _, _ in issue_setup.STANDARD_LABELS]
        assert "epic" in names

    def test_scale_labels_format(self):
        """Scale labels should use 'scale: ' prefix."""
        for name, _, _ in issue_setup.SCALE_LABELS:
            assert name.startswith("scale: ")

    def test_complexity_labels_format(self):
        """Complexity labels should use 'complexity: ' prefix."""
        for name, _, _ in issue_setup.COMPLEXITY_LABELS:
            assert name.startswith("complexity: ")
