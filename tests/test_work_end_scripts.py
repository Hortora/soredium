#!/usr/bin/env python3
"""
Tests for work-end scripts: artifact_promote.py, branch_cleanup.py

Covers: happy path, edge cases, missing args, error conditions.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ARTIFACT_PROMOTE = Path(__file__).parent.parent / "work-end" / "artifact_promote.py"
BRANCH_CLEANUP = Path(__file__).parent.parent / "work-end" / "branch_cleanup.py"


def run_promote(subcommand: str, *positional: str, **kw_args: str) -> subprocess.CompletedProcess:
    args = [sys.executable, str(ARTIFACT_PROMOTE), subcommand] + list(positional)
    args += [f"{k}={v}" for k, v in kw_args.items()]
    return subprocess.run(args, capture_output=True, text=True)


def run_cleanup(subcommand: str, *positional: str, **kw_args: str) -> subprocess.CompletedProcess:
    args = [sys.executable, str(BRANCH_CLEANUP), subcommand] + list(positional)
    args += [f"{k}={v}" for k, v in kw_args.items()]
    return subprocess.run(args, capture_output=True, text=True)


def parse(result: subprocess.CompletedProcess) -> dict[str, str]:
    """Extract KEY=VALUE pairs from stdout."""
    out: dict[str, str] = {}
    for line in result.stdout.strip().splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            out[k] = v
    return out


def init_git(path: Path) -> None:
    """Initialise a bare git repo at the given path with user config."""
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@test.com"],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test"],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "commit", "--allow-empty", "-m", "init"],
        capture_output=True, check=True,
    )


def create_branch_with_file(repo: Path, branch: str, filepath: str, content: str) -> None:
    """Create a branch in repo with a file, then return to main."""
    subprocess.run(
        ["git", "-C", str(repo), "checkout", "-b", branch],
        capture_output=True, check=True,
    )
    full_path = repo / filepath
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content)
    subprocess.run(
        ["git", "-C", str(repo), "add", filepath],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", f"add {filepath}"],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "checkout", "main"],
        capture_output=True, check=True,
    )


# ===========================================================================
# artifact_promote.py — to-workspace-main
# ===========================================================================

class TestToWorkspaceMain:

    def test_promotes_file_from_branch(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        init_git(ws)
        create_branch_with_file(ws, "issue-42-feature", "adr/0001.md", "# ADR 1\n")

        result = run_promote(
            "to-workspace-main", str(ws),
            branch="issue-42-feature", artifacts="adr/0001.md",
        )
        assert result.returncode == 0
        out = parse(result)
        assert out["PROMOTED"] == "1"

        # Verify file exists on main
        subprocess.run(
            ["git", "-C", str(ws), "checkout", "main"],
            capture_output=True, check=True,
        )
        assert (ws / "adr" / "0001.md").is_file()

    def test_promotes_multiple_artifacts(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        init_git(ws)

        # Create branch with two files
        subprocess.run(
            ["git", "-C", str(ws), "checkout", "-b", "issue-10-work"],
            capture_output=True, check=True,
        )
        (ws / "adr").mkdir()
        (ws / "adr" / "0001.md").write_text("adr 1\n")
        (ws / "blog").mkdir()
        (ws / "blog" / "entry.md").write_text("entry\n")
        subprocess.run(["git", "-C", str(ws), "add", "-A"], capture_output=True, check=True)
        subprocess.run(
            ["git", "-C", str(ws), "commit", "-m", "add artifacts"],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(ws), "checkout", "main"],
            capture_output=True, check=True,
        )

        result = run_promote(
            "to-workspace-main", str(ws),
            branch="issue-10-work", artifacts="adr/0001.md,blog/entry.md",
        )
        assert result.returncode == 0
        out = parse(result)
        assert out["PROMOTED"] == "2"

    def test_returns_to_branch_after_promote(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        init_git(ws)
        create_branch_with_file(ws, "issue-5-fix", "blog/post.md", "post\n")

        # Switch to the branch before running
        subprocess.run(
            ["git", "-C", str(ws), "checkout", "issue-5-fix"],
            capture_output=True, check=True,
        )

        result = run_promote(
            "to-workspace-main", str(ws),
            branch="issue-5-fix", artifacts="blog/post.md",
        )
        assert result.returncode == 0

        # Check we're back on the branch
        branch_result = subprocess.run(
            ["git", "-C", str(ws), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True,
        )
        assert branch_result.stdout.strip() == "issue-5-fix"

    def test_nothing_to_promote(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        init_git(ws)
        create_branch_with_file(ws, "issue-1-test", "somefile.md", "content\n")

        result = run_promote(
            "to-workspace-main", str(ws),
            branch="issue-1-test", artifacts="nonexistent.md",
        )
        assert result.returncode == 0
        out = parse(result)
        assert out["PROMOTED"] == "0"

    def test_empty_artifacts_string(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        init_git(ws)

        result = run_promote(
            "to-workspace-main", str(ws),
            branch="issue-1-test", artifacts="",
        )
        assert result.returncode == 1
        out = parse(result)
        assert out["ERROR"] == "missing_artifacts"

    def test_missing_branch_arg(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        init_git(ws)

        result = run_promote(
            "to-workspace-main", str(ws),
            artifacts="adr/0001.md",
        )
        assert result.returncode == 1
        out = parse(result)
        assert out["ERROR"] == "missing_branch"

    def test_nonexistent_workspace(self, tmp_path):
        result = run_promote(
            "to-workspace-main", str(tmp_path / "nonexistent"),
            branch="issue-1", artifacts="x.md",
        )
        assert result.returncode == 1
        out = parse(result)
        assert out["ERROR"] == "workspace_not_found"


# ===========================================================================
# artifact_promote.py — to-project
# ===========================================================================

class TestToProject:

    def test_copies_file_to_project(self, tmp_path):
        proj = tmp_path / "project"
        ws = tmp_path / "workspace"
        proj.mkdir()
        ws.mkdir()
        init_git(proj)

        # Create a file in workspace
        (ws / "docs" / "adr").mkdir(parents=True)
        (ws / "docs" / "adr" / "0001.md").write_text("# ADR 1\n")

        result = run_promote(
            "to-project", str(proj), str(ws),
            artifacts="docs/adr/0001.md",
        )
        assert result.returncode == 0
        out = parse(result)
        assert out["PROMOTED"] == "1"
        assert (proj / "docs" / "adr" / "0001.md").is_file()
        assert (proj / "docs" / "adr" / "0001.md").read_text() == "# ADR 1\n"

    def test_copies_directory_to_project(self, tmp_path):
        proj = tmp_path / "project"
        ws = tmp_path / "workspace"
        proj.mkdir()
        ws.mkdir()
        init_git(proj)

        (ws / "specs" / "issue-42").mkdir(parents=True)
        (ws / "specs" / "issue-42" / "design.md").write_text("design\n")
        (ws / "specs" / "issue-42" / "api.md").write_text("api\n")

        result = run_promote(
            "to-project", str(proj), str(ws),
            artifacts="specs/issue-42",
        )
        assert result.returncode == 0
        out = parse(result)
        assert out["PROMOTED"] == "1"
        assert (proj / "specs" / "issue-42" / "design.md").is_file()
        assert (proj / "specs" / "issue-42" / "api.md").is_file()

    def test_skips_nonexistent_source(self, tmp_path):
        proj = tmp_path / "project"
        ws = tmp_path / "workspace"
        proj.mkdir()
        ws.mkdir()
        init_git(proj)

        result = run_promote(
            "to-project", str(proj), str(ws),
            artifacts="nonexistent.md",
        )
        assert result.returncode == 0
        out = parse(result)
        assert out["PROMOTED"] == "0"

    def test_missing_artifacts_arg(self, tmp_path):
        proj = tmp_path / "project"
        ws = tmp_path / "workspace"
        proj.mkdir()
        ws.mkdir()

        result = run_promote("to-project", str(proj), str(ws))
        assert result.returncode == 1
        out = parse(result)
        assert out["ERROR"] == "missing_artifacts"

    def test_nonexistent_project(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        result = run_promote(
            "to-project", str(tmp_path / "nonexistent"), str(ws),
            artifacts="x.md",
        )
        assert result.returncode == 1
        out = parse(result)
        assert out["ERROR"] == "project_not_found"

    def test_nonexistent_workspace(self, tmp_path):
        proj = tmp_path / "project"
        proj.mkdir()
        result = run_promote(
            "to-project", str(proj), str(tmp_path / "nonexistent"),
            artifacts="x.md",
        )
        assert result.returncode == 1
        out = parse(result)
        assert out["ERROR"] == "workspace_not_found"


# ===========================================================================
# artifact_promote.py — cleanup-specs
# ===========================================================================

class TestCleanupSpecs:

    def test_removes_spec_directory(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        init_git(ws)

        # Create specs on main
        (ws / "specs" / "issue-42").mkdir(parents=True)
        (ws / "specs" / "issue-42" / "design.md").write_text("design\n")
        subprocess.run(["git", "-C", str(ws), "add", "-A"], capture_output=True, check=True)
        subprocess.run(
            ["git", "-C", str(ws), "commit", "-m", "add specs"],
            capture_output=True, check=True,
        )

        result = run_promote("cleanup-specs", str(ws), branch="issue-42")
        assert result.returncode == 0
        out = parse(result)
        assert out["CLEANED"] == "1"
        assert not (ws / "specs" / "issue-42").exists()

    def test_no_specs_to_clean(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        init_git(ws)

        result = run_promote("cleanup-specs", str(ws), branch="nonexistent-branch")
        assert result.returncode == 0
        out = parse(result)
        assert out["CLEANED"] == "0"

    def test_missing_branch_arg(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        init_git(ws)

        result = run_promote("cleanup-specs", str(ws))
        assert result.returncode == 1
        out = parse(result)
        assert out["ERROR"] == "missing_branch"

    def test_nonexistent_workspace(self, tmp_path):
        result = run_promote(
            "cleanup-specs", str(tmp_path / "nonexistent"),
            branch="issue-1",
        )
        assert result.returncode == 1
        out = parse(result)
        assert out["ERROR"] == "workspace_not_found"


# ===========================================================================
# artifact_promote.py — close-issues
# ===========================================================================

class TestCloseIssues:

    def test_missing_covers_arg(self):
        result = run_promote("close-issues", "owner/repo")
        assert result.returncode == 1
        out = parse(result)
        assert out["ERROR"] == "missing_covers"

    def test_empty_covers(self):
        result = run_promote("close-issues", "owner/repo", covers="")
        assert result.returncode == 1
        out = parse(result)
        assert out["ERROR"] == "missing_covers"

    def test_gh_not_found_graceful(self):
        """When gh fails (no auth, wrong repo), should report ERROR."""
        # This will fail because the repo doesn't exist, but it tests
        # that the error handling works
        result = run_promote(
            "close-issues", "nonexistent-owner/nonexistent-repo",
            covers="999999",
        )
        # Should exit 1 because all closes failed
        assert result.returncode == 1
        out = parse(result)
        assert out["ERROR"] == "gh_failed"

    def test_partial_success(self, tmp_path, monkeypatch):
        """When some issues close successfully and some fail, should report partial success."""
        # Create a mock gh that succeeds for issue "1", fails for others
        import importlib
        import sys

        # Import the artifact_promote module
        import_path = str(ARTIFACT_PROMOTE.parent)
        if import_path not in sys.path:
            sys.path.insert(0, import_path)

        artifact_promote = importlib.import_module("artifact_promote")

        original_run = subprocess.run

        def mock_run(args, **kwargs):
            # Only mock gh calls; pass through everything else
            if args[0] == "gh":
                # args is ["gh", "issue", "close", "<issue_num>", "--repo", "<repo>"]
                issue_num = args[3]
                if issue_num == "1":
                    return subprocess.CompletedProcess(
                        args=args, returncode=0, stdout="", stderr=""
                    )
                else:
                    # Raise CalledProcessError as the code expects
                    raise subprocess.CalledProcessError(
                        returncode=1,
                        cmd=args,
                        stderr=f"failed to close #{issue_num}"
                    )
            else:
                return original_run(args, **kwargs)

        # Monkeypatch subprocess.run in the artifact_promote module
        monkeypatch.setattr(artifact_promote.subprocess, "run", mock_run)

        # Now run the close_issues function directly
        from io import StringIO

        captured = StringIO()
        monkeypatch.setattr(sys, "stdout", captured)

        result = artifact_promote.close_issues("owner/repo", {"covers": "1,2,3"})

        # Restore stdout
        monkeypatch.undo()

        # Should succeed with partial close
        assert result == 0
        output = captured.getvalue()
        out = {}
        for line in output.strip().splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                out[k] = v

        assert out["CLOSED"] == "1"
        assert "ERRORS" in out
        assert "#2:" in out["ERRORS"]
        assert "#3:" in out["ERRORS"]


# ===========================================================================
# artifact_promote.py — errors
# ===========================================================================

class TestArtifactPromoteErrors:

    def test_unknown_subcommand(self):
        result = run_promote("bogus", "/tmp")
        assert result.returncode == 1

    def test_no_args_prints_usage(self):
        result = subprocess.run(
            [sys.executable, str(ARTIFACT_PROMOTE)],
            capture_output=True, text=True,
        )
        assert result.returncode == 1

    def test_to_workspace_main_no_positional(self):
        result = run_promote("to-workspace-main")
        assert result.returncode == 1

    def test_to_project_missing_workspace(self, tmp_path):
        proj = tmp_path / "project"
        proj.mkdir()
        result = subprocess.run(
            [sys.executable, str(ARTIFACT_PROMOTE), "to-project", str(proj)],
            capture_output=True, text=True,
        )
        assert result.returncode == 1


# ===========================================================================
# branch_cleanup.py — create-epic-closed
# ===========================================================================

class TestCreateEpicClosed:

    def test_creates_epic_closed_file(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        init_git(ws)

        # Create a branch (we need one to be on for the test)
        subprocess.run(
            ["git", "-C", str(ws), "checkout", "-b", "issue-42-feature"],
            capture_output=True, check=True,
        )

        result = run_cleanup(
            "create-epic-closed", str(ws),
            branch="issue-42-feature", date="2026-06-18",
            issues="42",
        )
        assert result.returncode == 0
        out = parse(result)
        assert out["CREATED"] == "yes"

        content = (ws / "design" / "EPIC-CLOSED.md").read_text()
        assert "Branch Closed: issue-42-feature" in content
        assert "2026-06-18" in content
        assert "42" in content
        assert "merged to main" in content

    def test_creates_with_multiple_issues(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        init_git(ws)

        subprocess.run(
            ["git", "-C", str(ws), "checkout", "-b", "issue-5-multi"],
            capture_output=True, check=True,
        )

        result = run_cleanup(
            "create-epic-closed", str(ws),
            branch="issue-5-multi", date="2026-06-18",
            issues="5,19,32",
        )
        assert result.returncode == 0
        content = (ws / "design" / "EPIC-CLOSED.md").read_text()
        assert "5,19,32" in content

    def test_single_repo_mode_switches_branches(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        init_git(ws)

        # Create the branch
        subprocess.run(
            ["git", "-C", str(ws), "checkout", "-b", "issue-7-sr"],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(ws), "checkout", "main"],
            capture_output=True, check=True,
        )

        result = run_cleanup(
            "create-epic-closed", str(ws),
            branch="issue-7-sr", date="2026-06-18",
            issues="7", **{"single-repo": "yes"},
        )
        assert result.returncode == 0

        # Should end up back on main
        branch_result = subprocess.run(
            ["git", "-C", str(ws), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True,
        )
        assert branch_result.stdout.strip() == "main"

    def test_missing_branch_arg(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        init_git(ws)

        result = run_cleanup(
            "create-epic-closed", str(ws),
            date="2026-06-18", issues="42",
        )
        assert result.returncode == 1
        out = parse(result)
        assert out["ERROR"] == "missing_branch"

    def test_missing_date_arg(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        init_git(ws)

        result = run_cleanup(
            "create-epic-closed", str(ws),
            branch="issue-42", issues="42",
        )
        assert result.returncode == 1
        out = parse(result)
        assert out["ERROR"] == "missing_date"

    def test_missing_issues_arg(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        init_git(ws)

        result = run_cleanup(
            "create-epic-closed", str(ws),
            branch="issue-42", date="2026-06-18",
        )
        assert result.returncode == 1
        out = parse(result)
        assert out["ERROR"] == "missing_issues"

    def test_nonexistent_workspace(self, tmp_path):
        result = run_cleanup(
            "create-epic-closed", str(tmp_path / "nonexistent"),
            branch="issue-42", date="2026-06-18", issues="42",
        )
        assert result.returncode == 1
        out = parse(result)
        assert out["ERROR"] == "workspace_not_found"


# ===========================================================================
# branch_cleanup.py — cleanup-scaffold
# ===========================================================================

class TestCleanupScaffold:

    def test_removes_meta_and_journal(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        init_git(ws)

        # Create scaffold files
        (ws / "design").mkdir()
        (ws / "design" / ".meta").write_text("branch: issue-42\n")
        (ws / "design" / "JOURNAL.md").write_text("# Journal\n")
        subprocess.run(["git", "-C", str(ws), "add", "-A"], capture_output=True, check=True)
        subprocess.run(
            ["git", "-C", str(ws), "commit", "-m", "add scaffold"],
            capture_output=True, check=True,
        )

        result = run_cleanup("cleanup-scaffold", str(ws))
        assert result.returncode == 0
        out = parse(result)
        assert out["CLEANED"] == "yes"
        assert not (ws / "design" / ".meta").exists()
        assert not (ws / "design" / "JOURNAL.md").exists()

    def test_removes_design_dir_if_empty(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        init_git(ws)

        (ws / "design").mkdir()
        (ws / "design" / ".meta").write_text("branch: issue-42\n")
        subprocess.run(["git", "-C", str(ws), "add", "-A"], capture_output=True, check=True)
        subprocess.run(
            ["git", "-C", str(ws), "commit", "-m", "add scaffold"],
            capture_output=True, check=True,
        )

        result = run_cleanup("cleanup-scaffold", str(ws))
        assert result.returncode == 0
        assert not (ws / "design").exists()

    def test_preserves_design_dir_if_has_other_files(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        init_git(ws)

        (ws / "design").mkdir()
        (ws / "design" / ".meta").write_text("branch: issue-42\n")
        (ws / "design" / "JOURNAL.md").write_text("# Journal\n")
        (ws / "design" / "EPIC-CLOSED.md").write_text("closed\n")
        subprocess.run(["git", "-C", str(ws), "add", "-A"], capture_output=True, check=True)
        subprocess.run(
            ["git", "-C", str(ws), "commit", "-m", "add scaffold and marker"],
            capture_output=True, check=True,
        )

        result = run_cleanup("cleanup-scaffold", str(ws))
        assert result.returncode == 0
        assert (ws / "design").is_dir()
        assert (ws / "design" / "EPIC-CLOSED.md").is_file()

    def test_nothing_to_clean(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        init_git(ws)

        result = run_cleanup("cleanup-scaffold", str(ws))
        assert result.returncode == 0
        out = parse(result)
        assert out["CLEANED"] == "yes"

    def test_only_meta_exists(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        init_git(ws)

        (ws / "design").mkdir()
        (ws / "design" / ".meta").write_text("branch: issue-42\n")
        subprocess.run(["git", "-C", str(ws), "add", "-A"], capture_output=True, check=True)
        subprocess.run(
            ["git", "-C", str(ws), "commit", "-m", "add meta"],
            capture_output=True, check=True,
        )

        result = run_cleanup("cleanup-scaffold", str(ws))
        assert result.returncode == 0
        assert not (ws / "design" / ".meta").exists()

    def test_nonexistent_workspace(self, tmp_path):
        result = run_cleanup("cleanup-scaffold", str(tmp_path / "nonexistent"))
        assert result.returncode == 1
        out = parse(result)
        assert out["ERROR"] == "workspace_not_found"


# ===========================================================================
# branch_cleanup.py — cleanup-stack
# ===========================================================================

class TestCleanupStack:

    def test_removes_branch_from_stack(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        init_git(ws)

        (ws / "design").mkdir()
        stack_content = (
            "- branch: issue-42-feature\n"
            "  project-sha: abc123\n"
            "  date: 2026-06-18\n"
            "- branch: issue-10-other\n"
            "  project-sha: def456\n"
            "  date: 2026-06-17\n"
        )
        (ws / "design" / ".pause-stack").write_text(stack_content)
        subprocess.run(["git", "-C", str(ws), "add", "-A"], capture_output=True, check=True)
        subprocess.run(
            ["git", "-C", str(ws), "commit", "-m", "add stack"],
            capture_output=True, check=True,
        )

        result = run_cleanup("cleanup-stack", str(ws), branch="issue-42-feature")
        assert result.returncode == 0
        out = parse(result)
        assert out["REMOVED"] == "yes"

        # Verify the branch was removed but the other remains
        remaining = (ws / "design" / ".pause-stack").read_text()
        assert "issue-42-feature" not in remaining
        assert "issue-10-other" in remaining

    def test_branch_not_in_stack(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        init_git(ws)

        (ws / "design").mkdir()
        (ws / "design" / ".pause-stack").write_text(
            "- branch: issue-10-other\n  project-sha: def456\n"
        )

        result = run_cleanup("cleanup-stack", str(ws), branch="issue-42-feature")
        assert result.returncode == 0
        out = parse(result)
        assert out["REMOVED"] == "no"

    def test_no_stack_file(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        init_git(ws)

        result = run_cleanup("cleanup-stack", str(ws), branch="issue-42-feature")
        assert result.returncode == 0
        out = parse(result)
        assert out["REMOVED"] == "no"

    def test_missing_branch_arg(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        init_git(ws)

        result = run_cleanup("cleanup-stack", str(ws))
        assert result.returncode == 1
        out = parse(result)
        assert out["ERROR"] == "missing_branch"

    def test_nonexistent_workspace(self, tmp_path):
        result = run_cleanup(
            "cleanup-stack", str(tmp_path / "nonexistent"),
            branch="issue-1",
        )
        assert result.returncode == 1
        out = parse(result)
        assert out["ERROR"] == "workspace_not_found"


# ===========================================================================
# branch_cleanup.py — checkout-main
# ===========================================================================

class TestCheckoutMain:

    def test_switches_both_repos_to_main(self, tmp_path):
        proj = tmp_path / "project"
        ws = tmp_path / "workspace"
        proj.mkdir()
        ws.mkdir()
        init_git(proj)
        init_git(ws)

        # Create branches and switch to them
        subprocess.run(
            ["git", "-C", str(proj), "checkout", "-b", "issue-42"],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(ws), "checkout", "-b", "issue-42"],
            capture_output=True, check=True,
        )

        result = run_cleanup("checkout-main", str(proj), str(ws))
        assert result.returncode == 0
        out = parse(result)
        assert out["SWITCHED"] == "yes"

        # Verify both on main
        for repo in [proj, ws]:
            branch = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True,
            )
            assert branch.stdout.strip() == "main"

    def test_already_on_main(self, tmp_path):
        proj = tmp_path / "project"
        ws = tmp_path / "workspace"
        proj.mkdir()
        ws.mkdir()
        init_git(proj)
        init_git(ws)

        result = run_cleanup("checkout-main", str(proj), str(ws))
        assert result.returncode == 0
        out = parse(result)
        assert out["SWITCHED"] == "yes"

    def test_nonexistent_project(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        init_git(ws)

        result = run_cleanup("checkout-main", str(tmp_path / "nonexistent"), str(ws))
        assert result.returncode == 1
        out = parse(result)
        assert out["ERROR"] == "project_not_found"

    def test_nonexistent_workspace(self, tmp_path):
        proj = tmp_path / "project"
        proj.mkdir()
        init_git(proj)

        result = run_cleanup("checkout-main", str(proj), str(tmp_path / "nonexistent"))
        assert result.returncode == 1
        out = parse(result)
        assert out["ERROR"] == "workspace_not_found"

    def test_missing_workspace_arg(self, tmp_path):
        proj = tmp_path / "project"
        proj.mkdir()
        result = subprocess.run(
            [sys.executable, str(BRANCH_CLEANUP), "checkout-main", str(proj)],
            capture_output=True, text=True,
        )
        assert result.returncode == 1


# ===========================================================================
# branch_cleanup.py — errors
# ===========================================================================

class TestBranchCleanupErrors:

    def test_unknown_subcommand(self):
        result = run_cleanup("bogus", "/tmp")
        assert result.returncode == 1

    def test_no_args_prints_usage(self):
        result = subprocess.run(
            [sys.executable, str(BRANCH_CLEANUP)],
            capture_output=True, text=True,
        )
        assert result.returncode == 1

    def test_create_epic_closed_no_positional(self):
        result = run_cleanup("create-epic-closed")
        assert result.returncode == 1
