"""Tests for work/work_router.py"""

import sys
from pathlib import Path

import pytest

skill_dir = Path(__file__).parent.parent / "work"
sys.path.insert(0, str(skill_dir))

import work_router


class TestDetectState:
    def test_on_main_no_stack(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        result = work_router.detect_state(
            current_branch="main",
            project_path=str(tmp_path / "project"),
            workspace_path=str(workspace),
        )
        assert result["ON_MAIN"] == "yes"
        assert result["ROUTE"] == "start"
        assert result["STACK_DEPTH"] == "0"

    def test_on_main_with_stack(self, tmp_path):
        workspace = tmp_path / "workspace"
        design = workspace / "design"
        design.mkdir(parents=True)
        (design / ".pause-stack").write_text(
            "- branch: issue-42-spi\n  issue: 42\n"
            "- branch: issue-55-ledger\n  issue: 55\n"
        )
        result = work_router.detect_state(
            current_branch="main",
            project_path=str(tmp_path / "project"),
            workspace_path=str(workspace),
        )
        assert result["ROUTE"] == "resume_stack"
        assert result["STACK_DEPTH"] == "2"

    def test_on_branch_no_slot(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        project = tmp_path / "project"
        project.mkdir()
        result = work_router.detect_state(
            current_branch="issue-42-spi",
            project_path=str(project),
            workspace_path=str(workspace),
        )
        assert result["ON_MAIN"] == "no"
        assert result["ROUTE"] == "resume_branch"
        assert result["IN_SLOT"] == "no"

    def test_on_branch_in_slot(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        family = tmp_path / "family"
        slot = family / "worktrees" / "1"
        project = slot / "engine"
        project.mkdir(parents=True)
        (slot / "SLOT.md").write_text(
            "# Slot 1 — issue-42-spi\n\n## Issue\n"
            "repo#42\nCovers: 42\n\n## What to do\nTest\n"
        )
        result = work_router.detect_state(
            current_branch="issue-42-spi",
            project_path=str(project),
            workspace_path=str(workspace),
        )
        assert result["IN_SLOT"] == "yes"
        assert result["IS_EPIC"] == "no"
        assert result["ROUTE"] == "resume_branch"
        assert result["SLOT_MD_PATH"] == str(slot / "SLOT.md")

    def test_on_branch_in_epic_slot(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        family = tmp_path / "family"
        slot = family / "worktrees" / "1"
        project = slot / "engine"
        project.mkdir(parents=True)
        (slot / "SLOT.md").write_text(
            "# Slot 1 — issue-50-profiles\n\n## Issue\n"
            "casehubio/engine#50\nCovers: 108\nType: epic\n\n"
            "## What to do\nEpic work\n\n"
            "## Batch Plan\n\n"
            "### Batch 1 — Vocab (S+S)\n"
            "- [x] #108 — Done\n"
            "- [ ] #109 — Active ← active\n\n"
            "### Batch 2 — API (M)\n"
            "- [ ] #111 — Weights\n\n"
            "## Session State\nCurrent batch: 1\n"
            "Current issue: #109 — Active\n\n"
            "## Repos\n- engine\n"
        )
        result = work_router.detect_state(
            current_branch="issue-50-profiles",
            project_path=str(project),
            workspace_path=str(workspace),
        )
        assert result["IN_SLOT"] == "yes"
        assert result["IS_EPIC"] == "yes"
        assert result["EPIC_BATCH"] == "1 of 2"
        assert result["EPIC_ACTIVE_ISSUE"] == "109"
        assert result["ROUTE"] == "resume_branch"

    def test_on_branch_with_handoff(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "HANDOFF.md").write_text("# Handoff\nLast session did X.")
        project = tmp_path / "project"
        project.mkdir()
        result = work_router.detect_state(
            current_branch="issue-42-spi",
            project_path=str(project),
            workspace_path=str(workspace),
        )
        assert result["HAS_HANDOFF"] == "yes"
        assert result["HANDOFF_PATH"] == str(workspace / "HANDOFF.md")

    def test_on_branch_with_stack(self, tmp_path):
        workspace = tmp_path / "workspace"
        design = workspace / "design"
        design.mkdir(parents=True)
        (design / ".pause-stack").write_text(
            "- branch: issue-55-ledger\n  issue: 55\n"
        )
        project = tmp_path / "project"
        project.mkdir()
        result = work_router.detect_state(
            current_branch="issue-42-spi",
            project_path=str(project),
            workspace_path=str(workspace),
        )
        assert result["ROUTE"] == "resume_branch"
        assert result["STACK_DEPTH"] == "1"

    def test_no_handoff_file(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        project = tmp_path / "project"
        project.mkdir()
        result = work_router.detect_state(
            current_branch="issue-42-spi",
            project_path=str(project),
            workspace_path=str(workspace),
        )
        assert result["HAS_HANDOFF"] == "no"
        assert "HANDOFF_PATH" not in result

    def test_slot_without_worktrees_in_path(self, tmp_path):
        """A SLOT.md one level up doesn't count if /worktrees/ isn't in the path."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        project = tmp_path / "family" / "engine"
        project.mkdir(parents=True)
        (tmp_path / "family" / "SLOT.md").write_text(
            "# Slot 1\n\n## Issue\nrepo#42\nType: epic\n"
        )
        result = work_router.detect_state(
            current_branch="issue-42-spi",
            project_path=str(project),
            workspace_path=str(workspace),
        )
        assert result["IN_SLOT"] == "no"


class TestCLI:
    def test_outputs_key_value(self, tmp_path, capsys):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        sys.argv = ["work_router.py", "main", str(tmp_path), str(workspace)]
        work_router.main()
        out = capsys.readouterr().out
        assert "ROUTE=start" in out
        assert "ON_MAIN=yes" in out

    def test_missing_args(self, capsys):
        sys.argv = ["work_router.py"]
        rc = work_router.main()
        assert rc == 1
