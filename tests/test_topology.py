"""Tests for project/topology.py — path resolution and layout detection."""

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "project" / "topology.py"
PROJECT_DIR = SCRIPT.parent


def init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t.com"], capture_output=True)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"],
        cwd=str(path), capture_output=True, check=True,
    )
    return path


@pytest.fixture(autouse=True)
def _setup_path():
    if str(PROJECT_DIR) not in sys.path:
        sys.path.insert(0, str(PROJECT_DIR))
    slot_dir = PROJECT_DIR.parent / "work-slot"
    if str(slot_dir) not in sys.path:
        sys.path.insert(0, str(slot_dir))


def _resolve(cwd: str):
    import importlib
    import topology
    importlib.reload(topology)
    return topology.resolve(cwd)


class TestTopologyResolve:

    def test_single_repo_no_symlinks(self, tmp_path):
        repo = init_repo(tmp_path / "repo")
        topo = _resolve(str(repo))
        assert topo.layout == "single"
        assert topo.project == repo.resolve()
        assert topo.workspace == topo.project
        assert topo.workspace_root == topo.project
        assert topo.slot_dir is None
        assert topo.primary_repo is None

    def test_dual_repo_wksp_to_git_root(self, tmp_path):
        project = init_repo(tmp_path / "project")
        workspace = init_repo(tmp_path / "workspace")
        (project / "wksp").symlink_to(workspace)
        topo = _resolve(str(project))
        assert topo.layout == "dual"
        assert topo.workspace == workspace.resolve()
        assert topo.workspace_root == workspace.resolve()

    def test_dual_repo_wksp_to_subdir(self, tmp_path):
        project = init_repo(tmp_path / "project")
        workspace = init_repo(tmp_path / "work")
        subdir = workspace / "engine"
        subdir.mkdir()
        (project / "wksp").symlink_to("../work/engine")
        topo = _resolve(str(project))
        assert topo.layout == "dual"
        assert topo.workspace == subdir.resolve()
        assert topo.workspace_root == workspace.resolve()

    def test_dual_repo_proj_symlink(self, tmp_path):
        project = init_repo(tmp_path / "project")
        workspace = init_repo(tmp_path / "workspace")
        (workspace / "proj").symlink_to(project)
        topo = _resolve(str(workspace))
        assert topo.layout == "dual"
        assert topo.project == project.resolve()
        assert topo.workspace == workspace.resolve()

    def test_slot_detected_via_dot_slot_file(self, tmp_path):
        slot_dir = tmp_path / "slots" / "110"
        slot_dir.mkdir(parents=True)
        (slot_dir / ".slot").write_text(
            "# Slot 110 — test\n\n## Repos\n- engine (primary)\n- platform\n"
        )
        project = init_repo(slot_dir / "engine")
        workspace = init_repo(slot_dir / "work")
        subdir = workspace / "engine"
        subdir.mkdir()
        (project / "wksp").symlink_to("../work/engine")
        topo = _resolve(str(project))
        assert topo.layout == "slot"
        assert topo.slot_dir == slot_dir
        assert topo.primary_repo == "engine"

    def test_no_slot_without_dot_slot_file(self, tmp_path):
        """Substring /slots/ in path is not enough — .slot file required."""
        slot_dir = tmp_path / "slots" / "110"
        slot_dir.mkdir(parents=True)
        project = init_repo(slot_dir / "engine")
        topo = _resolve(str(project))
        assert topo.layout == "single"
        assert topo.slot_dir is None

    def test_worktree_falls_back_to_main_when_no_local_wksp(self, tmp_path):
        project = init_repo(tmp_path / "project")
        workspace = init_repo(tmp_path / "workspace")
        (project / "wksp").symlink_to(workspace)
        wt = tmp_path / "wt" / "feat"
        wt.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "-C", str(project), "worktree", "add", str(wt), "-b", "feat"],
            capture_output=True, check=True,
        )
        topo = _resolve(str(wt))
        assert topo.in_worktree is True
        assert topo.workspace == workspace.resolve()

    def test_worktree_uses_own_wksp_when_present(self, tmp_path):
        project = init_repo(tmp_path / "project")
        main_workspace = init_repo(tmp_path / "main-workspace")
        slot_workspace = init_repo(tmp_path / "slot-workspace")
        (project / "wksp").symlink_to(main_workspace)
        wt = tmp_path / "wt" / "feat"
        wt.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "-C", str(project), "worktree", "add", str(wt), "-b", "feat"],
            capture_output=True, check=True,
        )
        (wt / "wksp").symlink_to(slot_workspace)
        topo = _resolve(str(wt))
        assert topo.in_worktree is True
        assert topo.workspace == slot_workspace.resolve()

    def test_worktree_falls_back_when_local_wksp_dangling(self, tmp_path):
        project = init_repo(tmp_path / "project")
        main_workspace = init_repo(tmp_path / "main-workspace")
        (project / "wksp").symlink_to(main_workspace)
        wt = tmp_path / "wt" / "feat"
        wt.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "-C", str(project), "worktree", "add", str(wt), "-b", "feat"],
            capture_output=True, check=True,
        )
        (wt / "wksp").symlink_to("/nonexistent/workspace")
        topo = _resolve(str(wt))
        assert topo.in_worktree is True
        assert topo.workspace == main_workspace.resolve()

    def test_broken_symlink_outside_git_returns_single(self, tmp_path):
        project = init_repo(tmp_path / "project")
        (project / "wksp").symlink_to("/nonexistent/path")
        topo = _resolve(str(project))
        assert topo.layout == "single"

    def test_dangling_symlink_walks_up_to_git_root(self, tmp_path):
        project = init_repo(tmp_path / "project")
        workspace = init_repo(tmp_path / "workspace")
        (project / "wksp").symlink_to("../workspace/nonexistent")
        topo = _resolve(str(project))
        assert topo.layout == "dual"
        assert topo.workspace == workspace.resolve()


