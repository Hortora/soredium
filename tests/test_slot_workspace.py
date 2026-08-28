"""Tests for work-slot/slot_workspace.py"""

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

skill_dir = Path(__file__).parent.parent / "work-slot"
sys.path.insert(0, str(skill_dir))

import slot_workspace
from slot_core import run_cmd
from slot_test_helpers import init_repo, init_repo_with_workspace


class TestResolveWorkspaceSource:
    def test_resolves_to_child_not_parent(self, tmp_path):
        """When child workspace is nested inside a parent git repo,
        resolve to the child (the actual workspace repo)."""
        parent = init_repo(tmp_path / "public" / "casehub")
        child = init_repo(parent / "engine")
        subprocess.run(["git", "-C", str(child), "remote", "add", "origin",
                         "https://github.com/mdproctor/wsp-casehub-engine.git"],
                        capture_output=True, check=True)
        repo = tmp_path / "casehub" / "engine"
        repo.mkdir(parents=True)
        (repo / "wksp").symlink_to(child)

        src, name = slot_workspace.resolve_workspace_source(repo)
        assert src == child
        assert name == "wsp-casehub-engine"

    def test_name_from_remote_url(self, tmp_path):
        """Slot name derived from workspace repo's origin remote URL."""
        ws_repo = init_repo(tmp_path / "workspace")
        subprocess.run(["git", "-C", str(ws_repo), "remote", "add", "origin",
                         "https://github.com/mdproctor/wsp-casehub-connectors.git"],
                        capture_output=True, check=True)
        repo = tmp_path / "project"
        repo.mkdir(parents=True)
        (repo / "wksp").symlink_to(ws_repo)

        src, name = slot_workspace.resolve_workspace_source(repo)
        assert src == ws_repo
        assert name == "wsp-casehub-connectors"

    def test_fallback_name_when_no_remote(self, tmp_path):
        """When workspace repo has no remote, construct name from path."""
        ws_repo = init_repo(tmp_path / "public" / "casehub" / "connectors")
        repo = tmp_path / "project"
        repo.mkdir(parents=True)
        (repo / "wksp").symlink_to(ws_repo)

        src, name = slot_workspace.resolve_workspace_source(repo)
        assert src == ws_repo
        assert name == "wsp-casehub-connectors"

    def test_external_workspace_single_repo(self, tmp_path):
        """External workspace (no parent git repo) resolves directly."""
        ext_ws = init_repo(tmp_path / "public" / "casehub-iot")
        subprocess.run(["git", "-C", str(ext_ws), "remote", "add", "origin",
                         "https://github.com/mdproctor/wsp-casehub-iot.git"],
                        capture_output=True, check=True)
        repo = tmp_path / "casehub" / "iot"
        repo.mkdir(parents=True)
        (repo / "wksp").symlink_to(ext_ws)

        src, name = slot_workspace.resolve_workspace_source(repo)
        assert src == ext_ws
        assert name == "wsp-casehub-iot"

    def test_no_wksp_symlink(self, tmp_path):
        repo = tmp_path / "casehub" / "engine"
        repo.mkdir(parents=True)
        result = slot_workspace.resolve_workspace_source(repo)
        assert result is None

    def test_wksp_points_to_nonexistent(self, tmp_path):
        repo = tmp_path / "project"
        repo.mkdir(parents=True)
        (repo / "wksp").symlink_to(tmp_path / "nonexistent")
        result = slot_workspace.resolve_workspace_source(repo)
        assert result is None



class TestDiscoverWorkspace:
    @patch("slot_workspace.run_cmd")
    def test_discovers_via_public_path(self, mock_cmd, tmp_path):
        """discover_workspace finds ~/claude/public/<family>/<repo>."""
        family = tmp_path / "casehub"
        family.mkdir()
        engine = family / "engine"
        engine.mkdir()

        public_ws = tmp_path / "claude" / "public" / "casehub" / "engine"
        public_ws.mkdir(parents=True)

        mock_cmd.return_value = (0, str(public_ws), "")

        with patch("slot_workspace.Path.home", return_value=tmp_path):
            result = slot_workspace.discover_workspace(engine)

        assert result is not None
        assert result[0] == public_ws

    @patch("slot_workspace.run_cmd")
    def test_discovers_via_sibling_proj_symlink(self, mock_cmd, tmp_path):
        """discover_workspace finds a sibling dir with proj -> repo_path."""
        family = tmp_path / "casehub"
        family.mkdir()
        engine = family / "engine"
        engine.mkdir()
        work = family / "work"
        work.mkdir()
        (work / "proj").symlink_to(engine)

        mock_cmd.return_value = (0, str(work), "")

        with patch("slot_workspace.Path.home", return_value=tmp_path):
            result = slot_workspace.discover_workspace(engine)

        assert result is not None
        assert result[0] == work

    @patch("slot_workspace.run_cmd")
    def test_returns_none_when_nothing_found(self, mock_cmd, tmp_path):
        """discover_workspace returns None when no workspace can be found."""
        family = tmp_path / "casehub"
        family.mkdir()
        engine = family / "engine"
        engine.mkdir()

        with patch("slot_workspace.Path.home", return_value=tmp_path):
            result = slot_workspace.discover_workspace(engine)

        assert result is None



