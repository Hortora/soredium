"""Tests for plan_manager — .plan tree parser, writer, flatten, detect, worklog emission."""

import pytest
import sys
import unittest.mock
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "work-slot"))
import plan_manager


SINGLE_ISSUE_PLAN = """\
# Work Plan — issue-42-fix-login

## Queue
- [ ] test/repo#42 — Fix login validation ← active

## Session State
Current: #42 — Fix login validation
Started: 2026-08-04
"""

MULTI_ISSUE_PLAN = """\
# Work Plan — issue-42-batch-work

## Queue
- [x] test/repo#42 — Fix login validation
- [ ] test/repo#50 — Weighted profiles (epic)
  - [x] test/repo#108 — Add weight field
  - [ ] test/repo#109 — Update scoring ← active
  - [ ] test/repo#110 — Migration script
- [ ] test/repo#32 — Update API docs

## Session State
Current: #109 — Update scoring
Started: 2026-08-04
"""

NESTED_EPIC_PLAN = """\
# Work Plan — issue-42-nested

## Queue
- [ ] test/repo#42 — Fix login ← active
- [ ] test/repo#50 — Weighted profiles (epic)
  - [ ] test/repo#51 — Add weight field
  - [ ] test/repo#52 — Scoring subsystem (epic)
    - [ ] test/repo#60 — Score calculator
    - [ ] test/repo#61 — Score migration
  - [ ] test/repo#53 — API endpoints
- [ ] test/repo#32 — Update API docs

## Session State
Current: #42 — Fix login
Started: 2026-08-04
"""

BATCH_PLAN = """\
# Work Plan — issue-50-weighted

## Queue
- [ ] test/repo#50 — Weighted profiles (epic)
  ### Batch 1 — Data model ← current
  - [ ] test/repo#108 — Add weight field ← active
  - [ ] test/repo#109 — Migration script
  ### Batch 2 — Scoring logic
  - [ ] test/repo#110 — Update scoring algorithm
  - [ ] test/repo#111 — Recalculate existing scores

## Session State
Current: #108 — Add weight field
Started: 2026-08-04
"""

EMPTY_PLAN = """\
# Work Plan — improve-scoring-engine

## Queue
(empty — issues created during design)

## Session State
Started: 2026-08-04
"""

UNIFIED_PLAN = """\
# Work Plan — issue-42-fix-login

## State
branch: issue-42-fix-login
state: active
project-sha: abc123
date: 2026-08-04
issue-repo: Hortora/soredium
covers: 42
design-repo: workspace
flyway-next-v: unknown

## Queue
- [ ] #42 — Fix login validation ← active

## Deferred
- [ ] Follow-up refactor (S / Low) [soredium]
"""

UNIFIED_PLAN_MULTI = """\
# Work Plan — issue-42-batch

## State
branch: issue-42-batch
state: active
date: 2026-08-04
covers: 42,43,44
issue-repo: Hortora/soredium

## Queue
- [x] #42 — Fix login
- [ ] #43 — Add tests ← active
- [ ] #44 — Update docs
"""


class TestParsePlan:
    def test_single_issue(self, tmp_path):
        plan_file = tmp_path / ".plan"
        plan_file.write_text(SINGLE_ISSUE_PLAN)
        tree = plan_manager.parse_plan(plan_file)
        assert len(tree.queue) == 1
        assert tree.queue[0].issue_number == 42
        assert tree.queue[0].active is True
        assert tree.queue[0].is_epic is False
        assert tree.current_issue == 42

    def test_multi_issue_with_epic(self, tmp_path):
        plan_file = tmp_path / ".plan"
        plan_file.write_text(MULTI_ISSUE_PLAN)
        tree = plan_manager.parse_plan(plan_file)
        assert len(tree.queue) == 3
        assert tree.queue[0].completed is True
        assert tree.queue[1].is_epic is True
        assert len(tree.queue[1].children) == 3
        assert tree.queue[1].children[1].active is True
        assert tree.current_issue == 109

    def test_nested_epics(self, tmp_path):
        plan_file = tmp_path / ".plan"
        plan_file.write_text(NESTED_EPIC_PLAN)
        tree = plan_manager.parse_plan(plan_file)
        epic50 = tree.queue[1]
        assert epic50.children[1].is_epic is True
        assert len(epic50.children[1].children) == 2
        assert epic50.children[1].children[0].issue_number == 60

    def test_batch_planning(self, tmp_path):
        plan_file = tmp_path / ".plan"
        plan_file.write_text(BATCH_PLAN)
        tree = plan_manager.parse_plan(plan_file)
        epic = tree.queue[0]
        assert len(epic.children) == 4
        assert epic.children[0].batch == "Batch 1 — Data model"
        assert epic.children[1].batch == "Batch 1 — Data model"
        assert epic.children[2].batch == "Batch 2 — Scoring logic"
        assert epic.children[3].batch == "Batch 2 — Scoring logic"

    def test_empty_queue(self, tmp_path):
        plan_file = tmp_path / ".plan"
        plan_file.write_text(EMPTY_PLAN)
        tree = plan_manager.parse_plan(plan_file)
        assert len(tree.queue) == 0
        assert tree.current_issue is None

    def test_heading_parsed(self, tmp_path):
        plan_file = tmp_path / ".plan"
        plan_file.write_text(SINGLE_ISSUE_PLAN)
        tree = plan_manager.parse_plan(plan_file)
        assert tree.heading == "Work Plan — issue-42-fix-login"

    def test_session_state_parsed(self, tmp_path):
        plan_file = tmp_path / ".plan"
        plan_file.write_text(SINGLE_ISSUE_PLAN)
        tree = plan_manager.parse_plan(plan_file)
        assert tree.started == "2026-08-04"


