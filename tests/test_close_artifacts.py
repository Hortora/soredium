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
    """scan_artifacts now delegates to workspace_artifacts.scan()."""

    def test_finds_specs_flat(self, tmp_path):
        """Specs are flat at workspace/specs/, not workspace/specs/<branch>/."""
        specs = tmp_path / "specs"
        specs.mkdir()
        (specs / "design.md").write_text("spec")
        (specs / "notes.md").write_text("notes")

        result = scan_artifacts(tmp_path)
        assert len(result["specs"]) == 2
        assert "specs/design.md" in result["specs"]

    def test_does_not_use_branch_subdirectory(self, tmp_path):
        """The old branch-based spec path is dead."""
        (tmp_path / "specs" / "issue-42-feat").mkdir(parents=True)
        (tmp_path / "specs" / "issue-42-feat" / "spec.md").write_text("x")
        (tmp_path / "specs").mkdir(exist_ok=True)
        (tmp_path / "specs" / "top-level.md").write_text("y")

        result = scan_artifacts(tmp_path)
        assert result["specs"] == ["specs/top-level.md"]

    def test_finds_all_artifact_types(self, tmp_path):
        for cat in ("specs", "adr", "blog", "plans", "snapshots"):
            d = tmp_path / cat
            d.mkdir()
            (d / f"test-{cat}.md").write_text(f"# {cat}\n")
        result = scan_artifacts(tmp_path)
        for cat in ("specs", "adr", "blog", "plans", "snapshots"):
            assert len(result[cat]) == 1, f"{cat} should have 1 entry"

    def test_empty_workspace(self, tmp_path):
        result = scan_artifacts(tmp_path)
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

        (slot_workspace / "specs").mkdir()
        (slot_workspace / "specs" / "spec.md").write_text("# Spec\n")

        result = subprocess.run(
            [sys.executable, str(self.SCRIPT),
             str(workspace), str(project), "any-branch",
             f"scan-workspace={slot_workspace}"],
            capture_output=True, text=True,
        )
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
        """Without scan-workspace, scan_artifacts uses workspace."""
        workspace = tmp_path / "workspace"
        project = tmp_path / "project"
        self._init_git(workspace)
        self._init_git(project)
        (workspace / "design").mkdir()

        (workspace / "specs").mkdir()
        (workspace / "specs" / "spec.md").write_text("# Spec\n")

        result = subprocess.run(
            [sys.executable, str(self.SCRIPT),
             str(workspace), str(project), "any-branch"],
            capture_output=True, text=True,
        )
        assert result.returncode != 1
        assert "PROJECT_PROMOTED=" in result.stdout or "WORKSPACE_PROMOTED=" in result.stdout

    def test_scan_workspace_unit_scan_artifacts(self, tmp_path):
        """scan_artifacts uses the scan source path, not workspace."""
        slot = tmp_path / "slot"
        slot.mkdir()
        (slot / "specs").mkdir()
        (slot / "specs" / "design.md").write_text("spec")
        (slot / "blog").mkdir()
        (slot / "blog" / "entry.md").write_text("blog")

        result = scan_artifacts(slot)
        assert len(result["specs"]) == 1
        assert len(result["blog"]) == 1