class TestFindDesignFile:

    def test_finds_in_workspace_design_subdir(self, tmp_path):
        project = init_repo(tmp_path / "project")
        workspace = init_repo(tmp_path / "workspace")
        (project / "wksp").symlink_to(workspace)
        (workspace / "design").mkdir()
        (workspace / "design" / ".meta").write_text("branch: test\n")
        import importlib, topology
        importlib.reload(topology)
        topo = topology.resolve(str(project))
        result = topology.find_design_file(".meta", topo)
        assert result == workspace / "design" / ".meta"

    def test_finds_at_workspace_root(self, tmp_path):
        """Slot root .plan — no design/ subdir."""
        slot_dir = tmp_path / "slots" / "1"
        slot_dir.mkdir(parents=True)
        (slot_dir / ".slot").write_text("# Slot\n\n## Repos\n- engine (primary)\n")
        project = init_repo(slot_dir / "engine")
        workspace = init_repo(slot_dir / "work")
        (project / "wksp").symlink_to("../work")
        (slot_dir / ".plan").write_text("# Plan\n")
        import importlib, topology
        importlib.reload(topology)
        topo = topology.resolve(str(project))
        result = topology.find_design_file(".plan", topo)
        assert result == slot_dir / ".plan"

    def test_finds_at_workspace_git_root(self, tmp_path):
        """wksp → subdir, file at git root's design/."""
        project = init_repo(tmp_path / "project")
        workspace = init_repo(tmp_path / "work")
        subdir = workspace / "engine"
        subdir.mkdir()
        (workspace / "design").mkdir()
        (workspace / "design" / ".meta").write_text("branch: test\n")
        (project / "wksp").symlink_to("../work/engine")
        import importlib, topology
        importlib.reload(topology)
        topo = topology.resolve(str(project))
        result = topology.find_design_file(".meta", topo)
        assert result == workspace / "design" / ".meta"

    def test_finds_via_primary_repo_workspace(self, tmp_path):
        """Secondary repo in slot finds .plan at primary's workspace."""
        slot_dir = tmp_path / "slots" / "110"
        slot_dir.mkdir(parents=True)
        (slot_dir / ".slot").write_text(
            "# Slot\n\n## Repos\n- parent (primary)\n- engine\n"
        )
        primary = init_repo(slot_dir / "parent")
        secondary = init_repo(slot_dir / "engine")
        ws_primary = init_repo(slot_dir / "work-main")
        ws_secondary = init_repo(slot_dir / "work-eng")
        (primary / "wksp").symlink_to("../work-main")
        (secondary / "wksp").symlink_to("../work-eng")
        (ws_primary / "design").mkdir()
        (ws_primary / "design" / ".plan").write_text("# Plan\n")
        import importlib, topology
        importlib.reload(topology)
        topo = topology.resolve(str(secondary))
        result = topology.find_design_file(".plan", topo)
        assert result == ws_primary / "design" / ".plan"

    def test_returns_none_when_not_found(self, tmp_path):
        project = init_repo(tmp_path / "project")
        import importlib, topology
        importlib.reload(topology)
        topo = topology.resolve(str(project))
        result = topology.find_design_file(".plan", topo)
        assert result is None

    def test_design_subdir_takes_precedence(self, tmp_path):
        """design/.meta preferred over bare .meta at same level."""
        project = init_repo(tmp_path / "project")
        workspace = init_repo(tmp_path / "workspace")
        (project / "wksp").symlink_to(workspace)
        (workspace / "design").mkdir()
        (workspace / "design" / ".meta").write_text("in_design: yes\n")
        (workspace / ".meta").write_text("at_root: yes\n")
        import importlib, topology
        importlib.reload(topology)
        topo = topology.resolve(str(project))
        result = topology.find_design_file(".meta", topo)
        assert result == workspace / "design" / ".meta"
