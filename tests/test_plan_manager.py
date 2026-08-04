"""Tests for plan_manager — .plan tree parser, writer, flatten, detect."""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "work-slot"))
import plan_manager


SINGLE_ISSUE_PLAN = """\
# Work Plan — issue-42-fix-login

## Queue
- [ ] #42 — Fix login validation ← active

## Session State
Current: #42 — Fix login validation
Started: 2026-08-04
"""

MULTI_ISSUE_PLAN = """\
# Work Plan — issue-42-batch-work

## Queue
- [x] #42 — Fix login validation
- [ ] #50 — Weighted profiles (epic)
  - [x] #108 — Add weight field
  - [ ] #109 — Update scoring ← active
  - [ ] #110 — Migration script
- [ ] #32 — Update API docs

## Session State
Current: #109 — Update scoring
Started: 2026-08-04
"""

NESTED_EPIC_PLAN = """\
# Work Plan — issue-42-nested

## Queue
- [ ] #42 — Fix login ← active
- [ ] #50 — Weighted profiles (epic)
  - [ ] #51 — Add weight field
  - [ ] #52 — Scoring subsystem (epic)
    - [ ] #60 — Score calculator
    - [ ] #61 — Score migration
  - [ ] #53 — API endpoints
- [ ] #32 — Update API docs

## Session State
Current: #42 — Fix login
Started: 2026-08-04
"""