class TestFlattenLeaves:
    def test_nested_epics_flatten(self, tmp_path):
        plan_file = tmp_path / ".plan"
        plan_file.write_text(NESTED_EPIC_PLAN)
        tree = plan_manager.parse_plan(plan_file)
        leaves = plan_manager.flatten_leaves(tree)
        assert [leaf.issue_number for leaf in leaves] == [42, 51, 60, 61, 53, 32]

    def test_single_issue_flatten(self, tmp_path):
        plan_file = tmp_path / ".plan"
        plan_file.write_text(SINGLE_ISSUE_PLAN)
        tree = plan_manager.parse_plan(plan_file)
        leaves = plan_manager.flatten_leaves(tree)
        assert len(leaves) == 1
        assert leaves[0].issue_number == 42

    def test_empty_queue_flatten(self, tmp_path):
        plan_file = tmp_path / ".plan"
        plan_file.write_text(EMPTY_PLAN)
        tree = plan_manager.parse_plan(plan_file)
        leaves = plan_manager.flatten_leaves(tree)
        assert leaves == []

    def test_multi_issue_flatten(self, tmp_path):
        plan_file = tmp_path / ".plan"
        plan_file.write_text(MULTI_ISSUE_PLAN)
        tree = plan_manager.parse_plan(plan_file)
        leaves = plan_manager.flatten_leaves(tree)
        assert [leaf.issue_number for leaf in leaves] == [42, 108, 109, 110, 32]

    def test_batch_plan_flatten(self, tmp_path):
        plan_file = tmp_path / ".plan"
        plan_file.write_text(BATCH_PLAN)
        tree = plan_manager.parse_plan(plan_file)
        leaves = plan_manager.flatten_leaves(tree)
        assert [leaf.issue_number for leaf in leaves] == [108, 109, 110, 111]

    def test_leaves_have_parent_epic(self, tmp_path):
        plan_file = tmp_path / ".plan"
        plan_file.write_text(NESTED_EPIC_PLAN)
        tree = plan_manager.parse_plan(plan_file)
        leaves = plan_manager.flatten_leaves(tree)
        assert leaves[0].parent_epic is None  # #42 is top-level
        assert leaves[1].parent_epic == 50  # #51 is child of #50
        assert leaves[2].parent_epic == 52  # #60 is child of #52
        assert leaves[5].parent_epic is None  # #32 is top-level

    def test_leaves_have_batch(self, tmp_path):
        plan_file = tmp_path / ".plan"
        plan_file.write_text(BATCH_PLAN)
        tree = plan_manager.parse_plan(plan_file)
        leaves = plan_manager.flatten_leaves(tree)
        assert leaves[0].batch == "Batch 1 — Data model"
        assert leaves[2].batch == "Batch 2 — Scoring logic"


class TestWritePlan:
    @pytest.mark.parametrize("content", [
        SINGLE_ISSUE_PLAN,
        MULTI_ISSUE_PLAN,
        NESTED_EPIC_PLAN,
        BATCH_PLAN,
        EMPTY_PLAN,
    ])
    def test_round_trip(self, tmp_path, content):
        plan_file = tmp_path / ".plan"
        plan_file.write_text(content)
        tree = plan_manager.parse_plan(plan_file)
        plan_manager.rewrite_plan(plan_file, tree)
        tree2 = plan_manager.parse_plan(plan_file)
        leaves1 = plan_manager.flatten_leaves(tree)
        leaves2 = plan_manager.flatten_leaves(tree2)
        assert [l.issue_number for l in leaves1] == [l.issue_number for l in leaves2]
        assert [l.completed for l in leaves1] == [l.completed for l in leaves2]
        assert [l.active for l in leaves1] == [l.active for l in leaves2]


class TestBuildPlanContent:
    def test_builds_single_issue(self):
        items = [plan_manager.QueueItem(42, "Fix login", active=True, repo="test/repo")]
        content = plan_manager.build_plan_content("issue-42-fix-login", items, "2026-08-04")
        assert "# Work Plan — issue-42-fix-login" in content
        assert "- [ ] test/repo#42 — Fix login ← active" in content
        assert "Current: test/repo#42 — Fix login" in content

    def test_builds_epic_with_children(self):
        children = [
            plan_manager.QueueItem(108, "Add weight field", active=True, repo="test/repo"),
            plan_manager.QueueItem(109, "Update scoring", repo="test/repo"),
        ]
        items = [plan_manager.QueueItem(50, "Weighted profiles", is_epic=True, children=children, repo="test/repo")]
        content = plan_manager.build_plan_content("issue-50-weighted", items, "2026-08-04")
        assert "(epic)" in content
        assert "  - [ ] test/repo#108 — Add weight field ← active" in content
        assert "  - [ ] test/repo#109 — Update scoring" in content

    def test_builds_empty_queue(self):
        content = plan_manager.build_plan_content("improve-scoring", [], "2026-08-04")
        assert "(empty" in content

    def test_builds_nested_epic(self):
        inner = [plan_manager.QueueItem(60, "Calculator", repo="test/repo"), plan_manager.QueueItem(61, "Migration", repo="test/repo")]
        children = [
            plan_manager.QueueItem(51, "Weight field", active=True, repo="test/repo"),
            plan_manager.QueueItem(52, "Scoring subsystem", is_epic=True, children=inner, repo="test/repo"),
        ]
        items = [plan_manager.QueueItem(50, "Weighted profiles", is_epic=True, children=children, repo="test/repo")]
        content = plan_manager.build_plan_content("issue-50-test", items, "2026-08-04")
        assert "    - [ ] test/repo#60 — Calculator" in content  # double-indented


class TestAppendToQueue:
    def test_appends_to_existing(self, tmp_path):
        plan_file = tmp_path / ".plan"
        plan_file.write_text(SINGLE_ISSUE_PLAN)
        plan_manager.append_to_queue(plan_file, [plan_manager.QueueItem(99, "New issue", repo="test/repo")])
        tree = plan_manager.parse_plan(plan_file)
        assert len(tree.queue) == 2
        assert tree.queue[1].issue_number == 99

    def test_appends_to_empty(self, tmp_path):
        plan_file = tmp_path / ".plan"
        plan_file.write_text(EMPTY_PLAN)
        plan_manager.append_to_queue(plan_file, [plan_manager.QueueItem(42, "First issue", active=True, repo="test/repo")])
        tree = plan_manager.parse_plan(plan_file)
        assert len(tree.queue) == 1
        assert tree.queue[0].active is True

    def test_appends_multiple(self, tmp_path):
        plan_file = tmp_path / ".plan"
        plan_file.write_text(SINGLE_ISSUE_PLAN)
        plan_manager.append_to_queue(plan_file, [
            plan_manager.QueueItem(99, "Issue A", repo="test/repo"),
            plan_manager.QueueItem(100, "Issue B", repo="test/repo"),
        ])
        tree = plan_manager.parse_plan(plan_file)
        assert len(tree.queue) == 3


