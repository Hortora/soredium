#!/usr/bin/env python3
"""
Tests for work-end scripts: artifact_promote.py, branch_cleanup.py

Covers: happy path, edge cases, missing args, error conditions.
"""

import os
import shutil
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
        assert out["SKIPPED"] == "1"

    def test_reports_skipped_count_for_missing_artifacts(self, tmp_path):
        """When some artifacts don't exist on the branch, SKIPPED count is reported."""
        ws = tmp_path / "workspace"
        ws.mkdir()
        init_git(ws)
        create_branch_with_file(ws, "issue-1-test", "blog/real.md", "real content\n")

        result = run_promote(
            "to-workspace-main", str(ws),
            branch="issue-1-test", artifacts="blog/real.md,specs/missing.md",
        )
        assert result.returncode == 0
        out = parse(result)
        assert out["PROMOTED"] == "1"
        assert out["SKIPPED"] == "1"

    def test_skipped_paths_reported(self, tmp_path):
        """Skipped artifact paths are reported in output for diagnostics."""
        ws = tmp_path / "workspace"
        ws.mkdir()
        init_git(ws)
        create_branch_with_file(ws, "issue-1-test", "blog/real.md", "content\n")

        result = run_promote(
            "to-workspace-main", str(ws),
            branch="issue-1-test", artifacts="blog/real.md,specs/missing.md",
        )
        out = parse(result)
        assert "specs/missing.md" in out.get("SKIPPED_PATHS", "")

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
# artifact_promote.py — push behavior (to-workspace-main)
# ===========================================================================

class TestToWorkspaceMainPush:

    def test_push_skipped_when_no_remote(self, tmp_path):
        """No remote configured → PUSHED=skipped, not failure."""
        ws = tmp_path / "workspace"
        ws.mkdir()
        init_git(ws)
        create_branch_with_file(ws, "issue-1-test", "blog/real.md", "content\n")

        result = run_promote(
            "to-workspace-main", str(ws),
            branch="issue-1-test", artifacts="blog/real.md",
        )
        out = parse(result)
        assert out["PROMOTED"] == "1"
        assert out["PUSHED"] == "skipped"

    def test_push_failed_when_remote_unreachable(self, tmp_path):
        """Remote exists but is unreachable → PUSHED=failed."""
        ws = tmp_path / "workspace"
        remote = tmp_path / "remote.git"
        ws.mkdir()
        init_git(ws)

        subprocess.run(["git", "init", "--bare", str(remote)], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(ws), "remote", "add", "origin", str(remote)], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(ws), "push", "-u", "origin", "main"], capture_output=True, check=True)

        create_branch_with_file(ws, "issue-1-test", "blog/real.md", "content\n")

        shutil.rmtree(remote)

        result = run_promote(
            "to-workspace-main", str(ws),
            branch="issue-1-test", artifacts="blog/real.md",
        )
        out = parse(result)
        assert out["PROMOTED"] == "1"
        assert out["PUSHED"] == "failed"
        assert "PUSH_ERROR" in out


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
# artifact_promote.py — push behavior (to-project)
# ===========================================================================

class TestToProjectPush:

    def test_push_skipped_when_no_remote(self, tmp_path):
        """No remote configured → PUSHED=skipped."""
        proj = tmp_path / "project"
        ws = tmp_path / "workspace"
        proj.mkdir()
        ws.mkdir()
        init_git(proj)

        (ws / "specs").mkdir()
        (ws / "specs" / "design.md").write_text("# Spec\n")

        result = run_promote(
            "to-project", str(proj), str(ws),
            artifacts="specs/design.md",
        )
        out = parse(result)
        assert out["PROMOTED"] == "1"
        assert out["PUSHED"] == "skipped"

    def test_push_failed_when_remote_unreachable(self, tmp_path):
        """Remote exists but is unreachable → PUSHED=failed."""
        proj = tmp_path / "project"
        ws = tmp_path / "workspace"
        remote = tmp_path / "remote.git"
        proj.mkdir()
        ws.mkdir()
        init_git(proj)

        subprocess.run(["git", "init", "--bare", str(remote)], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(proj), "remote", "add", "origin", str(remote)], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(proj), "push", "-u", "origin", "main"], capture_output=True, check=True)

        (ws / "specs").mkdir()
        (ws / "specs" / "design.md").write_text("# Spec\n")

        shutil.rmtree(remote)

        result = run_promote(
            "to-project", str(proj), str(ws),
            artifacts="specs/design.md",
        )
        out = parse(result)
        assert out["PROMOTED"] == "1"
        assert out["PUSHED"] == "failed"
        assert "PUSH_ERROR" in out


# ===========================================================================
# artifact_promote.py — cleanup-specs (removed subcommand — keep only the negative test)
# ===========================================================================

class TestCleanupSpecs:
    """cleanup-specs was removed — test_close_artifacts.py::TestCleanupSpecsRemoved covers this."""

    def test_subcommand_rejected(self):
        result = run_promote("cleanup-specs", "/tmp", branch="x")
        assert result.returncode == 1


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

    def test_unknown_subcommand(self):
        result = run_cleanup("create-epic-closed")
        assert result.returncode == 1


