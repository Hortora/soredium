"""Tests for work-end/close_artifacts.py"""

import shutil
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

    def test_finds_specs_in_subdirectories(self, tmp_path):
        """Specs in issue-specific subdirectories are found."""
        (tmp_path / "specs" / "issue-42-feat").mkdir(parents=True)
        (tmp_path / "specs" / "issue-42-feat" / "spec.md").write_text("x")
        (tmp_path / "specs").mkdir(exist_ok=True)
        (tmp_path / "specs" / "top-level.md").write_text("y")

        result = scan_artifacts(tmp_path)
        assert "specs/top-level.md" in result["specs"]
        assert "specs/issue-42-feat/spec.md" in result["specs"]

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

    def test_promotes_workspace_artifacts_from_scan_source(self, tmp_path):
        """Scan finds workspace-routed artifacts in scan-workspace.
        With source-dir fix, to-workspace-main copies from scan source.
        Previously this was BUG 1 — branch not available, all skipped."""
        workspace = tmp_path / "workspace"
        project = tmp_path / "project"
        scan_ws = tmp_path / "scan-ws"
        self._init_git(workspace)
        self._init_git(project)
        (workspace / "design").mkdir()
        scan_ws.mkdir()

        (scan_ws / "specs").mkdir()
        (scan_ws / "specs" / "design.md").write_text("# Spec\n")

        (scan_ws / "CLAUDE.md").write_text(
            "# Workspace\n\n## Routing\n\n"
            "| Artifact | Destination | Notes |\n"
            "|----------|-------------|-------|\n"
            "| specs | workspace | |\n"
        )

        result = subprocess.run(
            [sys.executable, str(self.SCRIPT),
             str(workspace), str(project), "issue-42-test",
             f"scan-workspace={scan_ws}"],
            capture_output=True, text=True,
        )

        assert result.returncode == 0, (
            f"Expected exit 0 but got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_promotes_project_artifacts_from_scan_source(self, tmp_path):
        """Scan finds project-routed artifacts in scan-workspace.
        With scan_source fix, to-project reads from scan source.
        Previously this was BUG 2 — read from original workspace, all skipped."""
        workspace = tmp_path / "workspace"
        project = tmp_path / "project"
        scan_ws = tmp_path / "scan-ws"
        self._init_git(workspace)
        self._init_git(project)
        (workspace / "design").mkdir()
        scan_ws.mkdir()

        (scan_ws / "specs").mkdir()
        (scan_ws / "specs" / "design.md").write_text("# Spec\n")

        result = subprocess.run(
            [sys.executable, str(self.SCRIPT),
             str(workspace), str(project), "any-branch",
             f"scan-workspace={scan_ws}"],
            capture_output=True, text=True,
        )

        out = {}
        for line in result.stdout.strip().splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                out[k] = v

        assert out.get("PROJECT_PROMOTED") == "1", (
            f"Expected PROJECT_PROMOTED=1 but got {out.get('PROJECT_PROMOTED', '0')}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert (project / "docs" / "specs" / "design.md").is_file()

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
            f"Expected exit 0 (stamp written) but got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_push_failure_blocks_stamp(self, tmp_path):
        """Promotion succeeds but push fails (remote broken) → exit 2, no stamp."""
        workspace = tmp_path / "workspace"
        project = tmp_path / "project"
        remote = tmp_path / "remote.git"
        self._init_git(workspace)
        self._init_git(project)
        (workspace / "design").mkdir()

        subprocess.run(["git", "init", "--bare", str(remote)], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(workspace), "remote", "add", "origin", str(remote)], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(workspace), "push", "-u", "origin", "main"], capture_output=True, check=True)

        subprocess.run(["git", "-C", str(workspace), "checkout", "-b", "issue-42-test"], capture_output=True, check=True)
        (workspace / "blog").mkdir()
        (workspace / "blog" / "entry.md").write_text("# Blog\n")
        subprocess.run(["git", "-C", str(workspace), "add", "-A"], capture_output=True)
        subprocess.run(["git", "-C", str(workspace), "commit", "-m", "add blog"], capture_output=True, check=True)

        (workspace / "CLAUDE.md").write_text(
            "# Workspace\n\n## Routing\n\n"
            "| Artifact | Destination | Notes |\n"
            "|----------|-------------|-------|\n"
            "| blog | workspace | |\n"
        )

        shutil.rmtree(remote)

        result = subprocess.run(
            [sys.executable, str(self.SCRIPT),
             str(workspace), str(project), "issue-42-test"],
            capture_output=True, text=True,
        )

        assert result.returncode == 2, (
            f"Expected exit 2 (push failure) but got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert not (workspace / "design" / ".artifacts-promoted").exists()


class TestPostPushVerification:
    """After push, artifact_promote must verify artifacts are on origin/main."""

    SCRIPT = Path(__file__).parent.parent / "work-end" / "artifact_promote.py"

    def _init_repo_with_remote(self, path):
        remote = path.parent / f".{path.name}-bare.git"
        remote.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "--bare", str(remote)], capture_output=True, check=True)
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", str(remote), str(path)], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], capture_output=True)
        subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t.com"], capture_output=True)
        subprocess.run(["git", "-C", str(path), "checkout", "-b", "main"], capture_output=True)
        (path / "README.md").write_text("# test\n")
        subprocess.run(["git", "-C", str(path), "add", "."], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(path), "commit", "-m", "init"], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(path), "push", "-u", "origin", "main"], capture_output=True, check=True)
        return path, remote

    def test_reports_verified_after_successful_push(self, tmp_path):
        """After push succeeds, PUSH_VERIFIED=yes confirms artifacts on origin/main."""
        ws, remote = self._init_repo_with_remote(tmp_path / "workspace")

        subprocess.run(["git", "-C", str(ws), "checkout", "-b", "feat"], capture_output=True, check=True)
        (ws / "blog").mkdir()
        (ws / "blog" / "entry.md").write_text("# Blog\n")
        subprocess.run(["git", "-C", str(ws), "add", "."], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(ws), "commit", "-m", "add blog"], capture_output=True, check=True)

        result = subprocess.run(
            [sys.executable, str(self.SCRIPT), "to-workspace-main", str(ws),
             "branch=feat", "artifacts=blog/entry.md"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "PUSHED=yes" in result.stdout
        assert "PUSH_VERIFIED=yes" in result.stdout

    def test_push_failure_triggers_no_verification(self, tmp_path):
        """When push itself fails, PUSHED=failed is reported and no verification runs."""
        ws, remote = self._init_repo_with_remote(tmp_path / "workspace")

        subprocess.run(["git", "-C", str(ws), "checkout", "-b", "feat"], capture_output=True, check=True)
        (ws / "blog").mkdir()
        (ws / "blog" / "entry.md").write_text("# Blog\n")
        subprocess.run(["git", "-C", str(ws), "add", "."], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(ws), "commit", "-m", "add blog"], capture_output=True, check=True)

        # Break the remote so push fails
        shutil.rmtree(remote)

        result = subprocess.run(
            [sys.executable, str(self.SCRIPT), "to-workspace-main", str(ws),
             "branch=feat", "artifacts=blog/entry.md"],
            capture_output=True, text=True,
        )
        assert "PUSHED=failed" in result.stdout
        assert "PUSH_VERIFIED" not in result.stdout, "Verification should not run when push fails"


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

    def test_archive_plans_skips_on_checkout_failure(self, tmp_path):
        """When git checkout branch -- plan fails, the plan is skipped and not
        archived with the stale main version. Regression test for bare pass."""
        ws = tmp_path / "workspace"
        ws.mkdir()
        subprocess.run(["git", "init", str(ws)], capture_output=True)
        subprocess.run(["git", "-C", str(ws), "config", "user.name", "Test"], capture_output=True)
        subprocess.run(["git", "-C", str(ws), "config", "user.email", "t@t.com"], capture_output=True)
        subprocess.run(["git", "-C", str(ws), "checkout", "-b", "main"], capture_output=True)

        plans = ws / "plans"
        plans.mkdir()
        (plans / "good.md").write_text("good plan")
        (plans / "bad.md").write_text("stale main version — should NOT be archived")
        subprocess.run(["git", "-C", str(ws), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(ws), "commit", "-m", "add plans"], capture_output=True)

        # Create branch with both files
        subprocess.run(["git", "-C", str(ws), "checkout", "-b", "issue-99"], capture_output=True)
        (plans / "good.md").write_text("good plan — branch version")
        (plans / "bad.md").write_text("bad plan — branch version")
        subprocess.run(["git", "-C", str(ws), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(ws), "commit", "-m", "update plans"], capture_output=True)

        import importlib
        ap = importlib.import_module("artifact_promote")

        original_git = ap.git

        def mock_git(*cmd, cwd):
            if cmd[:2] == ("checkout", "issue-99") and "--" in cmd and "plans/bad.md" in cmd:
                raise subprocess.CalledProcessError(1, cmd, stderr="error: simulated failure")
            return original_git(*cmd, cwd=cwd)

        with patch.object(ap, "git", side_effect=mock_git):
            rc = ap.archive_plans(str(ws), {"branch": "issue-99"})

        assert rc == 0

        # Switch to main to see the attic (archive commits on main)
        subprocess.run(["git", "-C", str(ws), "checkout", "main"], capture_output=True)

        # good.md was archived (checkout succeeded)
        attic = plans / "attic" / "issue-99"
        assert (attic / "good.md").exists()

        # bad.md was NOT archived (checkout failed → skipped)
        assert not (attic / "bad.md").exists()


# ===========================================================================
# BUG 2: Slot mode — to_project reads from scan_source, not workspace
# ===========================================================================

class TestSlotModeProjectPromotion:
    """Slot mode: scan_source has artifacts, but to_project reads from
    workspace (original, on main) where they don't exist."""

    SCRIPT = Path(__file__).parent.parent / "work-end" / "close_artifacts.py"

    def _init_git(self, path):
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", str(path)], capture_output=True)
        subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], capture_output=True)
        subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t.com"], capture_output=True)
        subprocess.run(["git", "-C", str(path), "commit", "--allow-empty", "-m", "init"], capture_output=True)

    def test_promotes_to_project_from_scan_source(self, tmp_path):
        """When scan-workspace is set, to_project should read artifacts from
        the scan source (slot workspace), not the original workspace.
        BUG 2 regression test."""
        workspace = tmp_path / "original-workspace"
        project = tmp_path / "project"
        slot_ws = tmp_path / "slot-workspace"
        self._init_git(workspace)
        self._init_git(project)
        (workspace / "design").mkdir()

        # Slot workspace has a spec (not the original workspace)
        (slot_ws / "specs").mkdir(parents=True)
        (slot_ws / "specs" / "design.md").write_text("# Spec from slot\n")

        result = subprocess.run(
            [sys.executable, str(self.SCRIPT),
             str(workspace), str(project), "issue-42-test",
             f"scan-workspace={slot_ws}"],
            capture_output=True, text=True,
        )

        out = {}
        for line in result.stdout.strip().splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                out[k] = v

        assert out.get("PROJECT_PROMOTED", "0") != "0", (
            f"Expected PROJECT_PROMOTED >= 1 but got {out.get('PROJECT_PROMOTED', '0')}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert (project / "docs" / "specs" / "design.md").is_file()


# ===========================================================================
# BUG 3: Slot mode — archive_plans with source-dir
# ===========================================================================

class TestSlotModeArchivePlans:
    """Slot mode: archive_plans needs source-dir to copy plans from
    slot workspace when branch doesn't exist on original workspace."""

    def test_archives_from_source_dir(self, tmp_path):
        """Plans should be archived from source-dir when the branch
        doesn't exist on the original workspace. BUG 3 regression test."""
        ws = tmp_path / "original-workspace"
        ws.mkdir()
        subprocess.run(["git", "init", str(ws)], capture_output=True)
        subprocess.run(["git", "-C", str(ws), "config", "user.name", "Test"], capture_output=True)
        subprocess.run(["git", "-C", str(ws), "config", "user.email", "t@t.com"], capture_output=True)
        subprocess.run(["git", "-C", str(ws), "checkout", "-b", "main"], capture_output=True)
        (ws / "plans").mkdir()
        (ws / "plans" / ".gitkeep").write_text("")
        subprocess.run(["git", "-C", str(ws), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(ws), "commit", "-m", "init"], capture_output=True)

        # Slot workspace has a plan file
        slot_ws = tmp_path / "slot-workspace"
        (slot_ws / "plans").mkdir(parents=True)
        (slot_ws / "plans" / "implementation.md").write_text("# Plan\n")

        script = Path(__file__).parent.parent / "work-end" / "artifact_promote.py"
        result = subprocess.run(
            [sys.executable, str(script), "archive-plans", str(ws),
             "branch=issue-42-test", f"source-dir={slot_ws}"],
            capture_output=True, text=True,
        )

        out = {}
        for line in result.stdout.strip().splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                out[k] = v

        assert result.returncode == 0
        assert int(out.get("ARCHIVED", "0")) >= 1, (
            f"Expected ARCHIVED >= 1 but got {out.get('ARCHIVED', '0')}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

        subprocess.run(["git", "-C", str(ws), "checkout", "main"], capture_output=True)
        attic = ws / "plans" / "attic" / "issue-42-test"
        assert (attic / "implementation.md").exists()


# ===========================================================================
# End-to-end: slot mode through close_artifacts.py
# ===========================================================================

class TestSlotModeEndToEnd:
    """Integration: close_artifacts.py with scan-workspace, both routing paths."""

    SCRIPT = Path(__file__).parent.parent / "work-end" / "close_artifacts.py"

    def _init_git(self, path):
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", str(path)], capture_output=True)
        subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], capture_output=True)
        subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t.com"], capture_output=True)
        subprocess.run(["git", "-C", str(path), "commit", "--allow-empty", "-m", "init"], capture_output=True)

    def test_promotes_both_workspace_and_project_artifacts(self, tmp_path):
        """Slot workspace has blog (workspace-routed) and specs (project-routed).
        Both should be promoted successfully."""
        workspace = tmp_path / "workspace"
        project = tmp_path / "project"
        slot_ws = tmp_path / "slot-ws"
        self._init_git(workspace)
        self._init_git(project)
        (workspace / "design").mkdir()

        (slot_ws / "blog").mkdir(parents=True)
        (slot_ws / "blog" / "entry.md").write_text("# Blog\n")
        (slot_ws / "specs").mkdir()
        (slot_ws / "specs" / "design.md").write_text("# Spec\n")

        (slot_ws / "CLAUDE.md").write_text(
            "# Workspace\n\n## Routing\n\n"
            "| Artifact | Destination | Notes |\n"
            "|----------|-------------|-------|\n"
            "| blog | workspace | |\n"
            "| specs | project | |\n"
        )

        result = subprocess.run(
            [sys.executable, str(self.SCRIPT),
             str(workspace), str(project), "issue-42-test",
             f"scan-workspace={slot_ws}"],
            capture_output=True, text=True,
        )

        out = {}
        for line in result.stdout.strip().splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                out[k] = v

        assert out.get("WORKSPACE_PROMOTED", "0") != "0", (
            f"Blog not promoted to workspace.\nstdout: {result.stdout}"
        )
        assert out.get("PROJECT_PROMOTED", "0") != "0", (
            f"Spec not promoted to project.\nstdout: {result.stdout}"
        )
        assert (project / "docs" / "specs" / "design.md").is_file()

    def test_archives_plans_in_slot_mode(self, tmp_path):
        """Plans in scan-workspace are archived to original workspace attic."""
        workspace = tmp_path / "workspace"
        project = tmp_path / "project"
        slot_ws = tmp_path / "slot-ws"
        self._init_git(workspace)
        self._init_git(project)
        (workspace / "design").mkdir()
        (workspace / "plans").mkdir()
        subprocess.run(["git", "-C", str(workspace), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(workspace), "commit", "-m", "dirs"], capture_output=True)

        (slot_ws / "plans").mkdir(parents=True)
        (slot_ws / "plans" / "impl.md").write_text("# Plan\n")

        result = subprocess.run(
            [sys.executable, str(self.SCRIPT),
             str(workspace), str(project), "issue-99-test",
             f"scan-workspace={slot_ws}"],
            capture_output=True, text=True,
        )

        out = {}
        for line in result.stdout.strip().splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                out[k] = v

        assert int(out.get("PLANS_ARCHIVED", "0")) >= 1, (
            f"Plans not archived.\nstdout: {result.stdout}"
        )


