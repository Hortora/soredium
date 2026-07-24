"""Tests for work-end/close_artifacts.py"""

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

script_dir = Path(__file__).parent.parent / "work-end"
sys.path.insert(0, str(script_dir))
sys.path.insert(0, str(Path(__file__).parent.parent / "project"))

from close_artifacts import scan_artifacts, resolve_routing, write_stamp


class TestScanArtifacts:
    def test_finds_specs_for_branch(self, tmp_path):
        specs = tmp_path / "specs" / "issue-42-feat"
        specs.mkdir(parents=True)
        (specs / "design.md").write_text("spec")
        (specs / "notes.md").write_text("notes")

        result = scan_artifacts(tmp_path, "issue-42-feat")
        assert len(result["specs"]) == 2
        assert "specs/issue-42-feat/design.md" in result["specs"]

    def test_ignores_other_branch_specs(self, tmp_path):
        (tmp_path / "specs" / "issue-42-feat").mkdir(parents=True)
        (tmp_path / "specs" / "issue-42-feat" / "spec.md").write_text("x")
        (tmp_path / "specs" / "issue-99-other").mkdir(parents=True)
        (tmp_path / "specs" / "issue-99-other" / "spec.md").write_text("y")

        result = scan_artifacts(tmp_path, "issue-42-feat")
        assert len(result["specs"]) == 1

    def test_finds_blog_entries(self, tmp_path):
        blog = tmp_path / "blog"
        blog.mkdir()
        (blog / "2026-07-01-entry.md").write_text("blog")
        (blog / "INDEX.md").write_text("index")

        result = scan_artifacts(tmp_path, "any-branch")
        assert len(result["blog"]) == 1
        assert "blog/2026-07-01-entry.md" in result["blog"]

    def test_finds_adr(self, tmp_path):
        adr = tmp_path / "adr"
        adr.mkdir()
        (adr / "0001-decision.md").write_text("adr")
        (adr / "INDEX.md").write_text("index")

        result = scan_artifacts(tmp_path, "any-branch")
        assert len(result["adr"]) == 1

    def test_finds_plans(self, tmp_path):
        plans = tmp_path / "plans"
        plans.mkdir()
        (plans / "2026-07-01-plan.md").write_text("plan")
        (plans / "attic").mkdir()
        (plans / "INDEX.md").write_text("index")

        result = scan_artifacts(tmp_path, "any-branch")
        assert len(result["plans"]) == 1

    def test_empty_workspace(self, tmp_path):
        result = scan_artifacts(tmp_path, "any-branch")
        assert all(len(v) == 0 for v in result.values())


class TestResolveRouting:
    def test_defaults_without_claude_md(self, tmp_path):
        routing = resolve_routing(tmp_path)
        assert routing["specs"] == "project"
        assert routing["adr"] == "project"
        assert routing["blog"] == "project"

    def test_reads_workspace_routing_table(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text(
            "# Workspace\n\n## Routing\n\n"
            "| Artifact | Destination | Notes |\n"
            "|----------|-------------|-------|\n"
            "| blog | workspace | staged |\n"
            "| specs | project | lands in docs/specs/ |\n"
        )
        routing = resolve_routing(tmp_path)
        assert routing["blog"] == "workspace"
        assert routing["specs"] == "project"


class TestWriteStamp:
    def test_writes_stamp_file(self, tmp_path):
        (tmp_path / "design").mkdir()
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], capture_output=True)
        subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t.com"], capture_output=True)
        subprocess.run(["git", "-C", str(tmp_path), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(tmp_path), "commit", "--allow-empty", "-m", "init"], capture_output=True)

        results = {
            "workspace_promoted": "2",
            "project_promoted": "1",
            "specs_cleaned": "1",
            "issues_closed": "1",
            "blog_published": "0",
            "plans_archived": "1",
        }
        stamp = write_stamp(tmp_path, "issue-42-test", results)

        assert stamp.exists()
        content = stamp.read_text()
        assert "branch=issue-42-test" in content
        assert "workspace_promoted=2" in content
        assert "project_promoted=1" in content

    def test_stamp_contains_timestamp(self, tmp_path):
        (tmp_path / "design").mkdir()
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], capture_output=True)
        subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t.com"], capture_output=True)
        subprocess.run(["git", "-C", str(tmp_path), "commit", "--allow-empty", "-m", "init"], capture_output=True)

        stamp = write_stamp(tmp_path, "issue-42", {})
        content = stamp.read_text()
        assert "timestamp=" in content
        assert "202" in content  # year prefix


