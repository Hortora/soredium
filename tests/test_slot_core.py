"""Tests for work-slot/slot_core.py"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

skill_dir = Path(__file__).parent.parent / "work-slot"
sys.path.insert(0, str(skill_dir))

import slot_core
from slot_test_helpers import init_repo, init_repo_with_workspace


class TestSlotDirResolution:
    def test_prefers_slots_over_worktrees(self, tmp_path):
        (tmp_path / "slots").mkdir()
        (tmp_path / "worktrees").mkdir()
        result = slot_core._resolve_slots_dir(tmp_path)
        assert result == tmp_path / "slots"

    def test_falls_back_to_worktrees(self, tmp_path):
        (tmp_path / "worktrees").mkdir()
        result = slot_core._resolve_slots_dir(tmp_path)
        assert result == tmp_path / "worktrees"

    def test_returns_slots_when_neither_exists(self, tmp_path):
        result = slot_core._resolve_slots_dir(tmp_path)
        assert result == tmp_path / "slots"

    def test_resolve_slot_number_in_slots(self, tmp_path):
        (tmp_path / "slots" / "1").mkdir(parents=True)
        result = slot_core._resolve_slot_dir_for_number(tmp_path, 1)
        assert result == tmp_path / "slots" / "1"

    def test_resolve_slot_number_falls_back_to_worktrees(self, tmp_path):
        (tmp_path / "worktrees" / "1").mkdir(parents=True)
        result = slot_core._resolve_slot_dir_for_number(tmp_path, 1)
        assert result == tmp_path / "worktrees" / "1"

    def test_resolve_slot_number_prefers_slots(self, tmp_path):
        (tmp_path / "slots" / "1").mkdir(parents=True)
        (tmp_path / "worktrees" / "1").mkdir(parents=True)
        result = slot_core._resolve_slot_dir_for_number(tmp_path, 1)
        assert result == tmp_path / "slots" / "1"


class TestIsSlotPath:
    def test_detects_slots_path(self):
        assert slot_core.is_slot_path("/home/user/family/slots/1/repo") is True

    def test_detects_legacy_worktrees_path(self):
        assert slot_core.is_slot_path("/home/user/family/worktrees/1/repo") is True

    def test_rejects_claude_worktrees(self):
        assert slot_core.is_slot_path("/home/user/repo/.claude/worktrees/issue-17") is False

    def test_rejects_dot_worktrees(self):
        assert slot_core.is_slot_path("/home/user/repo/.worktrees/feat") is False

    def test_rejects_plain_path(self):
        assert slot_core.is_slot_path("/home/user/project/src") is False


class TestIsProjectRepo:
    def test_excludes_workspace_dirs(self):
        assert slot_core.is_project_repo("work") is False
        assert slot_core.is_project_repo("work-casehub") is False
        assert slot_core.is_project_repo("work-casehub-ras") is False

    def test_includes_real_repos(self):
        assert slot_core.is_project_repo("engine") is True
        assert slot_core.is_project_repo("blocks") is True

    def test_includes_worker_named_repos(self):
        """Repos named 'worker', 'workflow' etc must not be excluded."""
        assert slot_core.is_project_repo("worker") is True
        assert slot_core.is_project_repo("workflow") is True
        assert slot_core.is_project_repo("workbench") is True

    def test_excludes_infrastructure_dirs(self):
        assert slot_core.is_project_repo(".m2") is False
        assert slot_core.is_project_repo("attic") is False


class TestIsWorkspaceClone:
    def test_detects_workspace_marker(self, tmp_path):
        ws = tmp_path / "work-casehub"
        ws.mkdir()
        (ws / ".workspace").write_text("project: /path/to/project\n")
        assert slot_core.is_workspace_clone(ws) is True

    def test_detects_proj_symlink(self, tmp_path):
        ws = tmp_path / "custom-ws-name"
        ws.mkdir()
        (ws / "proj").symlink_to("/path/to/project")
        assert slot_core.is_workspace_clone(ws) is True

    def test_detects_work_prefix_name(self, tmp_path):
        ws = tmp_path / "work-casehub"
        ws.mkdir()
        assert slot_core.is_workspace_clone(ws) is True

    def test_detects_work_name(self, tmp_path):
        ws = tmp_path / "work"
        ws.mkdir()
        assert slot_core.is_workspace_clone(ws) is True

    def test_project_repo_not_workspace(self, tmp_path):
        repo = tmp_path / "engine"
        repo.mkdir()
        assert slot_core.is_workspace_clone(repo) is False

    def test_worker_named_repo_not_workspace(self, tmp_path):
        repo = tmp_path / "worker"
        repo.mkdir()
        assert slot_core.is_workspace_clone(repo) is False

    def test_nonexistent_path(self, tmp_path):
        assert slot_core.is_workspace_clone(tmp_path / "nope") is False

    def test_workspace_marker_overrides_project_name(self, tmp_path):
        """A repo named like a project but with .workspace is still a workspace."""
        ws = tmp_path / "engine"
        ws.mkdir()
        (ws / ".workspace").write_text("project: /path/to/engine\n")
        assert slot_core.is_workspace_clone(ws) is True

    def test_proj_symlink_overrides_project_name(self, tmp_path):
        """A repo with a proj symlink is a workspace even with a project-like name."""
        ws = tmp_path / "platform"
        ws.mkdir()
        (ws / "proj").symlink_to("/path/to/platform")
        assert slot_core.is_workspace_clone(ws) is True

    def test_wsp_prefix_without_marker_is_project(self, tmp_path):
        """wsp-casehub-connectors without .workspace marker is a project repo
        (name alone is not a detection signal)."""
        repo = tmp_path / "wsp-casehub-connectors"
        repo.mkdir()
        assert slot_core.is_workspace_clone(repo) is False

    def test_wsp_prefix_with_marker_is_workspace(self, tmp_path):
        """wsp-casehub-connectors with .workspace marker is detected."""
        ws = tmp_path / "wsp-casehub-connectors"
        ws.mkdir()
        (ws / ".workspace").touch()
        assert slot_core.is_workspace_clone(ws) is True


class TestGetSlotReposFiltersWorkspaces:
    def test_excludes_workspace_by_name(self, tmp_path):
        slot = tmp_path / "slot"
        slot.mkdir()
        init_repo(slot / "engine")
        init_repo(slot / "work-casehub")
        repos = slot_core.get_slot_repos(slot)
        assert "engine" in repos
        assert "work-casehub" not in repos

    def test_excludes_workspace_by_marker(self, tmp_path):
        slot = tmp_path / "slot"
        slot.mkdir()
        init_repo(slot / "engine")
        ws = init_repo(slot / "custom-ws")
        (ws / ".workspace").write_text("project: /path\n")
        repos = slot_core.get_slot_repos(slot)
        assert "engine" in repos
        assert "custom-ws" not in repos

    def test_excludes_workspace_by_proj_symlink(self, tmp_path):
        slot = tmp_path / "slot"
        slot.mkdir()
        init_repo(slot / "engine")
        ws = init_repo(slot / "my-workspace")
        (ws / "proj").symlink_to(str(slot / "engine"))
        repos = slot_core.get_slot_repos(slot)
        assert "engine" in repos
        assert "my-workspace" not in repos

    def test_excludes_wsp_prefix_workspace_by_marker(self, tmp_path):
        """New naming: wsp-casehub-connectors with .workspace marker is excluded."""
        slot = tmp_path / "slot"
        slot.mkdir()
        init_repo(slot / "connectors")
        ws = init_repo(slot / "wsp-casehub-connectors")
        (ws / ".workspace").touch()
        repos = slot_core.get_slot_repos(slot)
        assert "connectors" in repos
        assert "wsp-casehub-connectors" not in repos

    def test_wsp_prefix_without_marker_included_as_project(self, tmp_path):
        """Without .workspace marker, wsp-prefixed dir passes as project repo."""
        slot = tmp_path / "slot"
        slot.mkdir()
        init_repo(slot / "connectors")
        init_repo(slot / "wsp-casehub-connectors")  # no marker
        repos = slot_core.get_slot_repos(slot)
        assert "connectors" in repos
        assert "wsp-casehub-connectors" in repos

    def test_get_all_still_returns_workspaces(self, tmp_path):
        slot = tmp_path / "slot"
        slot.mkdir()
        init_repo(slot / "engine")
        init_repo(slot / "work-casehub")
        all_repos = slot_core.get_all_slot_repos(slot)
        assert "engine" in all_repos
        assert "work-casehub" in all_repos


class TestGetAllSlotRepos:
    def test_includes_workspace_dirs(self, tmp_path):
        slot = tmp_path / "slot1"
        slot.mkdir()
        for name in ["engine", "pages", "work-casehub"]:
            d = slot / name
            d.mkdir()
            (d / ".git").mkdir()
        (slot / ".m2").mkdir()
        result = slot_core.get_all_slot_repos(slot)
        assert result == ["engine", "pages", "work-casehub"]

    def test_excludes_m2_and_attic(self, tmp_path):
        slot = tmp_path / "slot1"
        slot.mkdir()
        for name in ["engine", ".m2", "attic"]:
            d = slot / name
            d.mkdir()
            (d / ".git").mkdir()
        result = slot_core.get_all_slot_repos(slot)
        assert result == ["engine"]

    def test_excludes_non_git_dirs(self, tmp_path):
        slot = tmp_path / "slot1"
        slot.mkdir()
        (slot / "engine").mkdir()
        (slot / "engine" / ".git").mkdir()
        (slot / "random-dir").mkdir()
        result = slot_core.get_all_slot_repos(slot)
        assert result == ["engine"]

    def test_get_slot_repos_still_excludes_workspace(self, tmp_path):
        slot = tmp_path / "slot1"
        slot.mkdir()
        for name in ["engine", "work-casehub"]:
            d = slot / name
            d.mkdir()
            (d / ".git").mkdir()
        result = slot_core.get_slot_repos(slot)
        assert result == ["engine"]


class TestIsWorktree:
    def test_worktree_detected(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").write_text("gitdir: /some/path/.git/worktrees/repo")
        assert slot_core.is_worktree(repo) is True

    def test_clone_not_detected(self, tmp_path):
        repo = init_repo(tmp_path / "repo")
        assert slot_core.is_worktree(repo) is False

    def test_no_git_not_detected(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        assert slot_core.is_worktree(repo) is False


class TestCleanupRemnantDir:
    def test_removes_idea_directory(self, tmp_path):
        target = tmp_path / "repo"
        target.mkdir()
        (target / ".idea").mkdir()
        (target / ".idea" / "workspace.xml").write_text("<xml/>")
        assert slot_core._cleanup_remnant_dir(target) is True
        assert not target.exists()

    def test_removes_multiple_ide_artifacts(self, tmp_path):
        target = tmp_path / "repo"
        target.mkdir()
        for name in [".idea", ".run", ".vscode"]:
            d = target / name
            d.mkdir()
            (d / "config").write_text("x")
        assert slot_core._cleanup_remnant_dir(target) is True
        assert not target.exists()

    def test_preserves_non_ide_content(self, tmp_path):
        target = tmp_path / "repo"
        target.mkdir()
        (target / ".idea").mkdir()
        (target / "src.java").write_text("class Foo {}")
        assert slot_core._cleanup_remnant_dir(target) is False
        assert target.exists()
        assert not (target / ".idea").exists()
        assert (target / "src.java").exists()

    def test_nonexistent_path_returns_true(self, tmp_path):
        assert slot_core._cleanup_remnant_dir(tmp_path / "nonexistent") is True

    def test_already_empty_dir(self, tmp_path):
        target = tmp_path / "empty"
        target.mkdir()
        assert slot_core._cleanup_remnant_dir(target) is True
        assert not target.exists()

    def test_nested_ide_artifacts(self, tmp_path):
        """Slot dir with subdirs that each only have IDE artifacts."""
        slot = tmp_path / "slot"
        slot.mkdir()
        engine = slot / "engine"
        engine.mkdir()
        (engine / ".idea").mkdir()
        (engine / ".idea" / "workspace.xml").write_text("<xml/>")
        assert slot_core._cleanup_remnant_dir(slot) is True
        assert not slot.exists()


class TestEscapeSlotCwd:
    def test_escapes_when_cwd_inside_slot(self, tmp_path):
        slot = tmp_path / "slots" / "1"
        slot.mkdir(parents=True)
        escape_to = tmp_path
        original_cwd = os.getcwd()
        try:
            os.chdir(slot)
            escaped, _ = slot_core._escape_slot_cwd(slot, escape_to)
            assert escaped is True
            assert Path.cwd().resolve() == escape_to.resolve()
        finally:
            os.chdir(original_cwd)

    def test_escapes_when_cwd_in_subdirectory(self, tmp_path):
        slot = tmp_path / "slots" / "1"
        engine = slot / "engine"
        engine.mkdir(parents=True)
        escape_to = tmp_path
        original_cwd = os.getcwd()
        try:
            os.chdir(engine)
            escaped, relative = slot_core._escape_slot_cwd(slot, escape_to)
            assert escaped is True
            assert relative == Path("engine")
            assert Path.cwd().resolve() == escape_to.resolve()
        finally:
            os.chdir(original_cwd)

    def test_noop_when_cwd_outside_slot(self, tmp_path):
        slot = tmp_path / "slots" / "1"
        slot.mkdir(parents=True)
        escape_to = tmp_path
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            escaped, _ = slot_core._escape_slot_cwd(slot, escape_to)
            assert escaped is False
        finally:
            os.chdir(original_cwd)


class TestHasUnmergedContent:
    """_has_unmerged_content detects repos with branch content not on main."""

    def test_detects_unmerged_branch_content(self, tmp_path):
        slots = tmp_path / "slots"
        slot = slots / "10"
        repo = init_repo(slot / "engine")
        subprocess.run(["git", "-C", str(repo), "checkout", "-b", "feat-1"],
                        capture_output=True, check=True)
        (repo / "feature.py").write_text("# feature\n")
        subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "feat"],
                        capture_output=True, check=True)

        result = slot_core._has_unmerged_content(slot)

        assert result == ["engine"]

    def test_returns_empty_when_on_main(self, tmp_path):
        slots = tmp_path / "slots"
        slot = slots / "10"
        init_repo(slot / "engine")

        result = slot_core._has_unmerged_content(slot)

        assert result == []

    def test_returns_empty_when_branch_content_merged(self, tmp_path):
        slots = tmp_path / "slots"
        slot = slots / "10"
        repo = init_repo(slot / "engine")
        subprocess.run(["git", "-C", str(repo), "checkout", "-b", "feat-1"],
                        capture_output=True, check=True)
        (repo / "feature.py").write_text("# feature\n")
        subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "feat"],
                        capture_output=True, check=True)
        subprocess.run(["git", "-C", str(repo), "checkout", "main"],
                        capture_output=True, check=True)
        subprocess.run(["git", "-C", str(repo), "merge", "--ff-only", "feat-1"],
                        capture_output=True, check=True)
        subprocess.run(["git", "-C", str(repo), "checkout", "feat-1"],
                        capture_output=True, check=True)

        result = slot_core._has_unmerged_content(slot)

        assert result == []

    def test_reports_multiple_repos_with_unmerged(self, tmp_path):
        slots = tmp_path / "slots"
        slot = slots / "10"
        for name in ["engine", "worker"]:
            repo = init_repo(slot / name)
            subprocess.run(["git", "-C", str(repo), "checkout", "-b", "feat-1"],
                            capture_output=True, check=True)
            (repo / "feature.py").write_text(f"# {name}\n")
            subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-m", "feat"],
                            capture_output=True, check=True)

        result = slot_core._has_unmerged_content(slot)

        assert sorted(result) == ["engine", "worker"]

    def test_skips_non_git_directories(self, tmp_path):
        slots = tmp_path / "slots"
        slot = slots / "10"
        init_repo(slot / "engine")
        (slot / "not-a-repo").mkdir(parents=True)

        result = slot_core._has_unmerged_content(slot)

        assert result == []


class TestGetFamilyRepoNames:
    def test_finds_git_repos(self, tmp_path):
        family = tmp_path / "casehub"
        family.mkdir()
        init_repo(family / "engine")
        init_repo(family / "work")
        (family / "not-a-repo").mkdir()
        result = slot_core._get_family_repo_names(family)
        assert result == {"engine", "work"}

    def test_excludes_slots_and_m2(self, tmp_path):
        family = tmp_path / "casehub"
        family.mkdir()
        init_repo(family / "engine")
        (family / "slots").mkdir()
        (family / ".m2").mkdir()
        result = slot_core._get_family_repo_names(family)
        assert "slots" not in result
        assert ".m2" not in result
        assert "engine" in result

    def test_empty_family(self, tmp_path):
        family = tmp_path / "casehub"
        family.mkdir()
        result = slot_core._get_family_repo_names(family)
        assert result == set()