class TestSpecPathRemapping:
    """Specs must land at project/docs/specs/, not project/specs/."""

    SCRIPT = Path(__file__).parent.parent / "work-end" / "artifact_promote.py"

    def _init_git(self, path):
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", str(path)], capture_output=True)
        subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], capture_output=True)
        subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t.com"], capture_output=True)
        subprocess.run(["git", "-C", str(path), "commit", "--allow-empty", "-m", "init"], capture_output=True)

    def test_to_project_remaps_specs_to_docs_specs(self, tmp_path):
        """to-project with dest-prefix=docs/ puts specs at project/docs/specs/."""
        project = tmp_path / "project"
        workspace = tmp_path / "workspace"
        self._init_git(project)
        workspace.mkdir()
        (workspace / "specs").mkdir()
        (workspace / "specs" / "design.md").write_text("# Spec\n")

        result = subprocess.run(
            [sys.executable, str(self.SCRIPT),
             "to-project", str(project), str(workspace),
             "artifacts=specs/design.md", "dest-prefix=docs/"],
            capture_output=True, text=True,
        )

        assert result.returncode == 0
        assert "PROMOTED=1" in result.stdout
        assert (project / "docs" / "specs" / "design.md").is_file()
        assert not (project / "specs" / "design.md").exists()

    def test_to_project_remaps_nested_spec_dirs(self, tmp_path):
        """Nested spec dirs also get the docs/ prefix."""
        project = tmp_path / "project"
        workspace = tmp_path / "workspace"
        self._init_git(project)
        workspace.mkdir()
        (workspace / "specs" / "issue-42-feat").mkdir(parents=True)
        (workspace / "specs" / "issue-42-feat" / "design.md").write_text("# Spec\n")

        result = subprocess.run(
            [sys.executable, str(self.SCRIPT),
             "to-project", str(project), str(workspace),
             "artifacts=specs/issue-42-feat/design.md", "dest-prefix=docs/"],
            capture_output=True, text=True,
        )

        assert result.returncode == 0
        assert (project / "docs" / "specs" / "issue-42-feat" / "design.md").is_file()

    def test_to_project_no_prefix_preserves_path(self, tmp_path):
        """Without dest-prefix, behavior is unchanged (regression guard)."""
        project = tmp_path / "project"
        workspace = tmp_path / "workspace"
        self._init_git(project)
        workspace.mkdir()
        (workspace / "specs").mkdir()
        (workspace / "specs" / "design.md").write_text("# Spec\n")

        result = subprocess.run(
            [sys.executable, str(self.SCRIPT),
             "to-project", str(project), str(workspace),
             "artifacts=specs/design.md"],
            capture_output=True, text=True,
        )

        assert result.returncode == 0
        assert (project / "specs" / "design.md").is_file()