class TestAdvance:
    def _setup(self, tmp_path, plan_content, covers="42"):
        design = tmp_path / "design"
        design.mkdir(exist_ok=True)
        plan_file = design / ".plan"
        plan_file.write_text(plan_content)
        meta = design / ".meta"
        meta.write_text(f"branch: test\nissue: 42\ncovers: {covers}\n")
        return plan_file, meta

    def test_linear_advance(self, tmp_path):
        plan = "# Work Plan — test\n\n## Queue\n- [ ] test/repo#42 — A ← active\n- [ ] test/repo#43 — B\n\n## Session State\nCurrent: #42 — A\nStarted: 2026-08-04\n"
        plan_file, meta = self._setup(tmp_path, plan)
        result = plan_manager.advance(plan_file)
        assert result.completed == 42
        assert result.next_issue == 43
        assert result.epic_complete is False
        tree = plan_manager.parse_plan(plan_file)
        assert tree.queue[0].completed is True
        assert tree.queue[1].active is True
        assert "42" in meta.read_text()

    def test_epic_child_advance(self, tmp_path):
        plan_file, meta = self._setup(tmp_path, MULTI_ISSUE_PLAN, covers="42")
        result = plan_manager.advance(plan_file)
        assert result.completed == 109
        assert result.next_issue == 110
        assert result.batch_complete is False

    def test_epic_last_child_completes_parent(self, tmp_path):
        plan = "# Work Plan — test\n\n## Queue\n- [ ] test/repo#50 — Epic (epic)\n  - [x] test/repo#108 — A\n  - [ ] test/repo#109 — B ← active\n- [ ] test/repo#32 — C\n\n## Session State\nCurrent: #109 — B\nStarted: 2026-08-04\n"
        plan_file, meta = self._setup(tmp_path, plan)
        result = plan_manager.advance(plan_file)
        assert result.completed == 109
        assert result.next_issue == 32
        tree = plan_manager.parse_plan(plan_file)
        assert tree.queue[0].completed is True

    def test_nested_epic_completes(self, tmp_path):
        plan = "# Work Plan — test\n\n## Queue\n- [ ] test/repo#50 — Epic (epic)\n  - [ ] test/repo#52 — Nested (epic)\n    - [x] test/repo#60 — A\n    - [ ] test/repo#61 — B ← active\n  - [ ] test/repo#53 — C\n\n## Session State\nCurrent: #61 — B\nStarted: 2026-08-04\n"
        plan_file, meta = self._setup(tmp_path, plan)
        result = plan_manager.advance(plan_file)
        assert result.completed == 61
        assert result.next_issue == 53
        tree = plan_manager.parse_plan(plan_file)
        assert tree.queue[0].children[0].completed is True

    def test_queue_exhausted(self, tmp_path):
        plan = "# Work Plan — test\n\n## Queue\n- [x] test/repo#42 — A\n- [ ] test/repo#43 — B ← active\n\n## Session State\nCurrent: #43 — B\nStarted: 2026-08-04\n"
        plan_file, meta = self._setup(tmp_path, plan)
        result = plan_manager.advance(plan_file)
        assert result.completed == 43
        assert result.next_issue is None
        assert result.epic_complete is True

    def test_batch_boundary_safe_exit(self, tmp_path):
        plan = "# Work Plan — test\n\n## Queue\n- [ ] test/repo#50 — Epic (epic)\n  ### Batch 1 — Model\n  - [x] test/repo#108 — A\n  - [ ] test/repo#109 — B ← active\n  ### Batch 2 — Logic\n  - [ ] test/repo#110 — C\n\n## Session State\nCurrent: #109 — B\nStarted: 2026-08-04\n"
        plan_file, meta = self._setup(tmp_path, plan)
        result = plan_manager.advance(plan_file)
        assert result.batch_complete is True
        assert result.safe_exit is True
        assert result.next_issue == 110

    def test_dispatches_to_plan(self, tmp_path):
        design = tmp_path / "design"
        design.mkdir()
        plan_file = design / ".plan"
        plan_file.write_text("# Work Plan — test\n\n## Queue\n- [ ] test/repo#42 — A ← active\n- [ ] test/repo#43 — B\n\n## Session State\nCurrent: #42 — A\nStarted: 2026-08-04\n")
        result = plan_manager.advance_issue(plan_file)
        assert result.completed == 42

    def test_raises_when_no_files(self, tmp_path):
        with pytest.raises(plan_manager.NoQueueFile):
            plan_manager.advance_issue(tmp_path / "nope.plan")


class TestDetectEpic:
    def test_detects_epic(self):
        body = "## Scope\n- [ ] #108 — Add weight\n- [ ] #109 — Update scoring\n"
        with unittest.mock.patch.object(plan_manager, '_gh_issue_body', return_value=body):
            with unittest.mock.patch.object(plan_manager, '_gh_issue_title', return_value="Weighted profiles"):
                result = plan_manager.detect_epic(50, "Org/repo")
        assert result.is_epic is True
        assert len(result.children) == 2
        assert result.children[0].issue_number == 108
        assert result.children[1].issue_number == 109

    def test_detects_leaf(self):
        with unittest.mock.patch.object(plan_manager, '_gh_issue_body', return_value="Just a regular issue"):
            with unittest.mock.patch.object(plan_manager, '_gh_issue_title', return_value="Fix login"):
                result = plan_manager.detect_epic(42, "Org/repo")
        assert result.is_epic is False
        assert result.children == []

    def test_skips_closed_children(self):
        body = "## Scope\n- [x] #108 — Done\n- [ ] #109 — Todo\n"
        with unittest.mock.patch.object(plan_manager, '_gh_issue_body', return_value=body):
            with unittest.mock.patch.object(plan_manager, '_gh_issue_title', return_value="Epic"):
                result = plan_manager.detect_epic(50, "Org/repo")
        assert len(result.children) == 1
        assert result.children[0].issue_number == 109

    def test_no_scope_section_is_leaf(self):
        body = "## Description\nSome text\n## Tasks\n- [ ] #108 — Something\n"
        with unittest.mock.patch.object(plan_manager, '_gh_issue_body', return_value=body):
            with unittest.mock.patch.object(plan_manager, '_gh_issue_title', return_value="Not epic"):
                result = plan_manager.detect_epic(42, "Org/repo")
        assert result.is_epic is False


class TestBuildQueue:
    def _mock_detect(self, epics):
        """Helper: epics is a dict of issue_number -> list of child numbers (or None for leaf)."""
        def fake_detect(n, repo):
            if n in epics and epics[n] is not None:
                children = [plan_manager.QueueItem(c, f"Child {c}", repo=repo) for c in epics[n]]
                return plan_manager.QueueItem(n, f"Epic {n}", is_epic=True, children=children, repo=repo)
            return plan_manager.QueueItem(n, f"Issue {n}", repo=repo)
        return fake_detect

    def test_flat_list(self):
        with unittest.mock.patch.object(plan_manager, 'detect_epic', side_effect=self._mock_detect({})):
            queue = plan_manager.build_queue([42, 43, 44], "Org/repo")
        assert len(queue) == 3
        assert all(not item.is_epic for item in queue)

    def test_epic_expansion(self):
        with unittest.mock.patch.object(plan_manager, 'detect_epic', side_effect=self._mock_detect({50: [108, 109]})):
            queue = plan_manager.build_queue([42, 50, 32], "Org/repo")
        assert len(queue) == 3
        assert queue[1].is_epic is True
        assert len(queue[1].children) == 2

    def test_cycle_detection(self):
        def cyclic_detect(n, repo):
            if n == 50:
                return plan_manager.QueueItem(50, "Epic 50", is_epic=True,
                    children=[plan_manager.QueueItem(99, "Child 99", repo=repo)], repo=repo)
            if n == 99:
                return plan_manager.QueueItem(99, "Epic 99", is_epic=True,
                    children=[plan_manager.QueueItem(50, "Cycle back", repo=repo)], repo=repo)
            return plan_manager.QueueItem(n, f"Issue {n}", repo=repo)

        with unittest.mock.patch.object(plan_manager, 'detect_epic', side_effect=cyclic_detect):
            queue = plan_manager.build_queue([50], "Org/repo")
        # Should not infinite loop — cycle on 50 is caught
        assert len(queue) == 1

    def test_sets_first_leaf_active(self):
        with unittest.mock.patch.object(plan_manager, 'detect_epic', side_effect=self._mock_detect({50: [108, 109]})):
            queue = plan_manager.build_queue([50, 32], "Org/repo")
        # First leaf is #108 (child of epic #50)
        leaves = []
        def collect(items):
            for item in items:
                if item.children:
                    collect(item.children)
                else:
                    leaves.append(item)
        collect(queue)
        assert leaves[0].active is True
        assert leaves[0].issue_number == 108