class TestScanWorkspaceParameter:
    """Test scan-workspace parameter for slot-mode artifact promotion."""

    SCRIPT = Path(__file__).parent.parent / "work-end" / "close_artifacts.py"

    def _init_git(self, path):
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", str(path)], capture_output=True)
        subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], capture_output=True)
        subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t.com"], capture_output=True)
        subprocess.run(["git", "-C", str(path), "commit", "--allow-empty", "-m", "init"], capture_output=True)

    def test_scan_workspace_reads_from_alternate_path(self, tmp_path):
        """When scan-workspace provided, artifacts scanned from that path."""
        workspace = tmp_path / "original-workspace"
        slot_workspace = tmp_path / "slot-workspace"
        project = tmp_path / "project"
        self._init_git(workspace)
        self._init_git(slot_workspace)
        self._init_git(project)
        (workspace / "design").mkdir()

        branch = "issue-99-test"
        (slot_workspace / "specs" / branch).mkdir(parents=True)
        (slot_workspace / "specs" / branch / "spec.md").write_text("# Spec\n")

        result = subprocess.run(
            [sys.executable, str(self.SCRIPT),
             str(workspace), str(project), branch,
             f"scan-workspace={slot_workspace}"],
            capture_output=True, text=True,
        )
        # Should not be fatal — scan from slot workspace succeeds
        assert result.returncode != 1

    def test_scan_workspace_missing_path_is_fatal(self, tmp_path):
        """scan-workspace pointing to non-existent path is fatal."""
        workspace = tmp_path / "workspace"
        project = tmp_path / "project"
        self._init_git(workspace)
        self._init_git(project)
        (workspace / "design").mkdir()

        result = subprocess.run(
            [sys.executable, str(self.SCRIPT),
             str(workspace), str(project), "test-branch",
             "scan-workspace=/nonexistent/path"],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "scan_workspace_not_found" in result.stdout

    def test_scan_workspace_omitted_scans_workspace(self, tmp_path):
        """Without scan-workspace, scan_artifacts uses workspace (current behaviour)."""
        workspace = tmp_path / "workspace"
        project = tmp_path / "project"
        self._init_git(workspace)
        self._init_git(project)
        (workspace / "design").mkdir()

        branch = "issue-99-test"
        (workspace / "specs" / branch).mkdir(parents=True)
        (workspace / "specs" / branch / "spec.md").write_text("# Spec\n")

        result = subprocess.run(
            [sys.executable, str(self.SCRIPT),
             str(workspace), str(project), branch],
            capture_output=True, text=True,
        )
        assert result.returncode != 1

    def test_scan_workspace_unit_scan_artifacts(self, tmp_path):
        """scan_artifacts uses the scan source path, not workspace."""
        slot = tmp_path / "slot"
        slot.mkdir()
        branch = "issue-50-feat"
        (slot / "specs" / branch).mkdir(parents=True)
        (slot / "specs" / branch / "design.md").write_text("spec")
        (slot / "blog").mkdir()
        (slot / "blog" / "entry.md").write_text("blog")

        result = scan_artifacts(slot, branch)
        assert len(result["specs"]) == 1
        assert len(result["blog"]) == 1


class TestArchivePlans:
    def test_archive_plans_via_script(self, tmp_path):
        """Integration test: archive-plans subcommand moves plans to attic."""
        ws = tmp_path / "workspace"
        ws.mkdir()
        subprocess.run(["git", "init", str(ws)], capture_output=True)
        subprocess.run(["git", "-C", str(ws), "config", "user.name", "Test"], capture_output=True)
        subprocess.run(["git", "-C", str(ws), "config", "user.email", "t@t.com"], capture_output=True)
        subprocess.run(["git", "-C", str(ws), "checkout", "-b", "main"], capture_output=True)

        plans = ws / "plans"
        plans.mkdir()
        (plans / "plan1.md").write_text("plan 1")
        subprocess.run(["git", "-C", str(ws), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(ws), "commit", "-m", "add plans"], capture_output=True)

        subprocess.run(["git", "-C", str(ws), "checkout", "-b", "issue-42"], capture_output=True)
        (plans / "plan2.md").write_text("plan 2")
        subprocess.run(["git", "-C", str(ws), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(ws), "commit", "-m", "add plan2"], capture_output=True)

        script = Path(__file__).parent.parent / "work-end" / "artifact_promote.py"
        result = subprocess.run(
            [sys.executable, str(script), "archive-plans", str(ws), "branch=issue-42"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "ARCHIVED=" in result.stdout

        # Verify plans moved to attic on main
        subprocess.run(["git", "-C", str(ws), "checkout", "main"], capture_output=True)
        attic = plans / "attic" / "issue-42"
        assert attic.is_dir()