class TestImagePromotion:
    """Image refs in markdown are included in scan results."""

    def test_image_promoted_alongside_markdown(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        specs = ws / "specs"
        specs.mkdir()
        (specs / "design.md").write_text("# Design\n\n![Arch](images/arch.svg)\n")
        img = specs / "images" / "arch.svg"
        img.parent.mkdir()
        img.write_text("<svg/>")

        result = scan_artifacts(ws)
        assert "specs/design.md" in result["specs"]
        assert "specs/images/arch.svg" in result["specs"]

    def test_blog_image_in_scan_results(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        blog = ws / "blog"
        blog.mkdir()
        (blog / "entry.md").write_text("![Photo](photo.png)\n")
        (blog / "photo.png").write_bytes(b"\x89PNG")

        result = scan_artifacts(ws)
        assert "blog/entry.md" in result["blog"]
        assert "blog/photo.png" in result["blog"]


# ===========================================================================
# Issue #181: stamp not committed, promote skips updated files
# ===========================================================================

class TestStampCommitReliability:
    """Bug #181.1: .artifacts-promoted stamp must be committed atomically.

    If to_workspace_main() fails to return to the branch (checkout fails
    silently), write_stamp() writes the stamp on the wrong branch.
    """

    SCRIPT = Path(__file__).parent.parent / "work-end" / "close_artifacts.py"

    def _init_git(self, path):
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", str(path)], capture_output=True)
        subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], capture_output=True)
        subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t.com"], capture_output=True)
        subprocess.run(["git", "-C", str(path), "commit", "--allow-empty", "-m", "init"], capture_output=True)

    def test_stamp_committed_on_branch_not_main(self, tmp_path):
        """After promotion, stamp must be a committed file on the branch,
        not an untracked file on main or the wrong branch."""
        workspace = tmp_path / "workspace"
        project = tmp_path / "project"
        self._init_git(workspace)
        self._init_git(project)
        (workspace / "design").mkdir()

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
        assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"

        # Workspace must be back on the branch after close_artifacts completes
        branch_result = subprocess.run(
            ["git", "-C", str(workspace), "branch", "--show-current"],
            capture_output=True, text=True,
        )
        assert branch_result.stdout.strip() == "issue-42-test", (
            f"Workspace should be on issue-42-test but is on {branch_result.stdout.strip()}"
        )

        # Stamp must be committed (not untracked)
        status = subprocess.run(
            ["git", "-C", str(workspace), "status", "--short"],
            capture_output=True, text=True,
        )
        assert ".artifacts-promoted" not in status.stdout, (
            f"Stamp is untracked/modified — not committed:\n{status.stdout}"
        )

        # Stamp must exist in the git tree on this branch
        cat_result = subprocess.run(
            ["git", "-C", str(workspace), "cat-file", "-e", "HEAD:design/.artifacts-promoted"],
            capture_output=True,
        )
        assert cat_result.returncode == 0, (
            "Stamp not in git tree on branch HEAD"
        )