class TestDetect:
    def test_detects_plan(self, tmp_path):
        design = tmp_path / "design"
        design.mkdir()
        (design / ".plan").write_text(SINGLE_ISSUE_PLAN)
        result = plan_manager.detect(tmp_path)
        assert result is not None
        assert result["has_plan"] is True
        assert result["active_issue"] == 42
        assert result["plan_path"] == str(design / ".plan")

    def test_no_plan(self, tmp_path):
        result = plan_manager.detect(tmp_path)
        assert result is None

    def test_detects_with_position(self, tmp_path):
        design = tmp_path / "design"
        design.mkdir()
        (design / ".plan").write_text(MULTI_ISSUE_PLAN)
        result = plan_manager.detect(tmp_path)
        assert result["active_issue"] == 109
        assert result["completed_count"] == 2
        assert result["total_count"] == 5


class TestDetectRootLevelPlan:
    def test_detect_finds_plan_at_root_not_just_design(self, tmp_path):
        """Slot-root .plan lives at <path>/.plan, not <path>/design/.plan."""
        (tmp_path / ".plan").write_text(SINGLE_ISSUE_PLAN)
        result = plan_manager.detect(tmp_path)
        assert result is not None, "detect() must find .plan at the given path root, not only design/"
        assert result["active_issue"] == 42

    def test_root_takes_precedence_over_design_subdir(self, tmp_path):
        """If both <path>/.plan and <path>/design/.plan exist, prefer root."""
        design = tmp_path / "design"
        design.mkdir()
        (design / ".plan").write_text(MULTI_ISSUE_PLAN)
        (tmp_path / ".plan").write_text(SINGLE_ISSUE_PLAN)
        result = plan_manager.detect(tmp_path)
        assert result is not None
        assert result["active_issue"] == 42, "root .plan should take precedence"


class TestDetectSlotMode:
    def test_detect_finds_plan_in_slot_workspace(self, tmp_path):
        """In slot mode, workspace is a clone inside the slot.
        detect() should find design/.plan there just like branch mode."""
        slot_dir = tmp_path / "slots" / "38"
        slot_dir.mkdir(parents=True)
        workspace_clone = slot_dir / "cc-praxis"
        workspace_clone.mkdir()
        design = workspace_clone / "design"
        design.mkdir()
        (design / ".plan").write_text(SINGLE_ISSUE_PLAN)
        result = plan_manager.detect(workspace_clone)
        assert result is not None
        assert result["active_issue"] == 42

    def test_advance_works_with_slot_paths(self, tmp_path):
        """advance() should work with slot-mode paths for plan and meta."""
        slot_dir = tmp_path / "slots" / "38"
        slot_dir.mkdir(parents=True)
        workspace_clone = slot_dir / "cc-praxis"
        workspace_clone.mkdir()
        design = workspace_clone / "design"
        design.mkdir()
        plan_file = design / ".plan"
        plan_file.write_text(
            "# Work Plan — test\n\n"
            "## State\nbranch: test\nissue-repo: Org/repo\ncovers: 42\n\n"
            "## Queue\n"
            "- [ ] #42 — A ← active\n"
            "- [ ] #43 — B\n"
        )
        slot_project = slot_dir / "soredium"
        slot_project.mkdir()
        with patch.object(plan_manager, '_emit_issue_events') as mock_emit:
            result = plan_manager.advance(plan_file, repo_path=str(slot_project))
        assert result.completed == 42
        assert result.next_issue == 43
        mock_emit.assert_called_once_with(plan_file, str(slot_project), 42, 43)


class TestReadPlanState:
    def test_reads_branch_and_issue_repo(self, tmp_path):
        meta = tmp_path / ".meta"
        meta.write_text("branch: issue-42-fix\nstate: active\nissue: 42\nissue-repo: Hortora/soredium\n")
        fields = plan_manager._read_plan_state(meta)
        assert fields["branch"] == "issue-42-fix"
        assert fields["issue-repo"] == "Hortora/soredium"

    def test_handles_empty_values(self, tmp_path):
        meta = tmp_path / ".meta"
        meta.write_text("branch: test\nissue:\nissue-repo:\n")
        fields = plan_manager._read_plan_state(meta)
        assert fields["branch"] == "test"
        assert fields["issue"] == ""


class TestEmitIssueEvents:
    def _setup_meta(self, tmp_path):
        meta = tmp_path / ".meta"
        meta.write_text("branch: issue-42-fix\nissue: 42\nissue-repo: Hortora/soredium\ncovers: 42\n")
        return meta

    def test_emits_complete_and_activate(self, tmp_path):
        meta = self._setup_meta(tmp_path)
        mock_wl = MagicMock()
        mock_conn = MagicMock()
        mock_wl.connect.return_value = mock_conn
        with patch.dict('sys.modules', {'worklog': mock_wl}):
            plan_manager._emit_issue_events(meta, "/repo", 42, 43)
        mock_wl.record_issue_complete.assert_called_once_with(
            mock_conn, "issue-42-fix", "/repo", 42, "Hortora/soredium")
        mock_wl.record_issue_activate.assert_called_once_with(
            mock_conn, "issue-42-fix", "/repo", 43, "Hortora/soredium")

    def test_emits_only_complete_when_no_next(self, tmp_path):
        meta = self._setup_meta(tmp_path)
        mock_wl = MagicMock()
        mock_conn = MagicMock()
        mock_wl.connect.return_value = mock_conn
        with patch.dict('sys.modules', {'worklog': mock_wl}):
            plan_manager._emit_issue_events(meta, "/repo", 42, None)
        mock_wl.record_issue_complete.assert_called_once()
        mock_wl.record_issue_activate.assert_not_called()

    def test_swallows_errors(self, tmp_path):
        meta = self._setup_meta(tmp_path)
        mock_wl = MagicMock()
        mock_wl.connect.side_effect = Exception("db locked")
        with patch.dict('sys.modules', {'worklog': mock_wl}):
            plan_manager._emit_issue_events(meta, "/repo", 42, 43)


