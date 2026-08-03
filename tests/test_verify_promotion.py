"""Tests for work-end/verify_promotion.py — post-promotion evidence check."""

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "work-end" / "verify_promotion.py"


def _init_git(path):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", str(path)], capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t.com"], capture_output=True)
    subprocess.run(["git", "-C", str(path), "commit", "--allow-empty", "-m", "init"], capture_output=True)


def run_verify(workspace, project, scan_workspace=None):
    cmd = [sys.executable, str(SCRIPT), str(workspace), str(project)]
    if scan_workspace:
        cmd.append(f"scan-workspace={scan_workspace}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    out = {}
    for line in result.stdout.strip().splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return result.returncode, out


class TestSpecsVerification:
    """Specs routed to project must land at project/docs/specs/."""

    def test_verified_when_specs_at_docs_specs(self, tmp_path):
        """VERIFIED=yes when specs exist at project/docs/specs/."""
        workspace = tmp_path / "workspace"
        project = tmp_path / "project"
        _init_git(workspace)
        _init_git(project)

        # Workspace has specs (scanner source)
        (workspace / "specs").mkdir()
        (workspace / "specs" / "design.md").write_text("# Spec\n")

        # Project has them at the correct location
        (project / "docs" / "specs").mkdir(parents=True)
        (project / "docs" / "specs" / "design.md").write_text("# Spec\n")

        rc, out = run_verify(workspace, project)
        assert rc == 0
        assert out["VERIFIED"] == "yes"

    def test_fails_when_spec_at_wrong_path(self, tmp_path):
        """VERIFIED=no when spec at project/specs/ instead of project/docs/specs/."""
        workspace = tmp_path / "workspace"
        project = tmp_path / "project"
        _init_git(workspace)
        _init_git(project)

        (workspace / "specs").mkdir()
        (workspace / "specs" / "design.md").write_text("# Spec\n")

        # Wrong path — project/specs/ instead of project/docs/specs/
        (project / "specs").mkdir()
        (project / "specs" / "design.md").write_text("# Spec\n")

        rc, out = run_verify(workspace, project)
        assert rc == 0
        assert out["VERIFIED"] == "no"
        assert "specs/design.md" in out.get("MISSING_LIST", "")

    def test_fails_when_spec_missing_entirely(self, tmp_path):
        """VERIFIED=no when spec in workspace but not in project at all."""
        workspace = tmp_path / "workspace"
        project = tmp_path / "project"
        _init_git(workspace)
        _init_git(project)

        (workspace / "specs").mkdir()
        (workspace / "specs" / "design.md").write_text("# Spec\n")

        rc, out = run_verify(workspace, project)
        assert rc == 0
        assert out["VERIFIED"] == "no"
        assert int(out["MISSING"]) == 1

    def test_nested_spec_dirs_verified(self, tmp_path):
        """Nested specs (specs/issue-42/design.md) verified at docs/specs/."""
        workspace = tmp_path / "workspace"
        project = tmp_path / "project"
        _init_git(workspace)
        _init_git(project)

        (workspace / "specs" / "issue-42").mkdir(parents=True)
        (workspace / "specs" / "issue-42" / "design.md").write_text("# Spec\n")

        (project / "docs" / "specs" / "issue-42").mkdir(parents=True)
        (project / "docs" / "specs" / "issue-42" / "design.md").write_text("# Spec\n")

        rc, out = run_verify(workspace, project)
        assert rc == 0
        assert out["VERIFIED"] == "yes"


class TestWorkspaceRoutedArtifacts:
    """Artifacts routed to workspace verified on workspace main."""

    def test_workspace_blog_verified_on_main(self, tmp_path):
        """Blog routed to workspace — verified on workspace main."""
        workspace = tmp_path / "workspace"
        project = tmp_path / "project"
        _init_git(workspace)
        _init_git(project)

        # Create blog on branch
        subprocess.run(["git", "-C", str(workspace), "checkout", "-b", "feat"],
                       capture_output=True)
        (workspace / "blog").mkdir()
        (workspace / "blog" / "entry.md").write_text("# Blog\n")
        subprocess.run(["git", "-C", str(workspace), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(workspace), "commit", "-m", "blog"],
                       capture_output=True)

        # Also put it on main (simulating promotion)
        subprocess.run(["git", "-C", str(workspace), "checkout", "main"],
                       capture_output=True)
        (workspace / "blog").mkdir(exist_ok=True)
        (workspace / "blog" / "entry.md").write_text("# Blog\n")
        subprocess.run(["git", "-C", str(workspace), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(workspace), "commit", "-m", "promote blog"],
                       capture_output=True)

        # Switch back to branch for scanning
        subprocess.run(["git", "-C", str(workspace), "checkout", "feat"],
                       capture_output=True)

        # Route blog to workspace
        (workspace / "CLAUDE.md").write_text(
            "# Workspace\n\n## Routing\n\n"
            "| Artifact | Destination | Notes |\n"
            "|----------|-------------|-------|\n"
            "| blog | workspace | |\n"
        )

        rc, out = run_verify(workspace, project)
        assert rc == 0
        assert out["VERIFIED"] == "yes"


class TestEmptyWorkspace:
    """No artifacts = nothing to verify = pass."""

    def test_empty_workspace_passes(self, tmp_path):
        """VERIFIED=yes when no artifacts exist."""
        workspace = tmp_path / "workspace"
        project = tmp_path / "project"
        _init_git(workspace)
        _init_git(project)

        rc, out = run_verify(workspace, project)
        assert rc == 0
        assert out["VERIFIED"] == "yes"
        assert out["TOTAL"] == "0"


class TestScanWorkspaceParameter:
    """scan-workspace parameter for slot mode."""

    def test_scans_from_alternate_path(self, tmp_path):
        """Specs in scan-workspace, promoted to project/docs/specs/."""
        workspace = tmp_path / "workspace"
        project = tmp_path / "project"
        slot_ws = tmp_path / "slot-ws"
        _init_git(workspace)
        _init_git(project)
        slot_ws.mkdir()

        (slot_ws / "specs").mkdir()
        (slot_ws / "specs" / "design.md").write_text("# Spec\n")

        (project / "docs" / "specs").mkdir(parents=True)
        (project / "docs" / "specs" / "design.md").write_text("# Spec\n")

        rc, out = run_verify(workspace, project, scan_workspace=str(slot_ws))
        assert rc == 0
        assert out["VERIFIED"] == "yes"