class TestPromotionFailureDetection:
    """Tests that close_artifacts detects when promotion silently drops artifacts."""

    SCRIPT = Path(__file__).parent.parent / "work-end" / "close_artifacts.py"

    def _init_git(self, path):
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", str(path)], capture_output=True)
        subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], capture_output=True)
        subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t.com"], capture_output=True)
        subprocess.run(["git", "-C", str(path), "commit", "--allow-empty", "-m", "init"], capture_output=True)

    def test_fails_when_workspace_artifacts_found_but_none_promoted(self, tmp_path):
        """Scan finds workspace-routed artifacts but to-workspace-main returns PROMOTED=0.
        close_artifacts should exit 2 (partial failure), not 0."""
        workspace = tmp_path / "workspace"
        project = tmp_path / "project"
        scan_ws = tmp_path / "scan-ws"
        self._init_git(workspace)
        self._init_git(project)
        (workspace / "design").mkdir()
        scan_ws.mkdir()

        # Scan source has specs
        (scan_ws / "specs").mkdir()
        (scan_ws / "specs" / "design.md").write_text("# Spec\n")

        # Route specs to workspace (so they go through to-workspace-main)
        (scan_ws / "CLAUDE.md").write_text(
            "# Workspace\n\n## Routing\n\n"
            "| Artifact | Destination | Notes |\n"
            "|----------|-------------|-------|\n"
            "| specs | workspace | |\n"
        )

        # Create branch in workspace (no specs committed to it)
        subprocess.run(
            ["git", "-C", str(workspace), "checkout", "-b", "issue-42-test"],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(workspace), "checkout", "main"],
            capture_output=True, check=True,
        )

        result = subprocess.run(
            [sys.executable, str(self.SCRIPT),
             str(workspace), str(project), "issue-42-test",
             f"scan-workspace={scan_ws}"],
            capture_output=True, text=True,
        )

        assert result.returncode == 2, (
            f"Expected exit 2 (partial failure) but got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert not (workspace / "design" / ".artifacts-promoted").exists()

    def test_fails_when_project_artifacts_found_but_none_promoted(self, tmp_path):
        """Scan finds project-routed artifacts but to-project returns PROMOTED=0.
        close_artifacts should exit 2 (partial failure)."""
        workspace = tmp_path / "workspace"
        project = tmp_path / "project"
        scan_ws = tmp_path / "scan-ws"
        self._init_git(workspace)
        self._init_git(project)
        (workspace / "design").mkdir()
        scan_ws.mkdir()

        # Scan source has specs (default routing: project)
        (scan_ws / "specs").mkdir()
        (scan_ws / "specs" / "design.md").write_text("# Spec\n")

        # Workspace does NOT have these files — to-project will skip them

        result = subprocess.run(
            [sys.executable, str(self.SCRIPT),
             str(workspace), str(project), "any-branch",
             f"scan-workspace={scan_ws}"],
            capture_output=True, text=True,
        )

        assert result.returncode == 2, (
            f"Expected exit 2 (partial failure) but got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert not (workspace / "design" / ".artifacts-promoted").exists()

    def test_stamp_written_when_all_artifacts_promoted(self, tmp_path):
        """When promotion succeeds, stamp is written (regression guard)."""
        workspace = tmp_path / "workspace"
        project = tmp_path / "project"
        self._init_git(workspace)
        self._init_git(project)
        (workspace / "design").mkdir()

        # Create branch with a spec committed
        subprocess.run(
            ["git", "-C", str(workspace), "checkout", "-b", "issue-42-test"],
            capture_output=True, check=True,
        )
        (workspace / "blog").mkdir()
        (workspace / "blog" / "entry.md").write_text("# Blog\n")
        subprocess.run(["git", "-C", str(workspace), "add", "-A"], capture_output=True)
        subprocess.run(
            ["git", "-C", str(workspace), "commit", "-m", "add blog"],
            capture_output=True, check=True,
        )

        # Route blog to workspace
        (workspace / "CLAUDE.md").write_text(
            "# Workspace\n\n## Routing\n\n"
            "| Artifact | Destination | Notes |\n"
            "|----------|-------------|-------|\n"
            "| blog | workspace | |\n"
        )

        result = subprocess.run(
            [sys.executable, str(self.SCRIPT),
             str(workspace), str(project), "issue-42-test"],
            capture_output=True, text=True,
        )

        assert result.returncode == 0, (
            f"Expected exit 0 but got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


class TestCleanupSpecsRemoved:
    def test_cleanup_specs_subcommand_removed(self, tmp_path):
        """cleanup-specs is no longer a valid subcommand."""
        script = Path(__file__).parent.parent / "work-end" / "artifact_promote.py"
        result = subprocess.run(
            [sys.executable, str(script), "cleanup-specs", str(tmp_path), "branch=test"],
            capture_output=True, text=True,
        )
        assert result.returncode == 1


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
