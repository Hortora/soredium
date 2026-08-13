"""Tests for project/work_state.py — lifecycle detection using Topology."""

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).parent.parent / "project"


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


def _detect(cwd: str):
    import importlib
    import topology
    importlib.reload(topology)
    topo = topology.resolve(cwd)
    import work_state
    importlib.reload(work_state)
    return work_state.detect(topo)


class TestWorkStateDetect:

    def test_on_main_no_stack_routes_start(self, tmp_path):
        repo = init_repo(tmp_path / "repo")
        state = _detect(str(repo))
        assert state.route == "start"
        assert state.on_main is True
        assert state.stack_depth == 0

    def test_on_main_with_stack_routes_resume_stack(self, tmp_path):
        repo = init_repo(tmp_path / "repo")
        (repo / "design").mkdir()
        (repo / "design" / ".pause-stack").write_text("- branch: issue-42-foo\n")
        state = _detect(str(repo))
        assert state.route == "resume_stack"
        assert state.stack_depth == 1

    def test_on_feature_branch_routes_resume_branch(self, tmp_path):
        repo = init_repo(tmp_path / "repo")
        subprocess.run(
            ["git", "-C", str(repo), "checkout", "-b", "issue-42-feat"],
            capture_output=True,
        )
        (repo / "design").mkdir()
        (repo / "design" / ".meta").write_text("branch: issue-42-feat\nissue: 42\n")
        state = _detect(str(repo))
        assert state.route == "resume_branch"
        assert state.on_main is False

    def test_plan_found_has_plan_true(self, tmp_path):
        repo = init_repo(tmp_path / "repo")
        (repo / "design").mkdir()
        (repo / "design" / ".plan").write_text(
            "# Work Plan — test\n\n## Queue\n"
            "- [ ] #10 — A ← active\n\n"
            "## Session State\nCurrent: #10\nStarted: 2026-01-01\n"
        )
        state = _detect(str(repo))
        assert state.has_plan is True
        assert state.plan_active_issue == "10"

    def test_no_plan_has_plan_false(self, tmp_path):
        repo = init_repo(tmp_path / "repo")
        state = _detect(str(repo))
        assert state.has_plan is False

    def test_in_slot_detected(self, tmp_path):
        slot_dir = tmp_path / "slots" / "1"
        slot_dir.mkdir(parents=True)
        (slot_dir / ".slot").write_text("# Slot\n\n## Repos\n- engine (primary)\n")
        project = init_repo(slot_dir / "engine")
        state = _detect(str(project))
        assert state.in_slot is True

    def test_plan_at_slot_root_found(self, tmp_path):
        slot_dir = tmp_path / "slots" / "1"
        slot_dir.mkdir(parents=True)
        (slot_dir / ".slot").write_text("# Slot\n\n## Repos\n- engine (primary)\n")
        (slot_dir / ".plan").write_text(
            "# Work Plan — test\n\n## Queue\n"
            "- [ ] #10 — A ← active\n\n"
            "## Session State\nCurrent: #10\nStarted: 2026-01-01\n"
        )
        project = init_repo(slot_dir / "engine")
        state = _detect(str(project))
        assert state.has_plan is True
        assert state.plan_active_issue == "10"

    def test_handoff_project_specific_found(self, tmp_path):
        """F4: HANDOFF-{project}.md checked before HANDOFF.md."""
        project = init_repo(tmp_path / "project")
        workspace = init_repo(tmp_path / "workspace")
        (project / "wksp").symlink_to(workspace)
        (workspace / "HANDOFF-project.md").write_text("# HANDOFF\n\n#42\n")
        subprocess.run(
            ["git", "-C", str(workspace), "add", "."],
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(workspace), "commit", "-m", "handoff"],
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(project), "checkout", "-b", "issue-42-feat"],
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(workspace), "checkout", "-b", "issue-42-feat"],
            capture_output=True,
        )
        state = _detect(str(project))
        assert state.has_handoff is True
        assert "HANDOFF-project.md" in state.handoff_path

    def test_handoff_branch_scoped_present(self, tmp_path):
        """Branch-scoped: HANDOFF.md on branch is detected regardless of content."""
        project = init_repo(tmp_path / "project")
        workspace = init_repo(tmp_path / "workspace")
        (project / "wksp").symlink_to(workspace)
        subprocess.run(
            ["git", "-C", str(project), "checkout", "-b", "issue-42-feat"],
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(workspace), "checkout", "-b", "issue-42-feat"],
            capture_output=True,
        )
        (workspace / "HANDOFF.md").write_text("# Handover\n\nSome context.\n")
        state = _detect(str(project))
        assert state.has_handoff is True

    def test_handoff_absent_on_main_after_branch_switch(self, tmp_path):
        """Branch-scoped: HANDOFF.md on branch A is invisible from main."""
        project = init_repo(tmp_path / "project")
        workspace = init_repo(tmp_path / "workspace")
        (project / "wksp").symlink_to(workspace)
        subprocess.run(
            ["git", "-C", str(project), "checkout", "-b", "issue-42-feat"],
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(workspace), "checkout", "-b", "issue-42-feat"],
            capture_output=True,
        )
        (workspace / "HANDOFF.md").write_text("# Handover\n\n#42\n")
        subprocess.run(
            ["git", "-C", str(workspace), "add", "HANDOFF.md"],
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(workspace), "commit", "-m", "handoff"],
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(project), "checkout", "main"],
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(workspace), "checkout", "main"],
            capture_output=True,
        )
        state = _detect(str(project))
        assert state.has_handoff is False

    def test_handoff_isolation_across_branches(self, tmp_path):
        """Pause/resume: branch A and B each carry their own HANDOFF.md."""
        project = init_repo(tmp_path / "project")
        workspace = init_repo(tmp_path / "workspace")
        (project / "wksp").symlink_to(workspace)

        subprocess.run(["git", "-C", str(project), "checkout", "-b", "issue-42-feat"], capture_output=True)
        subprocess.run(["git", "-C", str(workspace), "checkout", "-b", "issue-42-feat"], capture_output=True)
        (workspace / "HANDOFF.md").write_text("# Branch A handoff\n")
        subprocess.run(["git", "-C", str(workspace), "add", "HANDOFF.md"], capture_output=True)
        subprocess.run(["git", "-C", str(workspace), "commit", "-m", "handoff A"], capture_output=True)

        subprocess.run(["git", "-C", str(project), "checkout", "main"], capture_output=True)
        subprocess.run(["git", "-C", str(workspace), "checkout", "main"], capture_output=True)
        subprocess.run(["git", "-C", str(project), "checkout", "-b", "issue-55-other"], capture_output=True)
        subprocess.run(["git", "-C", str(workspace), "checkout", "-b", "issue-55-other"], capture_output=True)
        (workspace / "HANDOFF.md").write_text("# Branch B handoff\n")
        subprocess.run(["git", "-C", str(workspace), "add", "HANDOFF.md"], capture_output=True)
        subprocess.run(["git", "-C", str(workspace), "commit", "-m", "handoff B"], capture_output=True)

        subprocess.run(["git", "-C", str(project), "checkout", "issue-42-feat"], capture_output=True)
        subprocess.run(["git", "-C", str(workspace), "checkout", "issue-42-feat"], capture_output=True)

        state = _detect(str(project))
        assert state.has_handoff is True
        content = Path(state.handoff_path).read_text()
        assert "Branch A" in content
        assert "Branch B" not in content