class TestAdvanceWorklog:
    def _setup(self, tmp_path, plan_content, covers="42"):
        design = tmp_path / "design"
        design.mkdir(exist_ok=True)
        plan_file = design / ".plan"
        # Inject ## State into plan content for _emit_issue_events
        state_block = (
            f"## State\n"
            f"branch: test-branch\n"
            f"issue-repo: Org/repo\n"
            f"covers: {covers}\n\n"
        )
        enriched = plan_content.replace("## Queue", state_block + "## Queue")
        plan_file.write_text(enriched)
        return plan_file

    def test_advance_emits_events_when_repo_path_provided(self, tmp_path):
        plan = "# Work Plan — test\n\n## Queue\n- [ ] #42 — A ← active\n- [ ] #43 — B\n\n## Session State\nCurrent: #42 — A\nStarted: 2026-08-04\n"
        plan_file = self._setup(tmp_path, plan)
        with patch.object(plan_manager, '_emit_issue_events') as mock_emit:
            result = plan_manager.advance(plan_file, repo_path="/project")
            mock_emit.assert_called_once_with(plan_file, "/project", 42, 43)

    def test_advance_skips_worklog_when_no_repo_path(self, tmp_path):
        plan = "# Work Plan — test\n\n## Queue\n- [ ] #42 — A ← active\n- [ ] #43 — B\n\n## Session State\nCurrent: #42 — A\nStarted: 2026-08-04\n"
        plan_file = self._setup(tmp_path, plan)
        with patch.object(plan_manager, '_emit_issue_events') as mock_emit:
            plan_manager.advance(plan_file)
            mock_emit.assert_not_called()

    def test_advance_emits_none_next_on_queue_exhausted(self, tmp_path):
        plan = "# Work Plan — test\n\n## Queue\n- [x] #42 — A\n- [ ] #43 — B ← active\n\n## Session State\nCurrent: #43 — B\nStarted: 2026-08-04\n"
        plan_file = self._setup(tmp_path, plan)
        with patch.object(plan_manager, '_emit_issue_events') as mock_emit:
            plan_manager.advance(plan_file, repo_path="/project")
            mock_emit.assert_called_once_with(plan_file, "/project", 43, None)

    def test_advance_worklog_error_does_not_break_advance(self, tmp_path):
        plan = "# Work Plan — test\n\n## Queue\n- [ ] #42 — A ← active\n- [ ] #43 — B\n\n## Session State\nCurrent: #42 — A\nStarted: 2026-08-04\n"
        plan_file = self._setup(tmp_path, plan)
        with patch.object(plan_manager, '_emit_issue_events', side_effect=Exception("boom")):
            result = plan_manager.advance(plan_file, repo_path="/project")
            assert result.completed == 42
            assert result.next_issue == 43
            tree = plan_manager.parse_plan(plan_file)
            assert tree.queue[0].completed is True


class TestAdvanceIssueWorklog:
    def test_passes_repo_path_to_plan_advance(self, tmp_path):
        design = tmp_path / "design"
        design.mkdir()
        plan_file = design / ".plan"
        plan_file.write_text("# Work Plan — test\n\n## State\nbranch: test\nissue-repo: Org/repo\ncovers: 42\n\n## Queue\n- [ ] #42 — A ← active\n- [ ] #43 — B\n")
        with patch.object(plan_manager, '_emit_issue_events') as mock_emit:
            result = plan_manager.advance_issue(plan_file, repo_path="/project")
            mock_emit.assert_called_once_with(plan_file, "/project", 42, 43)


class TestCompleteActiveIssue:
    def _setup(self, tmp_path, plan_content):
        design = tmp_path / "design"
        design.mkdir(exist_ok=True)
        plan_file = design / ".plan"
        state_block = "## State\nbranch: test-branch\nissue-repo: Org/repo\ncovers: 42\n\n"
        enriched = plan_content.replace("## Queue", state_block + "## Queue")
        plan_file.write_text(enriched)
        return plan_file

    def test_emits_complete_for_active_issue(self, tmp_path):
        plan = "# Work Plan — test\n\n## Queue\n- [ ] #42 — A ← active\n- [ ] #43 — B\n\n## Session State\nCurrent: #42 — A\nStarted: 2026-08-04\n"
        plan_file = self._setup(tmp_path, plan)
        with patch.object(plan_manager, '_emit_issue_events') as mock_emit:
            result = plan_manager.complete_active_issue(plan_file, "/project")
            assert result == 42
            mock_emit.assert_called_once_with(plan_file, "/project", 42, next_issue=None)

    def test_returns_none_when_no_active_issue(self, tmp_path):
        plan = "# Work Plan — test\n\n## Queue\n- [x] #42 — A\n- [x] #43 — B\n\n## Session State\nCurrent: none\nStarted: 2026-08-04\n"
        plan_file = self._setup(tmp_path, plan)
        with patch.object(plan_manager, '_emit_issue_events') as mock_emit:
            result = plan_manager.complete_active_issue(plan_file, "/project")
            assert result is None
            mock_emit.assert_not_called()

    def test_does_not_modify_plan_file(self, tmp_path):
        plan = "# Work Plan — test\n\n## Queue\n- [ ] #42 — A ← active\n- [ ] #43 — B\n\n## Session State\nCurrent: #42 — A\nStarted: 2026-08-04\n"
        plan_file = self._setup(tmp_path, plan)
        original_content = plan_file.read_text()
        with patch.object(plan_manager, '_emit_issue_events'):
            plan_manager.complete_active_issue(plan_file, "/project")
        assert plan_file.read_text() == original_content


class TestCreateMainPlan:

    def test_creates_plan_with_items(self, tmp_path):
        workspace = tmp_path / "wksp"
        workspace.mkdir()
        items = [
            {"number": 170, "title": "pre-merge hook"},
            {"number": 95, "title": "mechanize LLM ops"},
        ]
        plan_path = plan_manager.create_main_plan(workspace, items, "soredium", issue_repo="test/repo")
        assert plan_path.exists()
        content = plan_path.read_text()
        assert "test/repo#170" in content
        assert "test/repo#95" in content
        assert "← active" in content
        assert "Work Plan — soredium" in content

    def test_first_item_is_active(self, tmp_path):
        workspace = tmp_path / "wksp"
        workspace.mkdir()
        items = [
            {"number": 10, "title": "first"},
            {"number": 20, "title": "second"},
        ]
        plan_manager.create_main_plan(workspace, items, "test", issue_repo="test/repo")
        tree = plan_manager.parse_plan(workspace / ".plan")
        leaves = plan_manager.flatten_leaves(tree)
        assert leaves[0].active is True
        assert leaves[1].active is False

    def test_detect_finds_main_plan(self, tmp_path):
        workspace = tmp_path / "wksp"
        workspace.mkdir()
        items = [{"number": 42, "title": "some issue"}]
        plan_manager.create_main_plan(workspace, items, "test", issue_repo="test/repo")
        result = plan_manager.detect(workspace)
        assert result is not None
        assert result["active_issue"] == 42

    def test_creates_plan_at_root(self, tmp_path):
        workspace = tmp_path / "wksp"
        workspace.mkdir()
        items = [{"number": 1, "title": "test"}]
        plan_manager.create_main_plan(workspace, items, issue_repo="test/repo")
        assert (workspace / ".plan").exists()


# ---------------------------------------------------------------------------
# Deferred items
# ---------------------------------------------------------------------------