class TestRepointSymlinks:
    def test_repoints_wksp_in_repo(self, tmp_path):
        repo_wt = tmp_path / "slot" / "engine"
        repo_wt.mkdir(parents=True)
        (repo_wt / "wksp").symlink_to("/original/workspace/engine")
        ws_wt = tmp_path / "slot" / "work"
        (ws_wt / "engine").mkdir(parents=True)

        slot_workspace.repoint_wksp(repo_wt, ws_wt / "engine")

        assert (repo_wt / "wksp").is_symlink()
        target = (repo_wt / "wksp").readlink()
        assert "work/engine" in str(target)

    def test_creates_proj_in_workspace(self, tmp_path):
        ws_subdir = tmp_path / "slot" / "work" / "engine"
        ws_subdir.mkdir(parents=True)
        repo_wt = tmp_path / "slot" / "engine"
        repo_wt.mkdir(parents=True)

        slot_workspace.create_proj_symlink(ws_subdir, repo_wt)

        assert (ws_subdir / "proj").is_symlink()
        target = (ws_subdir / "proj").readlink()
        assert "engine" in str(target)

    def test_repoint_replaces_existing(self, tmp_path):
        repo_wt = tmp_path / "slot" / "engine"
        repo_wt.mkdir(parents=True)
        (repo_wt / "wksp").symlink_to("/old/target")
        new_target = tmp_path / "slot" / "work" / "engine"
        new_target.mkdir(parents=True)

        slot_workspace.repoint_wksp(repo_wt, new_target)

        assert (repo_wt / "wksp").is_symlink()
        resolved = (repo_wt / "wksp").resolve()
        assert resolved == new_target



