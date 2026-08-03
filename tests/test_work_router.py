"""Tests for work/work_router.py"""

import subprocess
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
        slot = family / "slots" / "1"
        project = slot / "engine"
        project.mkdir(parents=True)
        (slot / ".slot").write_text(
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
        assert result["SLOT_PATH"] == str(slot / ".slot")

    def test_on_branch_in_epic_slot(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        family = tmp_path / "family"
        slot = family / "slots" / "1"
        project = slot / "engine"
        project.mkdir(parents=True)
        (slot / ".slot").write_text(
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

    def test_on_branch_handoff_references_different_issue(self, tmp_path):
        """HANDOFF.md exists but references a different issue — not a resume."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        self._init_git(workspace)
        (workspace / "HANDOFF.md").write_text("# Handoff\nFixed #99. All done.")
        self._commit_handoff_to_main(workspace)
        project = tmp_path / "project"
        project.mkdir()
        result = work_router.detect_state(
            current_branch="issue-42-spi",
            project_path=str(project),
            workspace_path=str(workspace),
        )
        assert result["HAS_HANDOFF"] == "no"
        assert result["HANDOFF_PATH"] == str(workspace / "HANDOFF.md")

    def test_on_branch_handoff_references_current_issue(self, tmp_path):
        """HANDOFF.md references the current branch's issue — genuine resume."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        self._init_git(workspace)
        (workspace / "HANDOFF.md").write_text(
            "# Handoff\nWorked on #42 SPI extraction. Midway through."
        )
        self._commit_handoff_to_main(workspace)
        project = tmp_path / "project"
        project.mkdir()
        result = work_router.detect_state(
            current_branch="issue-42-spi",
            project_path=str(project),
            workspace_path=str(workspace),
        )
        assert result["HAS_HANDOFF"] == "yes"
        assert result["HANDOFF_PATH"] == str(workspace / "HANDOFF.md")

    def test_on_main_handoff_always_yes(self, tmp_path):
        """On main, HAS_HANDOFF is yes whenever the file exists."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "HANDOFF.md").write_text("# Handoff\nLast session did X.")
        result = work_router.detect_state(
            current_branch="main",
            project_path=str(tmp_path / "project"),
            workspace_path=str(workspace),
        )
        assert result["HAS_HANDOFF"] == "yes"

    @staticmethod
    def _init_git(path):
        subprocess.run(["git", "init", "-b", "main", str(path)], capture_output=True)
        subprocess.run(
            ["git", "-C", str(path), "commit", "--allow-empty", "-m", "init"],
            capture_output=True,
        )

    @staticmethod
    def _commit_handoff_to_main(workspace):
        subprocess.run(
            ["git", "-C", str(workspace), "add", "HANDOFF.md"],
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(workspace), "commit", "-m", "handoff"],
            capture_output=True,
        )

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

    def test_non_standard_branch_assumes_resume(self, tmp_path):
        """Branches without issue-NNN pattern assume resume when handoff exists."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "HANDOFF.md").write_text("# Handoff\nSome work.")
        project = tmp_path / "project"
        project.mkdir()
        result = work_router.detect_state(
            current_branch="hotfix-typo",
            project_path=str(project),
            workspace_path=str(workspace),
        )
        assert result["HAS_HANDOFF"] == "yes"

    def test_slot_without_worktrees_in_path(self, tmp_path):
        """A .slot one level up doesn't count if /worktrees/ isn't in the path."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        project = tmp_path / "family" / "engine"
        project.mkdir(parents=True)
        (tmp_path / "family" / ".slot").write_text(
            "# Slot 1\n\n## Issue\nrepo#42\nType: epic\n"
        )
        result = work_router.detect_state(
            current_branch="issue-42-spi",
            project_path=str(project),
            workspace_path=str(workspace),
        )
        assert result["IN_SLOT"] == "no"


class TestSlotStates:
    """Test every possible slot state for correct HAS_HANDOFF detection."""

    @staticmethod
    def _init_git(path):
        subprocess.run(["git", "init", "-b", "main", str(path)], capture_output=True)
        subprocess.run(
            ["git", "-C", str(path), "commit", "--allow-empty", "-m", "init"],
            capture_output=True,
        )

    @staticmethod
    def _commit_handoff_to_main(workspace):
        subprocess.run(
            ["git", "-C", str(workspace), "add", "HANDOFF.md"],
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(workspace), "commit", "-m", "handoff"],
            capture_output=True,
        )

    def _make_slot(self, tmp_path, issue_num=42, epic=False):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        family = tmp_path / "family"
        slot = family / "slots" / "1"
        project = slot / "engine"
        project.mkdir(parents=True)
        if epic:
            (slot / ".slot").write_text(
                f"# Slot 1 — issue-{issue_num}\n\n## Issue\n"
                f"repo#{issue_num}\nCovers: {issue_num}\nType: epic\n\n"
                "## Batch Plan\n### Batch 1 — Core\n"
                f"- [ ] #{issue_num + 1} — Task ← active\n\n"
                "## Session State\nCurrent batch: 1\n"
                f"Current issue: #{issue_num + 1} — Task\n"
            )
        else:
            (slot / ".slot").write_text(
                f"# Slot 1 — issue-{issue_num}\n\n## Issue\n"
                f"repo#{issue_num}\nCovers: {issue_num}\n\n"
                "## What to do\nImplement feature\n"
            )
        return workspace, project

    def test_slot_first_session_no_handoff(self, tmp_path):
        """Brand new slot, no HANDOFF.md at all → start."""
        workspace, project = self._make_slot(tmp_path, issue_num=42)
        result = work_router.detect_state(
            "issue-42-feature", str(project), str(workspace))
        assert result["IN_SLOT"] == "yes"
        assert result["HAS_HANDOFF"] == "no"
        assert "HANDOFF_PATH" not in result

    def test_slot_first_session_handoff_from_other_work(self, tmp_path):
        """New slot, but HANDOFF.md exists from different issue → start."""
        workspace, project = self._make_slot(tmp_path, issue_num=42)
        self._init_git(workspace)
        (workspace / "HANDOFF.md").write_text(
            "# Handoff\nWorked on #99 — refactored the parser."
        )
        self._commit_handoff_to_main(workspace)
        result = work_router.detect_state(
            "issue-42-feature", str(project), str(workspace))
        assert result["IN_SLOT"] == "yes"
        assert result["HAS_HANDOFF"] == "no"
        assert result["HANDOFF_PATH"] == str(workspace / "HANDOFF.md")

    def test_slot_returning_handoff_references_issue(self, tmp_path):
        """Returning to slot, HANDOFF.md references this issue → resume."""
        workspace, project = self._make_slot(tmp_path, issue_num=42)
        self._init_git(workspace)
        (workspace / "HANDOFF.md").write_text(
            "# Handoff\nWorked on #42 feature. Midway through step 3."
        )
        self._commit_handoff_to_main(workspace)
        result = work_router.detect_state(
            "issue-42-feature", str(project), str(workspace))
        assert result["IN_SLOT"] == "yes"
        assert result["HAS_HANDOFF"] == "yes"
        assert result["HANDOFF_PATH"] == str(workspace / "HANDOFF.md")

    def test_slot_returning_no_handoff_written(self, tmp_path):
        """Returning to slot, prior session ended without handover → start."""
        workspace, project = self._make_slot(tmp_path, issue_num=42)
        result = work_router.detect_state(
            "issue-42-feature", str(project), str(workspace))
        assert result["IN_SLOT"] == "yes"
        assert result["HAS_HANDOFF"] == "no"

    def test_epic_slot_first_session(self, tmp_path):
        """Epic slot, first session → start + epic context."""
        workspace, project = self._make_slot(tmp_path, issue_num=50, epic=True)
        result = work_router.detect_state(
            "issue-50-profiles", str(project), str(workspace))
        assert result["IN_SLOT"] == "yes"
        assert result["IS_EPIC"] == "yes"
        assert result["HAS_HANDOFF"] == "no"
        assert result["EPIC_ACTIVE_ISSUE"] == "51"

    def test_epic_slot_returning_with_handoff(self, tmp_path):
        """Epic slot, returning with handoff → resume + epic context."""
        workspace, project = self._make_slot(tmp_path, issue_num=50, epic=True)
        self._init_git(workspace)
        (workspace / "HANDOFF.md").write_text(
            "# Handoff\nEpic #50 — completed batch 1, #51 done."
        )
        self._commit_handoff_to_main(workspace)
        result = work_router.detect_state(
            "issue-50-profiles", str(project), str(workspace))
        assert result["IN_SLOT"] == "yes"
        assert result["IS_EPIC"] == "yes"
        assert result["HAS_HANDOFF"] == "yes"
        assert result["EPIC_ACTIVE_ISSUE"] == "51"

    def test_epic_slot_first_session_stale_handoff(self, tmp_path):
        """Epic slot first session, HANDOFF.md from unrelated work → start."""
        workspace, project = self._make_slot(tmp_path, issue_num=50, epic=True)
        self._init_git(workspace)
        (workspace / "HANDOFF.md").write_text(
            "# Handoff\nFinished #77 — dependency gate shipped."
        )
        self._commit_handoff_to_main(workspace)
        result = work_router.detect_state(
            "issue-50-profiles", str(project), str(workspace))
        assert result["IN_SLOT"] == "yes"
        assert result["IS_EPIC"] == "yes"
        assert result["HAS_HANDOFF"] == "no"


class TestEpicFileDetection:
    def test_detects_epic_file_in_workspace(self, tmp_path):
        project = tmp_path / "project"
        workspace = tmp_path / "workspace"
        project.mkdir()
        workspace.mkdir()
        design = workspace / "design"
        design.mkdir(parents=True)
        (design / ".epic").write_text(
            "## Issue\nHortora/soredium#100\nType: epic\n\n"
            "## Batch Plan\n### Batch 1 — Core\n"
            "- [ ] #102 — First ← active\n\n"
            "## Session State\nCurrent batch: 1\n"
            "Current issue: #102 — First\n"
        )
        result = work_router.detect_state(
            "issue-100-epic", str(project), str(workspace))
        assert result["IS_EPIC"] == "yes"
        assert result["EPIC_PATH"] == str(design / ".epic")
        assert result["EPIC_BATCH"] == "1 of 1"
        assert result["EPIC_ACTIVE_ISSUE"] == "102"
        assert result["IN_SLOT"] == "no"

    def test_epic_file_not_present(self, tmp_path):
        project = tmp_path / "project"
        workspace = tmp_path / "workspace"
        project.mkdir()
        workspace.mkdir()
        result = work_router.detect_state(
            "main", str(project), str(workspace))
        assert result["IS_EPIC"] == "no"
        assert "EPIC_PATH" not in result

    def test_slot_takes_precedence_over_epic(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        family = tmp_path / "family"
        slot = family / "slots" / "1"
        project = slot / "repo"
        slot.mkdir(parents=True)
        project.mkdir()
        (slot / ".slot").write_text(
            "## Issue\nrepo#42\nType: epic\n\n"
            "## Batch Plan\n### Batch 1 — X\n"
            "- [ ] #10 — Y ← active\n\n"
            "## Session State\nCurrent batch: 1\n"
            "Current issue: #10 — Y\n"
        )
        design = workspace / "design"
        design.mkdir(parents=True)
        (design / ".epic").write_text(
            "## Issue\nother#99\nType: epic\n\n"
            "## Batch Plan\n### Batch 1 — Z\n"
            "- [ ] #20 — W ← active\n\n"
            "## Session State\nCurrent batch: 1\n"
            "Current issue: #20 — W\n"
        )
        result = work_router.detect_state(
            "issue-42-spi", str(project), str(workspace))
        assert result["IN_SLOT"] == "yes"
        assert result["SLOT_PATH"] == str(slot / ".slot")
        assert "EPIC_PATH" not in result

    def test_epic_multi_batch(self, tmp_path):
        project = tmp_path / "project"
        workspace = tmp_path / "workspace"
        project.mkdir()
        workspace.mkdir()
        design = workspace / "design"
        design.mkdir(parents=True)
        (design / ".epic").write_text(
            "## Issue\nrepo#100\nType: epic\n\n"
            "## Batch Plan\n"
            "### Batch 1 — A\n- [x] #10 — Done\n\n"
            "### Batch 2 — B ← current\n"
            "- [ ] #11 — Active ← active\n\n"
            "### Batch 3 — C\n- [ ] #12 — Later\n\n"
            "## Session State\nCurrent batch: 2\n"
            "Current issue: #11 — Active\n"
        )
        result = work_router.detect_state(
            "issue-100-epic", str(project), str(workspace))
        assert result["EPIC_BATCH"] == "2 of 3"
        assert result["EPIC_ACTIVE_ISSUE"] == "11"


class TestPerProjectHandoff:
    """Test per-project HANDOFF scoping in shared workspaces."""

    @staticmethod
    def _init_git(path):
        subprocess.run(["git", "init", "-b", "main", str(path)], capture_output=True)
        subprocess.run(
            ["git", "-C", str(path), "commit", "--allow-empty", "-m", "init"],
            capture_output=True,
        )

    @staticmethod
    def _commit_file(workspace, filename):
        subprocess.run(
            ["git", "-C", str(workspace), "add", filename],
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(workspace), "commit", "-m", f"add {filename}"],
            capture_output=True,
        )

    def test_shared_workspace_finds_project_handoff(self, tmp_path):
        """HANDOFF-engine.md exists → HAS_HANDOFF=yes for engine project."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "HANDOFF-engine.md").write_text("# Handoff\nEngine work on #42.")
        project = tmp_path / "engine"
        project.mkdir()
        result = work_router.detect_state(
            current_branch="main",
            project_path=str(project),
            workspace_path=str(workspace),
        )
        assert result["HAS_HANDOFF"] == "yes"
        assert result["HANDOFF_PATH"] == str(workspace / "HANDOFF-engine.md")

    def test_shared_workspace_ignores_other_project_handoff(self, tmp_path):
        """Only HANDOFF-eidos.md exists → HAS_HANDOFF=no for engine project."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "HANDOFF-eidos.md").write_text("# Handoff\nEidos work on #99.")
        project = tmp_path / "engine"
        project.mkdir()
        result = work_router.detect_state(
            current_branch="main",
            project_path=str(project),
            workspace_path=str(workspace),
        )
        assert result["HAS_HANDOFF"] == "no"

    def test_project_handoff_preferred_over_generic(self, tmp_path):
        """Both HANDOFF-engine.md and HANDOFF.md exist → project-specific wins."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "HANDOFF.md").write_text("# Handoff\nGeneric old handoff.")
        (workspace / "HANDOFF-engine.md").write_text("# Handoff\nEngine-specific.")
        project = tmp_path / "engine"
        project.mkdir()
        result = work_router.detect_state(
            current_branch="main",
            project_path=str(project),
            workspace_path=str(workspace),
        )
        assert result["HAS_HANDOFF"] == "yes"
        assert result["HANDOFF_PATH"] == str(workspace / "HANDOFF-engine.md")

    def test_falls_back_to_generic_handoff(self, tmp_path):
        """Only HANDOFF.md exists (no per-project file) → backward compat."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "HANDOFF.md").write_text("# Handoff\nGeneric handoff for #42.")
        project = tmp_path / "engine"
        project.mkdir()
        result = work_router.detect_state(
            current_branch="main",
            project_path=str(project),
            workspace_path=str(workspace),
        )
        assert result["HAS_HANDOFF"] == "yes"
        assert result["HANDOFF_PATH"] == str(workspace / "HANDOFF.md")

    def test_on_branch_project_handoff_branch_aware(self, tmp_path):
        """On feature branch, HANDOFF-engine.md checked for issue reference."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        self._init_git(workspace)
        (workspace / "HANDOFF-engine.md").write_text("# Handoff\nWorked on #42.")
        self._commit_file(workspace, "HANDOFF-engine.md")
        project = tmp_path / "engine"
        project.mkdir()
        result = work_router.detect_state(
            current_branch="issue-42-spi",
            project_path=str(project),
            workspace_path=str(workspace),
        )
        assert result["HAS_HANDOFF"] == "yes"
        assert result["HANDOFF_PATH"] == str(workspace / "HANDOFF-engine.md")

    def test_on_branch_project_handoff_wrong_issue(self, tmp_path):
        """On feature branch, HANDOFF-engine.md references different issue → no."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        self._init_git(workspace)
        (workspace / "HANDOFF-engine.md").write_text("# Handoff\nWorked on #99.")
        self._commit_file(workspace, "HANDOFF-engine.md")
        project = tmp_path / "engine"
        project.mkdir()
        result = work_router.detect_state(
            current_branch="issue-42-spi",
            project_path=str(project),
            workspace_path=str(workspace),
        )
        assert result["HAS_HANDOFF"] == "no"


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