PLAN_WITH_DEFERRED = """\
# Work Plan — issue-95-mechanize

## State
issue-repo: test/repo

## Queue
- [x] test/repo#95 — Mechanize inline operations
- [ ] test/repo#83 — Delegate handover subagents ← active

## Deferred
- [ ] Extract push retry logic (S / Low) [soredium]
- [ ] Add restore-slot command (M / Med) [soredium]
- [ ] Fix portal resolutions in blocks-ui (S / Low) [blocks-ui]
"""

PLAN_NO_DEFERRED = """\
# Work Plan — issue-42-fix

## Queue
- [ ] test/repo#42 — Fix login ← active

## Session State
Current: #42 — Fix login
Started: 2026-08-06
"""


class TestDeferredParsing:
    def test_parses_deferred_items(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(PLAN_WITH_DEFERRED)
        tree = plan_manager.parse_plan(plan)
        assert len(tree.deferred) == 3
        assert tree.deferred[0].title == "Extract push retry logic"
        assert tree.deferred[0].scale == "S"
        assert tree.deferred[0].complexity == "Low"
        assert tree.deferred[0].repos == ["soredium"]

    def test_parses_plan_without_deferred(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(PLAN_NO_DEFERRED)
        tree = plan_manager.parse_plan(plan)
        assert tree.deferred == []

    def test_deferred_with_multiple_repos(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(
            "# Work Plan — test\n\n## Queue\n- [ ] test/repo#1 — Work ← active\n\n"
            "## Deferred\n- [ ] Cross-repo fix (M / High) [engine, iot]\n\n"
            "## Session State\nCurrent: #1 — Work\nStarted: 2026-08-06\n"
        )
        tree = plan_manager.parse_plan(plan)
        assert len(tree.deferred) == 1
        assert tree.deferred[0].repos == ["engine", "iot"]


class TestDeferredRoundTrip:
    def test_deferred_survives_rewrite(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(PLAN_WITH_DEFERRED)
        tree = plan_manager.parse_plan(plan)
        plan_manager.rewrite_plan(plan, tree)
        tree2 = plan_manager.parse_plan(plan)
        assert len(tree2.deferred) == 3
        assert tree2.deferred[0].title == "Extract push retry logic"
        assert tree2.deferred[2].repos == ["blocks-ui"]

    def test_empty_deferred_not_written(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(PLAN_NO_DEFERRED)
        tree = plan_manager.parse_plan(plan)
        plan_manager.rewrite_plan(plan, tree)
        content = plan.read_text()
        assert "## Deferred" not in content


class TestAppendDeferred:
    def test_appends_to_existing_deferred(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(PLAN_WITH_DEFERRED)
        plan_manager.append_deferred(
            plan, "New follow-up task", "M", "Med", ["soredium"]
        )
        tree = plan_manager.parse_plan(plan)
        assert len(tree.deferred) == 4
        assert tree.deferred[3].title == "New follow-up task"

    def test_appends_to_plan_without_deferred(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(PLAN_NO_DEFERRED)
        plan_manager.append_deferred(
            plan, "Discovered gap", "S", "Low", ["soredium"]
        )
        tree = plan_manager.parse_plan(plan)
        assert len(tree.deferred) == 1
        assert tree.deferred[0].title == "Discovered gap"
        assert tree.deferred[0].scale == "S"


class TestPromoteDeferred:
    def test_promotes_matching_repos(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(PLAN_WITH_DEFERRED)
        tree = plan_manager.parse_plan(plan)
        # Complete the last agreed item so promote makes sense
        for item in tree.queue:
            item.completed = True
            item.active = False
        plan_manager.rewrite_plan(plan, tree)

        promoted = plan_manager.promote_deferred(plan, available_repos=["soredium"])
        assert len(promoted) == 2
        tree2 = plan_manager.parse_plan(plan)
        # 2 promoted items added to queue
        leaf_titles = [l.title for l in plan_manager.flatten_leaves(tree2)]
        assert "Extract push retry logic" in leaf_titles
        assert "Add restore-slot command" in leaf_titles
        # blocks-ui item stays in deferred
        assert len(tree2.deferred) == 1
        assert tree2.deferred[0].repos == ["blocks-ui"]

    def test_promotes_nothing_when_no_repo_match(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(PLAN_WITH_DEFERRED)
        promoted = plan_manager.promote_deferred(plan, available_repos=["engine"])
        assert len(promoted) == 0
        tree = plan_manager.parse_plan(plan)
        assert len(tree.deferred) == 3

    def test_promotes_all_when_all_match(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(PLAN_WITH_DEFERRED)
        promoted = plan_manager.promote_deferred(
            plan, available_repos=["soredium", "blocks-ui"]
        )
        assert len(promoted) == 3
        tree = plan_manager.parse_plan(plan)
        assert tree.deferred == []


class TestAdvanceWithDeferred:
    def test_advance_signals_deferred_when_queue_done(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(
            "# Work Plan — test\n\n## Queue\n- [x] test/repo#1 — First\n"
            "- [ ] test/repo#2 — Last ← active\n\n"
            "## Deferred\n- [ ] Follow-up (S / Low) [soredium]\n\n"
            "## Session State\nCurrent: #2 — Last\nStarted: 2026-08-06\n"
        )
        meta = tmp_path / ".meta"
        meta.write_text("branch: test\nissue: 1\n")
        result = plan_manager.advance(plan)
        assert result.has_deferred is True
        assert result.next_issue is None

    def test_advance_no_deferred_flag_when_queue_not_done(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(
            "# Work Plan — test\n\n## Queue\n"
            "- [ ] test/repo#1 — First ← active\n- [ ] test/repo#2 — Second\n\n"
            "## Deferred\n- [ ] Follow-up (S / Low) [soredium]\n\n"
            "## Session State\nCurrent: #1 — First\nStarted: 2026-08-06\n"
        )
        meta = tmp_path / ".meta"
        meta.write_text("branch: test\nissue: 1\n")
        result = plan_manager.advance(plan)
        assert result.has_deferred is False
        assert result.next_issue == 2


class TestDeferredReason:
    def test_parses_reason(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(
            "# Work Plan — test\n\n## Queue\n- [ ] test/repo#1 — Work ← active\n\n"
            "## Deferred\n"
            "- [ ] Schema migration (M / High) [engine] — blocked by #55 upstream release\n"
            "- [ ] Quick cleanup (XS / Low) [soredium]\n\n"
            "## Session State\nCurrent: #1 — Work\nStarted: 2026-08-06\n"
        )
        tree = plan_manager.parse_plan(plan)
        assert len(tree.deferred) == 2
        assert tree.deferred[0].reason == "blocked by #55 upstream release"
        assert tree.deferred[1].reason == ""

    def test_reason_survives_roundtrip(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(
            "# Work Plan — test\n\n## Queue\n- [ ] test/repo#1 — Work ← active\n\n"
            "## Deferred\n"
            "- [ ] Schema migration (M / High) [engine] — needs API v2 first\n\n"
            "## Session State\nCurrent: #1 — Work\nStarted: 2026-08-06\n"
        )
        tree = plan_manager.parse_plan(plan)
        plan_manager.rewrite_plan(plan, tree)
        tree2 = plan_manager.parse_plan(plan)
        assert tree2.deferred[0].reason == "needs API v2 first"

    def test_append_with_reason(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(PLAN_NO_DEFERRED)
        plan_manager.append_deferred(
            plan, "Future work", "M", "Med", ["soredium"],
            reason="depends on platform release"
        )
        tree = plan_manager.parse_plan(plan)
        assert tree.deferred[0].reason == "depends on platform release"


class TestPromoteSelected:
    def test_promotes_by_index(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(PLAN_WITH_DEFERRED)
        tree = plan_manager.parse_plan(plan)
        for item in tree.queue:
            item.completed = True
            item.active = False
        plan_manager.rewrite_plan(plan, tree)

        promoted = plan_manager.promote_selected(plan, [0, 2])
        assert len(promoted) == 2
        assert promoted[0].title == "Extract push retry logic"
        assert promoted[1].title == "Fix portal resolutions in blocks-ui"

        tree2 = plan_manager.parse_plan(plan)
        assert len(tree2.deferred) == 1
        assert tree2.deferred[0].title == "Add restore-slot command"

        leaf_titles = [l.title for l in plan_manager.flatten_leaves(tree2)]
        assert "Extract push retry logic" in leaf_titles
        assert "Fix portal resolutions in blocks-ui" in leaf_titles

    def test_promotes_nothing_for_empty_indices(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(PLAN_WITH_DEFERRED)
        promoted = plan_manager.promote_selected(plan, [])
        assert len(promoted) == 0

    def test_out_of_range_indices_ignored(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(PLAN_WITH_DEFERRED)
        promoted = plan_manager.promote_selected(plan, [99])
        assert len(promoted) == 0

    def test_sets_active_on_promoted_item(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(PLAN_WITH_DEFERRED)
        tree = plan_manager.parse_plan(plan)
        for item in tree.queue:
            item.completed = True
            item.active = False
        plan_manager.rewrite_plan(plan, tree)

        plan_manager.promote_selected(plan, [0])
        tree2 = plan_manager.parse_plan(plan)
        active = plan_manager._find_active_leaf(tree2.queue)
        assert active is not None
        assert active.title == "Extract push retry logic"

    def test_issue_numbers_dont_collide(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(
            "# Work Plan — test\n\n## State\nissue-repo: test/repo\n\n## Queue\n"
            "- [x] test/repo#9000 — Previously promoted\n"
            "- [x] test/repo#9001 — Also promoted\n\n"
            "## Deferred\n- [ ] New item (S / Low) [soredium]\n"
        )
        promoted = plan_manager.promote_selected(plan, [0])
        tree = plan_manager.parse_plan(plan)
        new_item = [q for q in tree.queue if q.title == "New item"]
        assert len(new_item) == 1
        assert new_item[0].issue_number >= 9002


class TestStateSectionParsing:
    def test_parse_plan_reads_state_section(self, tmp_path):
        plan_file = tmp_path / ".plan"
        plan_file.write_text(UNIFIED_PLAN)
        tree = plan_manager.parse_plan(plan_file)
        assert tree.state["branch"] == "issue-42-fix-login"
        assert tree.state["state"] == "active"
        assert tree.state["covers"] == "42"
        assert tree.state["project-sha"] == "abc123"
        assert tree.state["design-repo"] == "workspace"

    def test_parse_plan_state_and_queue_coexist(self, tmp_path):
        plan_file = tmp_path / ".plan"
        plan_file.write_text(UNIFIED_PLAN)
        tree = plan_manager.parse_plan(plan_file)
        assert len(tree.queue) == 1
        assert tree.queue[0].issue_number == 42
        assert tree.queue[0].active is True
        assert tree.state["branch"] == "issue-42-fix-login"

    def test_parse_old_plan_without_state_section(self, tmp_path):
        plan_file = tmp_path / ".plan"
        plan_file.write_text(SINGLE_ISSUE_PLAN)
        tree = plan_manager.parse_plan(plan_file)
        assert tree.state == {}
        assert tree.started == "2026-08-04"
        assert len(tree.queue) == 1

    def test_parse_unified_multi_issue(self, tmp_path):
        plan_file = tmp_path / ".plan"
        plan_file.write_text(UNIFIED_PLAN_MULTI)
        tree = plan_manager.parse_plan(plan_file)
        assert tree.state["covers"] == "42,43,44"
        assert len(tree.queue) == 3
        assert tree.queue[0].completed is True
        assert tree.queue[1].active is True


class TestStateSectionWriting:
    def test_build_plan_content_with_state(self):
        state = {"branch": "issue-42", "state": "active", "date": "2026-08-14", "covers": "42"}
        items = [plan_manager.QueueItem(issue_number=42, title="Fix auth", active=True, repo="test/repo")]
        content = plan_manager.build_plan_content("issue-42", items, "2026-08-14", state=state)
        assert "## State" in content
        assert "branch: issue-42" in content
        assert "state: active" in content
        assert "## Queue" in content
        assert "← active" in content

    def test_build_plan_content_without_state(self):
        items = [plan_manager.QueueItem(issue_number=42, title="Fix auth", active=True, repo="test/repo")]
        content = plan_manager.build_plan_content("issue-42", items, "2026-08-14")
        assert "## State" not in content
        assert "## Queue" in content

    def test_roundtrip_preserves_state(self, tmp_path):
        state = {"branch": "issue-42", "state": "active", "date": "2026-08-14", "covers": "42"}
        items = [plan_manager.QueueItem(issue_number=42, title="Fix auth", active=True, repo="test/repo")]
        content = plan_manager.build_plan_content("issue-42", items, "2026-08-14", state=state)
        plan_file = tmp_path / ".plan"
        plan_file.write_text(content)
        tree = plan_manager.parse_plan(plan_file)
        assert tree.state == state
        assert len(tree.queue) == 1
        assert tree.queue[0].active

    def test_rewrite_plan_preserves_state(self, tmp_path):
        plan_file = tmp_path / ".plan"
        plan_file.write_text(UNIFIED_PLAN)
        tree = plan_manager.parse_plan(plan_file)
        plan_manager.rewrite_plan(plan_file, tree)
        tree2 = plan_manager.parse_plan(plan_file)
        assert tree2.state == tree.state
        assert len(tree2.queue) == len(tree.queue)

    def test_rewrite_plan_is_atomic(self, tmp_path):
        plan_file = tmp_path / ".plan"
        plan_file.write_text(UNIFIED_PLAN)
        tree = plan_manager.parse_plan(plan_file)
        plan_manager.rewrite_plan(plan_file, tree)
        assert not (tmp_path / ".plan.tmp").exists()


class TestDetectWithState:
    def test_detect_returns_state_dict(self, tmp_path):
        design = tmp_path / "design"
        design.mkdir()
        plan_file = design / ".plan"
        plan_file.write_text(UNIFIED_PLAN)
        result = plan_manager.detect(tmp_path)
        assert result is not None
        assert result["state"]["branch"] == "issue-42-fix-login"
        assert result["state"]["state"] == "active"
        assert result["active_issue"] == 42

    def test_detect_old_plan_returns_empty_state(self, tmp_path):
        design = tmp_path / "design"
        design.mkdir()
        plan_file = design / ".plan"
        plan_file.write_text(SINGLE_ISSUE_PLAN)
        result = plan_manager.detect(tmp_path)
        assert result is not None
        assert result["state"] == {}
        assert result["active_issue"] == 42


PLAN_WITH_TASKS = """\
# Work Plan — issue-242-merge-slot

## Queue
- [x] test/repo#240 — Previous work
- [ ] test/repo#242 — Merge slot workspace ← active
  - [ ] Batch 1: Detection
    - [ ] Task 1: Add is_workspace_clone
    - [ ] Task 2: Update get_slot_repos
  - [ ] Batch 2: Integration
    - [ ] Task 3: Change merge_slot
- [ ] test/repo#243 — Reconciliation

## Session State
Current: #242 — Merge slot workspace
Started: 2026-08-16
"""


class TestTaskParsing:
    def test_parses_tasks_under_active_issue(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(PLAN_WITH_TASKS)
        tree = plan_manager.parse_plan(plan)
        issue_242 = tree.queue[1]
        assert issue_242.issue_number == 242
        assert len(issue_242.tasks) == 3
        assert issue_242.tasks[0].name == "Add is_workspace_clone"
        assert issue_242.tasks[0].batch == "Detection"
        assert issue_242.tasks[0].done is False
        assert issue_242.tasks[2].name == "Change merge_slot"
        assert issue_242.tasks[2].batch == "Integration"

    def test_completed_issue_has_no_tasks(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(PLAN_WITH_TASKS)
        tree = plan_manager.parse_plan(plan)
        assert tree.queue[0].tasks == []

    def test_future_issue_has_no_tasks(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(PLAN_WITH_TASKS)
        tree = plan_manager.parse_plan(plan)
        assert tree.queue[2].tasks == []

    def test_roundtrip_preserves_tasks(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(PLAN_WITH_TASKS)
        tree = plan_manager.parse_plan(plan)
        plan_manager.rewrite_plan(plan, tree)
        tree2 = plan_manager.parse_plan(plan)
        assert len(tree2.queue[1].tasks) == 3
        assert tree2.queue[1].tasks[0].name == "Add is_workspace_clone"
        assert tree2.queue[1].tasks[2].batch == "Integration"


class TestInjectTasks:
    def test_injects_into_active_issue(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(SINGLE_ISSUE_PLAN)
        plan_manager.inject_tasks(plan, [
            {"batch": "Setup", "name": "Create config"},
            {"batch": "Setup", "name": "Add validation"},
            {"batch": "Wiring", "name": "Connect pipeline"},
        ])
        tree = plan_manager.parse_plan(plan)
        active = tree.queue[0]
        assert len(active.tasks) == 3
        assert active.tasks[0].batch == "Setup"
        assert active.tasks[2].batch == "Wiring"

    def test_replaces_existing_tasks(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(PLAN_WITH_TASKS)
        plan_manager.inject_tasks(plan, [
            {"batch": "New", "name": "Only task"},
        ])
        tree = plan_manager.parse_plan(plan)
        assert len(tree.queue[1].tasks) == 1
        assert tree.queue[1].tasks[0].name == "Only task"


class TestCheckTask:
    def test_marks_task_done(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(PLAN_WITH_TASKS)
        result = plan_manager.check_task(plan, "Add is_workspace_clone")
        assert result["checked"] == "Add is_workspace_clone"
        assert result["batch"] == "Detection"
        assert result["batch_done"] is False
        assert result["all_done"] is False
        tree = plan_manager.parse_plan(plan)
        assert tree.queue[1].tasks[0].done is True
        assert tree.queue[1].tasks[1].done is False

    def test_batch_done_when_all_tasks_in_batch_complete(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(PLAN_WITH_TASKS)
        plan_manager.check_task(plan, "Add is_workspace_clone")
        result = plan_manager.check_task(plan, "Update get_slot_repos")
        assert result["batch_done"] is True
        assert result["all_done"] is False
        assert result["remaining_batches"] == 1

    def test_all_done_when_all_tasks_complete(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(PLAN_WITH_TASKS)
        plan_manager.check_task(plan, "Add is_workspace_clone")
        plan_manager.check_task(plan, "Update get_slot_repos")
        result = plan_manager.check_task(plan, "Change merge_slot")
        assert result["all_done"] is True
        assert result["remaining_batches"] == 0

    def test_error_on_unknown_task(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(PLAN_WITH_TASKS)
        result = plan_manager.check_task(plan, "Nonexistent task")
        assert "error" in result

    def test_error_on_no_active_issue(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text("# Work Plan — test\n\n## Queue\n- [x] test/repo#42 — Done\n")
        result = plan_manager.check_task(plan, "Some task")
        assert "error" in result


class TestAdvanceStripsTasks:
    @patch("plan_manager._emit_issue_events")
    def test_advance_removes_tasks_from_completed_issue(self, mock_emit, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(PLAN_WITH_TASKS)
        plan_manager.advance(plan)
        tree = plan_manager.parse_plan(plan)
        issue_242 = next(i for i in tree.queue if i.issue_number == 242)
        assert issue_242.completed is True
        assert issue_242.tasks == []
        issue_243 = next(i for i in tree.queue if i.issue_number == 243)
        assert issue_243.active is True


class TestTaskWriteFormat:
    def test_writes_batch_and_task_checkboxes(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(SINGLE_ISSUE_PLAN)
        plan_manager.inject_tasks(plan, [
            {"batch": "Foundation", "name": "Parser"},
            {"batch": "Foundation", "name": "Validator"},
            {"batch": "Wiring", "name": "Pipeline"},
        ])
        content = plan.read_text()
        assert "- [ ] Batch 1: Foundation" in content
        assert "- [ ] Task 1: Parser" in content
        assert "- [ ] Task 2: Validator" in content
        assert "- [ ] Batch 2: Wiring" in content
        assert "- [ ] Task 3: Pipeline" in content

    def test_checked_task_shows_x(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(PLAN_WITH_TASKS)
        plan_manager.check_task(plan, "Add is_workspace_clone")
        content = plan.read_text()
        assert "- [x] Task 1: Add is_workspace_clone" in content
        assert "- [ ] Task 2: Update get_slot_repos" in content

    def test_batch_checked_when_all_tasks_done(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(PLAN_WITH_TASKS)
        plan_manager.check_task(plan, "Add is_workspace_clone")
        plan_manager.check_task(plan, "Update get_slot_repos")
        content = plan.read_text()
        assert "- [x] Batch 1: Detection" in content
        assert "- [ ] Batch 2: Integration" in content

    def test_completed_issue_no_tasks_in_output(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(PLAN_WITH_TASKS)
        content = plan.read_text()
        assert "Task" not in content.split("#240")[0]