class TestUnignoreSubdir:
    """Tests for _unignore_subdir — removes gitignore entries that hide workspace subdirs in slots."""

    def test_removes_slash_prefix_entry(self, tmp_path):
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("/claudony\n/connectors\n/engine\n")
        slot_workspace._unignore_subdir(tmp_path, "claudony")
        content = gitignore.read_text()
        assert "/claudony" not in content
        assert "/connectors" in content
        assert "/engine" in content

    def test_removes_bare_name_entry(self, tmp_path):
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("claudony\nother\n")
        slot_workspace._unignore_subdir(tmp_path, "claudony")
        content = gitignore.read_text()
        assert "claudony" not in content
        assert "other" in content

    def test_removes_trailing_slash_entry(self, tmp_path):
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("/claudony/\nother\n")
        slot_workspace._unignore_subdir(tmp_path, "claudony")
        content = gitignore.read_text()
        assert "claudony" not in content

    def test_no_gitignore_file(self, tmp_path):
        slot_workspace._unignore_subdir(tmp_path, "claudony")

    def test_subdir_not_in_gitignore(self, tmp_path):
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("/engine\n/connectors\n")
        slot_workspace._unignore_subdir(tmp_path, "claudony")
        content = gitignore.read_text()
        assert "/engine" in content
        assert "/connectors" in content

    def test_preserves_other_entries(self, tmp_path):
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("*.pyc\n__pycache__\n/claudony\n.DS_Store\n")
        slot_workspace._unignore_subdir(tmp_path, "claudony")
        content = gitignore.read_text()
        assert "*.pyc" in content
        assert "__pycache__" in content
        assert ".DS_Store" in content
        assert "claudony" not in content

    def test_artifact_committable_after_unignore(self, tmp_path):
        """Integration: after _unignore_subdir, files in the subdirectory
        are visible to git and can be committed. Regression test for #148."""
        ws = tmp_path / "workspace"
        ws.mkdir()
        subprocess.run(["git", "init", str(ws)], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(ws), "config", "user.name", "Test"], capture_output=True)
        subprocess.run(["git", "-C", str(ws), "config", "user.email", "t@t.com"], capture_output=True)

        (ws / ".gitignore").write_text("/claudony\n")
        subprocess.run(["git", "-C", str(ws), "add", ".gitignore"], capture_output=True)
        subprocess.run(["git", "-C", str(ws), "commit", "-m", "init"], capture_output=True)

        subdir = ws / "claudony" / "blog"
        subdir.mkdir(parents=True)
        (subdir / "entry.md").write_text("# Blog Entry\n")

        check_before = subprocess.run(
            ["git", "-C", str(ws), "status", "--short"],
            capture_output=True, text=True,
        )
        assert "claudony" not in check_before.stdout, "dir should be invisible before fix"

        slot_workspace._unignore_subdir(ws, "claudony")

        check_after = subprocess.run(
            ["git", "-C", str(ws), "status", "--short"],
            capture_output=True, text=True,
        )
        assert "claudony" in check_after.stdout, "dir should be visible after fix"

        subprocess.run(["git", "-C", str(ws), "add", "claudony/blog/entry.md"], capture_output=True)
        result = subprocess.run(
            ["git", "-C", str(ws), "commit", "-m", "add blog entry"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"commit should succeed: {result.stderr}"



class TestValidateSlotWksp:
    def test_passes_when_symlinks_resolve(self, tmp_path):
        """All repo clones have working wksp/ symlinks."""
        family = tmp_path / "casehub"
        family.mkdir()
        original = init_repo(family / "engine")
        ws_dir = tmp_path / "workspace"
        ws_dir.mkdir()
        (ws_dir / "engine").mkdir()
        (original / "wksp").symlink_to(ws_dir / "engine")

        slot_dir = tmp_path / "slots" / "1"
        slot_dir.mkdir(parents=True)
        clone = init_repo(slot_dir / "engine")
        ws_slot = slot_dir / "work" / "engine"
        ws_slot.mkdir(parents=True)
        (clone / "wksp").symlink_to(os.path.relpath(ws_slot, clone))

        failures = slot_workspace.validate_slot_wksp(slot_dir)
        assert failures == []

    def test_fails_when_symlink_dangling(self, tmp_path):
        """wksp/ points to a non-existent directory."""
        family = tmp_path / "casehub"
        family.mkdir()
        original = init_repo(family / "engine")
        (original / "wksp").symlink_to("/nonexistent/path")

        slot_dir = tmp_path / "slots" / "1"
        slot_dir.mkdir(parents=True)
        clone = init_repo(slot_dir / "engine")
        (clone / "wksp").symlink_to("/nonexistent/path")

        failures = slot_workspace.validate_slot_wksp(slot_dir)
        assert len(failures) == 1
        assert "engine" in failures[0]

    def test_fails_when_symlink_missing(self, tmp_path):
        """Original has wksp/ but clone doesn't."""
        family = tmp_path / "casehub"
        family.mkdir()
        original = init_repo(family / "engine")
        ws_dir = tmp_path / "workspace"
        ws_dir.mkdir()
        (original / "wksp").symlink_to(ws_dir)

        slot_dir = tmp_path / "slots" / "1"
        slot_dir.mkdir(parents=True)
        clone = init_repo(slot_dir / "engine")

        subprocess.run(["git", "-C", str(clone), "remote", "add", "local", str(original)], capture_output=True)

        failures = slot_workspace.validate_slot_wksp(slot_dir)
        assert len(failures) == 1
        assert "missing" in failures[0].lower()

    def test_passes_when_original_has_no_wksp(self, tmp_path):
        """Original repo has no wksp/ — nothing to validate."""
        slot_dir = tmp_path / "slots" / "1"
        slot_dir.mkdir(parents=True)
        init_repo(slot_dir / "engine")

        failures = slot_workspace.validate_slot_wksp(slot_dir)
        assert failures == []

    def test_scoped_to_specific_repos(self, tmp_path):
        """When repo_names is provided, only those repos are checked."""
        slot_dir = tmp_path / "slots" / "1"
        slot_dir.mkdir(parents=True)
        init_repo(slot_dir / "engine")
        bad = init_repo(slot_dir / "iot")
        (bad / "wksp").symlink_to("/nonexistent")

        failures = slot_workspace.validate_slot_wksp(slot_dir, repo_names=["engine"])
        assert failures == []

