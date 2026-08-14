"""Tests for plan_migrate.py — one-time migration from .meta to unified .plan."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "work-slot"))
from plan_migrate import migrate_if_needed
import plan_manager


class TestMigrateMetaPlusOldPlan:

    def test_merges_meta_into_plan(self, tmp_path):
        design = tmp_path / "design"
        design.mkdir()
        meta = design / ".meta"
        meta.write_text(
            "branch: issue-42-fix-auth\n"
            "state: active\n"
            "project-sha: abc123\n"
            "date: 2026-08-14\n"
            "issue: 42\n"
            "issue-repo: Hortora/soredium\n"
            "covers: 42\n"
            "design-repo: workspace\n"
        )
        plan = design / ".plan"
        plan.write_text(
            "# Work Plan — issue-42-fix-auth\n\n"
            "## Queue\n"
            "- [ ] #42 — Fix auth ← active\n\n"
            "## Session State\n"
            "Current: #42 — Fix auth\n"
            "Started: 2026-08-14\n"
        )
        result = migrate_if_needed(design)
        assert result is True
        assert not meta.exists()
        assert plan.exists()
        content = plan.read_text()
        assert "## State" in content
        assert "branch: issue-42-fix-auth" in content
        assert "state: active" in content
        assert "## Queue" in content
        assert "← active" in content

    def test_drops_issue_and_plan_fields(self, tmp_path):
        design = tmp_path / "design"
        design.mkdir()
        (design / ".meta").write_text(
            "branch: test\nstate: active\nissue: 42\nplan: yes\ncovers: 42\n"
        )
        (design / ".plan").write_text(
            "# Work Plan — test\n\n## Queue\n- [ ] #42 — Fix ← active\n\n"
            "## Session State\nStarted: 2026-08-14\n"
        )
        migrate_if_needed(design)
        tree = plan_manager.parse_plan(design / ".plan")
        assert "issue" not in tree.state
        assert "plan" not in tree.state
        assert tree.state["covers"] == "42"

    def test_preserves_queue_structure(self, tmp_path):
        design = tmp_path / "design"
        design.mkdir()
        (design / ".meta").write_text("branch: test\nstate: active\ncovers: 42,43\n")
        (design / ".plan").write_text(
            "# Work Plan — test\n\n## Queue\n"
            "- [x] #42 — Done\n- [ ] #43 — Next ← active\n\n"
            "## Session State\nStarted: 2026-08-14\n"
        )
        migrate_if_needed(design)
        tree = plan_manager.parse_plan(design / ".plan")
        assert len(tree.queue) == 2
        assert tree.queue[0].completed is True
        assert tree.queue[1].active is True


class TestMigrateMetaAlone:

    def test_creates_plan_from_single_issue_meta(self, tmp_path):
        design = tmp_path / "design"
        design.mkdir()
        meta = design / ".meta"
        meta.write_text(
            "branch: issue-99-solo\n"
            "state: active\n"
            "project-sha: def456\n"
            "date: 2026-08-10\n"
            "issue: 99\n"
            "issue-repo: Hortora/soredium\n"
            "covers: 99\n"
        )
        result = migrate_if_needed(design)
        assert result is True
        assert not meta.exists()
        plan = design / ".plan"
        assert plan.exists()
        tree = plan_manager.parse_plan(plan)
        assert tree.state["branch"] == "issue-99-solo"
        assert tree.state["state"] == "active"
        assert len(tree.queue) == 1
        assert tree.queue[0].issue_number == 99
        assert tree.queue[0].active is True

    def test_creates_plan_from_multi_issue_meta(self, tmp_path):
        design = tmp_path / "design"
        design.mkdir()
        (design / ".meta").write_text(
            "branch: issue-42-batch\n"
            "state: active\n"
            "project-sha: abc123\n"
            "date: 2026-08-10\n"
            "issue: 42\n"
            "issue-repo: Hortora/soredium\n"
            "covers: 42,43,44\n"
        )
        result = migrate_if_needed(design)
        assert result is True
        plan = design / ".plan"
        tree = plan_manager.parse_plan(plan)
        assert len(tree.queue) == 3
        assert tree.queue[0].issue_number == 42
        assert tree.queue[0].active is True
        assert tree.queue[1].issue_number == 43
        assert tree.queue[2].issue_number == 44

    def test_preserves_lifecycle_state(self, tmp_path):
        design = tmp_path / "design"
        design.mkdir()
        (design / ".meta").write_text(
            "branch: test\nstate: closing:review\ncovers: 42\n"
        )
        migrate_if_needed(design)
        tree = plan_manager.parse_plan(design / ".plan")
        assert tree.state["state"] == "closing:review"


class TestNoMigrationNeeded:

    def test_already_unified(self, tmp_path):
        design = tmp_path / "design"
        design.mkdir()
        plan = design / ".plan"
        plan.write_text(
            "# Work Plan — issue-42\n\n"
            "## State\n"
            "branch: issue-42\n"
            "state: active\n\n"
            "## Queue\n"
            "- [ ] #42 — Fix ← active\n"
        )
        result = migrate_if_needed(design)
        assert result is False

    def test_nothing_exists(self, tmp_path):
        design = tmp_path / "design"
        design.mkdir()
        result = migrate_if_needed(design)
        assert result is False

    def test_no_meta_no_plan(self, tmp_path):
        result = migrate_if_needed(tmp_path)
        assert result is False


class TestMigrateWithStaleMeta:

    def test_cleans_up_stale_meta_when_plan_already_unified(self, tmp_path):
        design = tmp_path / "design"
        design.mkdir()
        (design / ".meta").write_text("branch: stale\nstate: active\n")
        (design / ".plan").write_text(
            "# Work Plan — test\n\n## State\nbranch: test\nstate: active\n\n"
            "## Queue\n- [ ] #42 — Fix ← active\n"
        )
        result = migrate_if_needed(design)
        assert result is True
        assert not (design / ".meta").exists()
        assert (design / ".plan").exists()


class TestMigrateWithEpic:

    def test_migrates_epic_to_plan(self, tmp_path):
        design = tmp_path / "design"
        design.mkdir()
        (design / ".meta").write_text(
            "branch: issue-50-epic\nstate: active\ncovers: 50\n"
        )
        (design / ".epic").write_text(
            "# Epic — issue-50\n\n"
            "- [x] #51 — First task\n"
            "- [ ] #52 — Second task\n"
            "- [ ] #53 — Third task\n"
        )
        migrate_if_needed(design)
        assert not (design / ".meta").exists()
        assert not (design / ".epic").exists()
        tree = plan_manager.parse_plan(design / ".plan")
        assert tree.state["branch"] == "issue-50-epic"
        assert len(tree.queue) == 3
        assert tree.queue[0].completed is True
        assert tree.queue[0].issue_number == 51
        has_active = any(q.active for q in tree.queue)
        assert has_active
