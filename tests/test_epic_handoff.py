#!/usr/bin/env python3
"""Tests for epic_handoff — epic context propagation to HANDOFF.md (#487)."""
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "work-end"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "work-slot"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "project"))


# ---------------------------------------------------------------------------
# detect_parent_epic — from .plan
# ---------------------------------------------------------------------------

class TestDetectParentEpicFromPlan:
    """Find parent epic via .plan queue structure."""

    def test_finds_parent_when_issue_is_child(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(
            "# Work Plan — polish\n"
            "## Queue\n"
            "- [ ] casehubio/platform#702 — YAML playbook polish (epic)\n"
            "  - [x] casehubio/platform#698 — Enforce combined-key syntax ← active\n"
            "  - [ ] casehubio/platform#703 — Variable declarations\n"
            "  - [ ] casehubio/platform#699 — Type-safe expressions\n"
        )
        from epic_handoff import detect_parent_epic_from_plan
        result = detect_parent_epic_from_plan(698, plan)
        assert result is not None
        assert result.number == 702

    def test_returns_none_when_no_epic_parent(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(
            "# Work Plan — fixes\n"
            "## Queue\n"
            "- [x] org/repo#100 — Fix widget ← active\n"
            "- [ ] org/repo#101 — Fix button\n"
        )
        from epic_handoff import detect_parent_epic_from_plan
        result = detect_parent_epic_from_plan(100, plan)
        assert result is None

    def test_returns_none_when_issue_not_in_plan(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(
            "# Work Plan — work\n"
            "## Queue\n"
            "- [ ] org/repo#702 — Epic (epic)\n"
            "  - [ ] org/repo#698 — Child\n"
        )
        from epic_handoff import detect_parent_epic_from_plan
        result = detect_parent_epic_from_plan(999, plan)
        assert result is None

    def test_returns_none_when_plan_missing(self, tmp_path):
        from epic_handoff import detect_parent_epic_from_plan
        result = detect_parent_epic_from_plan(100, tmp_path / ".plan")
        assert result is None


# ---------------------------------------------------------------------------
# detect_parent_epic — from GitHub issue body
# ---------------------------------------------------------------------------

class TestDetectParentEpicFromGitHub:
    """Find parent epic by parsing the GitHub issue body."""

    def test_finds_parent_from_body_reference(self):
        body = (
            "## Problem\nSome problem.\n\n"
            "## Context\n"
            "- #702 — YAML language refinement epic (parent)\n"
            "- Depends on #429\n"
        )
        from epic_handoff import detect_parent_epic_from_body
        result = detect_parent_epic_from_body(body)
        assert result == 702

    def test_finds_parent_from_parent_epic_field(self):
        body = "## Overview\nParent epic: #500\nSome description."
        from epic_handoff import detect_parent_epic_from_body
        result = detect_parent_epic_from_body(body)
        assert result == 500

    def test_finds_parent_from_part_of(self):
        body = "## Overview\nPart of #300\nSome description."
        from epic_handoff import detect_parent_epic_from_body
        result = detect_parent_epic_from_body(body)
        assert result == 300

    def test_returns_none_when_no_epic_reference(self):
        body = "## Problem\nJust a regular issue.\n## Solution\nFix it."
        from epic_handoff import detect_parent_epic_from_body
        result = detect_parent_epic_from_body(body)
        assert result is None

    def test_ignores_non_parent_issue_refs(self):
        body = (
            "## Problem\nRelated to #100.\n"
            "Depends on #200.\nBlocks #300.\n"
        )
        from epic_handoff import detect_parent_epic_from_body
        result = detect_parent_epic_from_body(body)
        assert result is None


# ---------------------------------------------------------------------------
# get_epic_status — parse epic body for child statuses
# ---------------------------------------------------------------------------

class TestGetEpicStatus:
    """Parse an epic issue body for child issue statuses."""

    def test_parses_checked_and_unchecked_children(self):
        body = (
            "## Child Issues\n"
            "- [x] #698 — Enforce syntax (S/Low) — ✅ landed\n"
            "- [x] #703 — Variable declarations (L/Med) — ✅ landed\n"
            "- [ ] #699 — Type-safe expressions (XL/High)\n"
            "- [ ] #700 — Annotations (XL/High)\n"
        )
        from epic_handoff import parse_epic_children
        children = parse_epic_children(body)
        assert len(children) == 4
        done = [c for c in children if c["done"]]
        assert len(done) == 2
        assert done[0]["number"] == 698
        open_items = [c for c in children if not c["done"]]
        assert len(open_items) == 2
        assert open_items[0]["number"] == 699

    def test_handles_batched_children(self):
        body = (
            "## Child Issues\n\n"
            "### Syntax & Foundations\n"
            "- [x] #698 — Enforce syntax\n"
            "### Type Safety\n"
            "- [ ] #699 — Type-safe expressions\n"
        )
        from epic_handoff import parse_epic_children
        children = parse_epic_children(body)
        assert len(children) == 2

    def test_returns_empty_for_no_children(self):
        body = "## Overview\nJust a description."
        from epic_handoff import parse_epic_children
        children = parse_epic_children(body)
        assert children == []


# ---------------------------------------------------------------------------
# recommend_next — pick the next issue from epic children
# ---------------------------------------------------------------------------

class TestRecommendNext:
    """Recommend the next issue from open epic children."""

    def test_recommends_first_open_issue(self):
        children = [
            {"number": 698, "title": "Syntax", "done": True},
            {"number": 703, "title": "Variables", "done": True},
            {"number": 699, "title": "Type-safe expressions", "done": False},
            {"number": 700, "title": "Annotations", "done": False},
        ]
        from epic_handoff import recommend_next
        result = recommend_next(children)
        assert result is not None
        assert result["number"] == 699

    def test_returns_none_when_all_done(self):
        children = [
            {"number": 698, "title": "Syntax", "done": True},
            {"number": 703, "title": "Variables", "done": True},
        ]
        from epic_handoff import recommend_next
        result = recommend_next(children)
        assert result is None

    def test_returns_none_for_empty_children(self):
        from epic_handoff import recommend_next
        assert recommend_next([]) is None


# ---------------------------------------------------------------------------
# build_epic_handoff — format the HANDOFF.md content
# ---------------------------------------------------------------------------

class TestBuildEpicHandoff:
    """Build structured HANDOFF.md content with epic context."""

    def test_includes_session_summary(self):
        children = [
            {"number": 698, "title": "Syntax", "done": True},
            {"number": 699, "title": "Expressions", "done": False},
        ]
        from epic_handoff import build_epic_handoff
        content = build_epic_handoff(
            completed_issue=698,
            completed_title="Enforce combined-key syntax",
            epic_number=702,
            epic_title="YAML playbook polish",
            children=children,
            repo="casehubio/platform",
            branch="issue-698-syntax",
        )
        assert "698" in content
        assert "Enforce combined-key syntax" in content
        assert "issue-698-syntax" in content

    def test_includes_epic_status_table(self):
        children = [
            {"number": 698, "title": "Syntax", "done": True},
            {"number": 703, "title": "Variables", "done": True},
            {"number": 699, "title": "Expressions", "done": False},
        ]
        from epic_handoff import build_epic_handoff
        content = build_epic_handoff(
            completed_issue=698,
            completed_title="Syntax",
            epic_number=702,
            epic_title="Epic title",
            children=children,
            repo="org/repo",
            branch="issue-698-test",
        )
        assert "702" in content
        assert "Epic title" in content
        assert "Done" in content or "✅" in content
        assert "Open" in content or "🔲" in content
        assert "699" in content
        assert "2/3" in content or "2 of 3" in content

    def test_includes_recommended_next(self):
        children = [
            {"number": 698, "title": "Syntax", "done": True},
            {"number": 699, "title": "Expressions", "done": False},
        ]
        from epic_handoff import build_epic_handoff
        content = build_epic_handoff(
            completed_issue=698,
            completed_title="Syntax",
            epic_number=702,
            epic_title="Epic",
            children=children,
            repo="org/repo",
            branch="issue-698-test",
        )
        assert "699" in content
        assert "Expressions" in content
        assert "Next" in content or "next" in content

    def test_no_next_when_epic_complete(self):
        children = [
            {"number": 698, "title": "Syntax", "done": True},
            {"number": 703, "title": "Variables", "done": True},
        ]
        from epic_handoff import build_epic_handoff
        content = build_epic_handoff(
            completed_issue=698,
            completed_title="Syntax",
            epic_number=702,
            epic_title="Epic",
            children=children,
            repo="org/repo",
            branch="issue-698-test",
        )
        assert "complete" in content.lower() or "all done" in content.lower() or "✅" in content


# ---------------------------------------------------------------------------
# write_epic_handoff — file I/O
# ---------------------------------------------------------------------------

class TestWriteEpicHandoff:
    """Write HANDOFF.md to workspace."""

    def test_writes_handoff_file(self, tmp_path):
        from epic_handoff import write_epic_handoff
        write_epic_handoff(
            workspace=tmp_path,
            completed_issue=698,
            completed_title="Syntax",
            epic_number=702,
            epic_title="Epic",
            children=[
                {"number": 698, "title": "Syntax", "done": True},
                {"number": 699, "title": "Expressions", "done": False},
            ],
            repo="org/repo",
            branch="issue-698-test",
        )
        handoff = tmp_path / "HANDOFF.md"
        assert handoff.exists()
        content = handoff.read_text()
        assert "698" in content
        assert "702" in content

    def test_overwrites_stale_handoff(self, tmp_path):
        (tmp_path / "HANDOFF.md").write_text("# Stale content from last session\n")
        from epic_handoff import write_epic_handoff
        write_epic_handoff(
            workspace=tmp_path,
            completed_issue=698,
            completed_title="Syntax",
            epic_number=702,
            epic_title="Epic",
            children=[{"number": 698, "title": "Syntax", "done": True}],
            repo="org/repo",
            branch="issue-698-test",
        )
        content = (tmp_path / "HANDOFF.md").read_text()
        assert "Stale content" not in content
        assert "698" in content


# ---------------------------------------------------------------------------
# run_epic_handoff — orchestrator entry point
# ---------------------------------------------------------------------------

class TestRunEpicHandoff:
    """End-to-end: detect epic, query, write HANDOFF."""

    def test_writes_handoff_when_plan_has_epic(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(
            "# Work Plan — polish\n"
            "## Queue\n"
            "- [ ] casehubio/platform#702 — YAML playbook polish (epic)\n"
            "  - [x] casehubio/platform#698 — Enforce syntax ← active\n"
            "  - [ ] casehubio/platform#699 — Type-safe expressions\n"
        )
        epic_body = (
            "## Child Issues\n"
            "- [x] #698 — Enforce syntax\n"
            "- [ ] #699 — Type-safe expressions\n"
        )

        def mock_gh(cmd, **kwargs):
            class R:
                returncode = 0
                stdout = json.dumps({"title": "Epic: YAML polish", "body": epic_body})
                stderr = ""
            return R()

        with patch("epic_handoff.subprocess.run", side_effect=mock_gh):
            from epic_handoff import run_epic_handoff
            result = run_epic_handoff(
                workspace=tmp_path,
                covers="698",
                issue_repo="casehubio/platform",
                plan_path=plan,
                branch="issue-698-syntax",
            )

        assert result.get("EPIC_HANDOFF") == "written"
        handoff = tmp_path / "HANDOFF.md"
        assert handoff.exists()
        content = handoff.read_text()
        assert "702" in content
        assert "699" in content

    def test_returns_skipped_when_no_epic(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(
            "# Work Plan — fixes\n"
            "## Queue\n"
            "- [x] org/repo#100 — Fix widget ← active\n"
            "- [ ] org/repo#101 — Fix button\n"
        )

        def mock_gh(cmd, **kwargs):
            class R:
                returncode = 0
                stdout = json.dumps({"title": "Fix widget", "body": "Just a fix."})
                stderr = ""
            return R()

        with patch("epic_handoff.subprocess.run", side_effect=mock_gh):
            from epic_handoff import run_epic_handoff
            result = run_epic_handoff(
                workspace=tmp_path,
                covers="100",
                issue_repo="org/repo",
                plan_path=plan,
                branch="issue-100-fix",
            )

        assert result.get("EPIC_HANDOFF") == "skipped"
        assert not (tmp_path / "HANDOFF.md").exists()

    def test_returns_skipped_when_no_covers(self, tmp_path):
        from epic_handoff import run_epic_handoff
        result = run_epic_handoff(
            workspace=tmp_path,
            covers="",
            issue_repo="org/repo",
            plan_path=None,
            branch="issue-100-fix",
        )
        assert result.get("EPIC_HANDOFF") == "skipped"

    def test_falls_back_to_github_when_no_plan(self, tmp_path):
        child_body = "## Context\n- #702 — YAML epic (parent)\n"
        epic_body = (
            "## Child Issues\n"
            "- [x] #698 — Syntax\n"
            "- [ ] #699 — Expressions\n"
        )

        call_count = {"n": 0}
        def mock_gh(cmd, **kwargs):
            call_count["n"] += 1
            class R:
                returncode = 0
                stderr = ""
            r = R()
            if call_count["n"] == 1:
                r.stdout = json.dumps({"title": "Syntax fix", "body": child_body})
            else:
                r.stdout = json.dumps({"title": "Epic: YAML polish", "body": epic_body})
            return r

        with patch("epic_handoff.subprocess.run", side_effect=mock_gh):
            from epic_handoff import run_epic_handoff
            result = run_epic_handoff(
                workspace=tmp_path,
                covers="698",
                issue_repo="casehubio/platform",
                plan_path=None,
                branch="issue-698-syntax",
            )

        assert result.get("EPIC_HANDOFF") == "written"
        content = (tmp_path / "HANDOFF.md").read_text()
        assert "702" in content


# ---------------------------------------------------------------------------
# Orchestrator wiring
# ---------------------------------------------------------------------------

class TestOrchestratorWiring:
    """Verify epic_handoff is wired into the work-end pipeline."""

    def test_epic_handoff_step_exists(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "work-end"))
        from work_end_orchestrator import STEPS
        step_names = [s.name for s in STEPS]
        assert "epic_handoff" in step_names

    def test_epic_handoff_after_close_issues(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "work-end"))
        from work_end_orchestrator import STEPS
        step_names = [s.name for s in STEPS]
        close_idx = step_names.index("close_issues")
        handoff_idx = step_names.index("epic_handoff")
        assert handoff_idx > close_idx

    def test_epic_handoff_requires_close_issues(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "work-end"))
        from work_end_orchestrator import STEPS
        step = next(s for s in STEPS if s.name == "epic_handoff")
        assert "close_issues" in step.requires

    def test_epic_handoff_is_mechanical(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "work-end"))
        from work_end_orchestrator import STEPS
        from judgment import StepType
        step = next(s for s in STEPS if s.name == "epic_handoff")
        assert step.step_type == StepType.MECHANICAL