BATCH_PLAN = """\
# Work Plan — issue-50-weighted

## Queue
- [ ] #50 — Weighted profiles (epic)
  ### Batch 1 — Data model ← current
  - [ ] #108 — Add weight field ← active
  - [ ] #109 — Migration script
  ### Batch 2 — Scoring logic
  - [ ] #110 — Update scoring algorithm
  - [ ] #111 — Recalculate existing scores

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
        items = [plan_manager.QueueItem(42, "Fix login", active=True)]
        content = plan_manager.build_plan_content("issue-42-fix-login", items, "2026-08-04")
        assert "# Work Plan — issue-42-fix-login" in content
        assert "- [ ] #42 — Fix login ← active" in content
        assert "Current: #42 — Fix login" in content

    def test_builds_epic_with_children(self):
        children = [
            plan_manager.QueueItem(108, "Add weight field", active=True),
            plan_manager.QueueItem(109, "Update scoring"),
        ]
        items = [plan_manager.QueueItem(50, "Weighted profiles", is_epic=True, children=children)]
        content = plan_manager.build_plan_content("issue-50-weighted", items, "2026-08-04")
        assert "(epic)" in content
        assert "  - [ ] #108 — Add weight field ← active" in content
        assert "  - [ ] #109 — Update scoring" in content

    def test_builds_empty_queue(self):
        content = plan_manager.build_plan_content("improve-scoring", [], "2026-08-04")
        assert "(empty" in content

    def test_builds_nested_epic(self):
        inner = [plan_manager.QueueItem(60, "Calculator"), plan_manager.QueueItem(61, "Migration")]
        children = [
            plan_manager.QueueItem(51, "Weight field", active=True),
            plan_manager.QueueItem(52, "Scoring subsystem", is_epic=True, children=inner),
        ]
        items = [plan_manager.QueueItem(50, "Weighted profiles", is_epic=True, children=children)]
        content = plan_manager.build_plan_content("issue-50-test", items, "2026-08-04")
        assert "    - [ ] #60 — Calculator" in content  # double-indented


class TestAppendToQueue:
    def test_appends_to_existing(self, tmp_path):
        plan_file = tmp_path / ".plan"
        plan_file.write_text(SINGLE_ISSUE_PLAN)
        plan_manager.append_to_queue(plan_file, [plan_manager.QueueItem(99, "New issue")])
        tree = plan_manager.parse_plan(plan_file)
        assert len(tree.queue) == 2
        assert tree.queue[1].issue_number == 99

    def test_appends_to_empty(self, tmp_path):
        plan_file = tmp_path / ".plan"
        plan_file.write_text(EMPTY_PLAN)
        plan_manager.append_to_queue(plan_file, [plan_manager.QueueItem(42, "First issue", active=True)])
        tree = plan_manager.parse_plan(plan_file)
        assert len(tree.queue) == 1
        assert tree.queue[0].active is True

    def test_appends_multiple(self, tmp_path):
        plan_file = tmp_path / ".plan"
        plan_file.write_text(SINGLE_ISSUE_PLAN)
        plan_manager.append_to_queue(plan_file, [
            plan_manager.QueueItem(99, "Issue A"),
            plan_manager.QueueItem(100, "Issue B"),
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
        plan = "# Work Plan — test\n\n## Queue\n- [ ] #42 — A ← active\n- [ ] #43 — B\n\n## Session State\nCurrent: #42 — A\nStarted: 2026-08-04\n"
        plan_file, meta = self._setup(tmp_path, plan)
        result = plan_manager.advance(plan_file, meta)
        assert result.completed == 42
        assert result.next_issue == 43
        assert result.epic_complete is False
        tree = plan_manager.parse_plan(plan_file)
        assert tree.queue[0].completed is True
        assert tree.queue[1].active is True
        assert "42" in meta.read_text()

    def test_epic_child_advance(self, tmp_path):
        plan_file, meta = self._setup(tmp_path, MULTI_ISSUE_PLAN, covers="42")
        result = plan_manager.advance(plan_file, meta)
        assert result.completed == 109
        assert result.next_issue == 110
        assert result.batch_complete is False

    def test_epic_last_child_completes_parent(self, tmp_path):
        plan = "# Work Plan — test\n\n## Queue\n- [ ] #50 — Epic (epic)\n  - [x] #108 — A\n  - [ ] #109 — B ← active\n- [ ] #32 — C\n\n## Session State\nCurrent: #109 — B\nStarted: 2026-08-04\n"
        plan_file, meta = self._setup(tmp_path, plan)
        result = plan_manager.advance(plan_file, meta)
        assert result.completed == 109
        assert result.next_issue == 32
        tree = plan_manager.parse_plan(plan_file)
        assert tree.queue[0].completed is True

    def test_nested_epic_completes(self, tmp_path):
        plan = "# Work Plan — test\n\n## Queue\n- [ ] #50 — Epic (epic)\n  - [ ] #52 — Nested (epic)\n    - [x] #60 — A\n    - [ ] #61 — B ← active\n  - [ ] #53 — C\n\n## Session State\nCurrent: #61 — B\nStarted: 2026-08-04\n"
        plan_file, meta = self._setup(tmp_path, plan)
        result = plan_manager.advance(plan_file, meta)
        assert result.completed == 61
        assert result.next_issue == 53
        tree = plan_manager.parse_plan(plan_file)
        assert tree.queue[0].children[0].completed is True

    def test_queue_exhausted(self, tmp_path):
        plan = "# Work Plan — test\n\n## Queue\n- [x] #42 — A\n- [ ] #43 — B ← active\n\n## Session State\nCurrent: #43 — B\nStarted: 2026-08-04\n"
        plan_file, meta = self._setup(tmp_path, plan)
        result = plan_manager.advance(plan_file, meta)
        assert result.completed == 43
        assert result.next_issue is None
        assert result.epic_complete is True

    def test_batch_boundary_safe_exit(self, tmp_path):
        plan = "# Work Plan — test\n\n## Queue\n- [ ] #50 — Epic (epic)\n  ### Batch 1 — Model\n  - [x] #108 — A\n  - [ ] #109 — B ← active\n  ### Batch 2 — Logic\n  - [ ] #110 — C\n\n## Session State\nCurrent: #109 — B\nStarted: 2026-08-04\n"
        plan_file, meta = self._setup(tmp_path, plan)
        result = plan_manager.advance(plan_file, meta)
        assert result.batch_complete is True
        assert result.safe_exit is True
        assert result.next_issue == 110

    def test_covers_updated(self, tmp_path):
        plan = "# Work Plan — test\n\n## Queue\n- [ ] #42 — A ← active\n- [ ] #43 — B\n\n## Session State\nCurrent: #42 — A\nStarted: 2026-08-04\n"
        plan_file, meta = self._setup(tmp_path, plan)
        plan_manager.advance(plan_file, meta)
        covers_line = [l for l in meta.read_text().splitlines() if l.startswith("covers:")][0]
        assert "42" in covers_line

    def test_covers_deduplication(self, tmp_path):
        plan = "# Work Plan — test\n\n## Queue\n- [ ] #42 — A ← active\n- [ ] #43 — B\n\n## Session State\nCurrent: #42 — A\nStarted: 2026-08-04\n"
        plan_file, meta = self._setup(tmp_path, plan, covers="42")
        plan_manager.advance(plan_file, meta)
        covers_line = [l for l in meta.read_text().splitlines() if l.startswith("covers:")][0]
        nums = [n.strip() for n in covers_line.split(":")[1].strip().split(",") if n.strip()]
        assert len(nums) == len(set(nums))


class TestAdvanceIssueDispatch:
    def test_dispatches_to_plan(self, tmp_path):
        design = tmp_path / "design"
        design.mkdir()
        plan_file = design / ".plan"
        plan_file.write_text("# Work Plan — test\n\n## Queue\n- [ ] #42 — A ← active\n- [ ] #43 — B\n\n## Session State\nCurrent: #42 — A\nStarted: 2026-08-04\n")
        meta = design / ".meta"
        meta.write_text("branch: test\nissue: 42\ncovers: 42\n")
        result = plan_manager.advance_issue(plan_file, None, meta)
        assert result.completed == 42

    def test_raises_when_no_files(self, tmp_path):
        with pytest.raises(plan_manager.NoQueueFile):
            plan_manager.advance_issue(tmp_path / "nope.plan", tmp_path / "nope.epic", tmp_path / ".meta")


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