class TestPromoteUpdatedFiles:
    """Bug #181.2: promote must overwrite files already on main, not skip them.

    If a spec was manually recovered to workspace main and then the branch
    edits it further, to_workspace_main() must overwrite the stale version
    on main with the branch version.
    """

    def _init_git(self, path):
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", str(path)], capture_output=True)
        subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], capture_output=True)
        subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t.com"], capture_output=True)
        subprocess.run(["git", "-C", str(path), "commit", "--allow-empty", "-m", "init"], capture_output=True)

    def test_overwrites_stale_spec_on_main(self, tmp_path):
        """A spec exists on main (from prior recovery) and an updated version
        exists on the branch. Promotion must use the branch version."""
        ws = tmp_path / "workspace"
        self._init_git(ws)

        # Put a stale spec on main
        (ws / "specs").mkdir()
        (ws / "specs" / "design.md").write_text("# Spec v1 — stale\n")
        subprocess.run(["git", "-C", str(ws), "add", "-A"], capture_output=True)
        subprocess.run(["git", "-C", str(ws), "commit", "-m", "recover spec"], capture_output=True)

        # Create branch with updated spec
        subprocess.run(
            ["git", "-C", str(ws), "checkout", "-b", "issue-74-test"],
            capture_output=True, check=True,
        )
        (ws / "specs" / "design.md").write_text("# Spec v2 — updated with 213 more lines\n" + "x\n" * 213)
        subprocess.run(["git", "-C", str(ws), "add", "-A"], capture_output=True)
        subprocess.run(
            ["git", "-C", str(ws), "commit", "-m", "update spec"],
            capture_output=True, check=True,
        )

        script = Path(__file__).parent.parent / "work-end" / "artifact_promote.py"
        result = subprocess.run(
            [sys.executable, str(script),
             "to-workspace-main", str(ws),
             "branch=issue-74-test",
             "artifacts=specs/design.md"],
            capture_output=True, text=True,
        )

        assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
        assert "PROMOTED=1" in result.stdout, (
            f"Expected PROMOTED=1 but got:\n{result.stdout}"
        )

        # Verify the promoted version is v2, not v1
        subprocess.run(["git", "-C", str(ws), "checkout", "main"], capture_output=True)
        content = (ws / "specs" / "design.md").read_text()
        assert "v2" in content, (
            f"Main has stale spec — promotion did not overwrite.\nContent: {content[:100]}"
        )
        assert "v1" not in content

    def test_promote_reports_count_even_when_overwriting(self, tmp_path):
        """When a file already exists on main with different content,
        promote must still count it as promoted (not skip it)."""
        ws = tmp_path / "workspace"
        self._init_git(ws)

        (ws / "blog").mkdir()
        (ws / "blog" / "entry.md").write_text("# Entry v1\n")
        subprocess.run(["git", "-C", str(ws), "add", "-A"], capture_output=True)
        subprocess.run(["git", "-C", str(ws), "commit", "-m", "old blog"], capture_output=True)

        subprocess.run(
            ["git", "-C", str(ws), "checkout", "-b", "issue-99-test"],
            capture_output=True, check=True,
        )
        (ws / "blog" / "entry.md").write_text("# Entry v2 — updated\n")
        subprocess.run(["git", "-C", str(ws), "add", "-A"], capture_output=True)
        subprocess.run(
            ["git", "-C", str(ws), "commit", "-m", "update blog"],
            capture_output=True, check=True,
        )

        script = Path(__file__).parent.parent / "work-end" / "artifact_promote.py"
        result = subprocess.run(
            [sys.executable, str(script),
             "to-workspace-main", str(ws),
             "branch=issue-99-test",
             "artifacts=blog/entry.md"],
            capture_output=True, text=True,
        )

        assert result.returncode == 0
        assert "PROMOTED=1" in result.stdout, (
            f"File was skipped instead of overwritten:\n{result.stdout}"
        )

    def test_promote_noop_when_content_identical(self, tmp_path):
        """When file on main is identical to branch version (prior manual
        recovery was up to date), promote should still succeed (count as
        promoted) even though git sees nothing to commit."""
        ws = tmp_path / "workspace"
        self._init_git(ws)

        (ws / "specs").mkdir()
        (ws / "specs" / "design.md").write_text("# Identical content\n")
        subprocess.run(["git", "-C", str(ws), "add", "-A"], capture_output=True)
        subprocess.run(["git", "-C", str(ws), "commit", "-m", "spec on main"], capture_output=True)

        subprocess.run(
            ["git", "-C", str(ws), "checkout", "-b", "issue-88-test"],
            capture_output=True, check=True,
        )
        # Don't change the file — content is identical
        subprocess.run(["git", "-C", str(ws), "commit", "--allow-empty", "-m", "branch work"], capture_output=True)

        script = Path(__file__).parent.parent / "work-end" / "artifact_promote.py"
        result = subprocess.run(
            [sys.executable, str(script),
             "to-workspace-main", str(ws),
             "branch=issue-88-test",
             "artifacts=specs/design.md"],
            capture_output=True, text=True,
        )

        # Should succeed even though nothing to commit
        assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
        assert "PROMOTED=1" in result.stdout