# ===========================================================================
# BUG 1: to_workspace_main slot mode — source-dir parameter
# ===========================================================================

class TestToWorkspaceMainSlotMode:
    """Slot mode: branch doesn't exist on original workspace.
    source-dir enables filesystem copy instead of git checkout."""

    def test_promotes_from_source_dir(self, tmp_path):
        """When source-dir is set, artifacts are copied from that directory
        instead of using git checkout from branch. BUG 1 regression test."""
        ws = tmp_path / "original-workspace"
        ws.mkdir()
        init_git(ws)

        slot_ws = tmp_path / "slot-workspace"
        (slot_ws / "blog").mkdir(parents=True)
        (slot_ws / "blog" / "entry.md").write_text("# Blog Entry\n")

        result = run_promote(
            "to-workspace-main", str(ws),
            branch="issue-42-feat",
            artifacts="blog/entry.md",
            **{"source-dir": str(slot_ws)},
        )
        assert result.returncode == 0
        out = parse(result)
        assert out["PROMOTED"] == "1"

        subprocess.run(
            ["git", "-C", str(ws), "checkout", "main"],
            capture_output=True, check=True,
        )
        assert (ws / "blog" / "entry.md").is_file()
        assert (ws / "blog" / "entry.md").read_text() == "# Blog Entry\n"

    def test_source_dir_promotes_multiple_artifacts(self, tmp_path):
        """source-dir with multiple artifacts."""
        ws = tmp_path / "ws"
        ws.mkdir()
        init_git(ws)

        slot = tmp_path / "slot"
        (slot / "specs").mkdir(parents=True)
        (slot / "specs" / "a.md").write_text("spec a\n")
        (slot / "blog").mkdir()
        (slot / "blog" / "b.md").write_text("blog b\n")

        result = run_promote(
            "to-workspace-main", str(ws),
            branch="issue-1",
            artifacts="specs/a.md,blog/b.md",
            **{"source-dir": str(slot)},
        )
        assert result.returncode == 0
        out = parse(result)
        assert out["PROMOTED"] == "2"

    def test_source_dir_skips_missing_artifact(self, tmp_path):
        """source-dir with one present and one missing artifact."""
        ws = tmp_path / "ws"
        ws.mkdir()
        init_git(ws)

        slot = tmp_path / "slot"
        (slot / "specs").mkdir(parents=True)
        (slot / "specs" / "exists.md").write_text("here\n")

        result = run_promote(
            "to-workspace-main", str(ws),
            branch="issue-1",
            artifacts="specs/exists.md,specs/missing.md",
            **{"source-dir": str(slot)},
        )
        assert result.returncode == 0
        out = parse(result)
        assert out["PROMOTED"] == "1"
        assert out["SKIPPED"] == "1"

    def test_without_source_dir_uses_git_checkout(self, tmp_path):
        """Without source-dir, existing git checkout behavior is preserved."""
        ws = tmp_path / "ws"
        ws.mkdir()
        init_git(ws)
        create_branch_with_file(ws, "issue-99", "adr/0001.md", "# ADR\n")

        result = run_promote(
            "to-workspace-main", str(ws),
            branch="issue-99", artifacts="adr/0001.md",
        )
        assert result.returncode == 0
        out = parse(result)
        assert out["PROMOTED"] == "1"


# ===========================================================================
# BUG 4: to_project single-repo mode — SameFileError
# ===========================================================================

class TestToProjectSingleRepo:
    """Single-repo mode: workspace=project. shutil.copy2(src, dst) crashes
    when src and dst resolve to the same file."""

    def test_same_path_no_crash(self, tmp_path):
        """When project and workspace are the same directory, to_project
        should not crash with SameFileError. BUG 4 regression test."""
        repo = tmp_path / "repo"
        repo.mkdir()
        init_git(repo)

        (repo / "specs").mkdir()
        (repo / "specs" / "design.md").write_text("# Spec\n")
        subprocess.run(
            ["git", "-C", str(repo), "add", "specs/design.md"],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", "add spec"],
            capture_output=True, check=True,
        )

        result = run_promote(
            "to-project", str(repo), str(repo),
            artifacts="specs/design.md",
        )
        assert result.returncode == 0, (
            f"Expected exit 0 but got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        out = parse(result)
        assert out["PROMOTED"] == "1"

    def test_single_repo_directory_no_crash(self, tmp_path):
        """Directory artifact in single-repo mode should not crash."""
        repo = tmp_path / "repo"
        repo.mkdir()
        init_git(repo)

        (repo / "specs" / "issue-42").mkdir(parents=True)
        (repo / "specs" / "issue-42" / "design.md").write_text("# Spec\n")
        subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "add"], capture_output=True, check=True)

        result = run_promote(
            "to-project", str(repo), str(repo),
            artifacts="specs/issue-42",
        )
        assert result.returncode == 0
        out = parse(result)
        assert out["PROMOTED"] == "1"
