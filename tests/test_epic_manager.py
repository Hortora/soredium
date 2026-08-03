"""Tests for work-slot/epic_manager.py"""

import sys
from pathlib import Path

import pytest

skill_dir = Path(__file__).parent.parent / "work-slot"
sys.path.insert(0, str(skill_dir))

import epic_manager


SAMPLE_EPIC_SLOT_MD = """\
# Slot 38 — issue-50-weighted-profiles

## Issue
casehubio/engine#50
Covers: 108
Type: epic
Safe exit: after any completed batch

## What to do
Epic #50 — Weighted Profiles. Working through batched child issues.
Current: Batch 1 — Vocabulary and docs (S+S)

## Batch Plan

### Batch 1 — Vocabulary and docs (S+S)
- [x] #108 — Rename disposition
- [ ] #109 — Update terminology ← active

### Batch 2 — Weighted profiles API (M+M)
- [ ] #111 — Add weight parameter
- [ ] #112 — Dominant-auxiliary scoring

## Session State
Current batch: 1
Current issue: #109 — Update terminology
Last wrap: 2026-07-28, session started batch 1

## Repos
- engine (primary)

## Created
2026-07-28, branch: issue-50-weighted-profiles
"""


class TestParseBatchPlan:
    def test_parses_epic_slot(self, tmp_path):
        (tmp_path / ".slot").write_text(SAMPLE_EPIC_SLOT_MD)
        result = epic_manager.parse_batch_plan(tmp_path / ".slot")
        assert result["is_epic"] is True
        assert result["epic_number"] == "50"
        assert result["epic_repo"] == "casehubio/engine"
        assert len(result["batches"]) == 2
        assert result["current_batch"] == 1
        assert result["current_issue"] == 109
        assert result["completed"] == [108]

    def test_batch_structure(self, tmp_path):
        (tmp_path / ".slot").write_text(SAMPLE_EPIC_SLOT_MD)
        result = epic_manager.parse_batch_plan(tmp_path / ".slot")
        b1 = result["batches"][0]
        assert b1["name"] == "Vocabulary and docs (S+S)"
        assert b1["number"] == 1
        assert len(b1["issues"]) == 2
        assert b1["issues"][0] == {"number": 108, "title": "Rename disposition", "done": True}
        assert b1["issues"][1] == {"number": 109, "title": "Update terminology", "done": False}

    def test_non_epic_slot(self, tmp_path):
        (tmp_path / ".slot").write_text(
            "# Slot 1 — issue-42-spi\n\n## Issue\nrepo#42\nCovers: 42\n"
        )
        result = epic_manager.parse_batch_plan(tmp_path / ".slot")
        assert result["is_epic"] is False

    def test_missing_file(self, tmp_path):
        result = epic_manager.parse_batch_plan(tmp_path / ".slot")
        assert result["is_epic"] is False

    def test_all_done_in_batch(self, tmp_path):
        md = SAMPLE_EPIC_SLOT_MD.replace(
            "- [ ] #109 — Update terminology ← active",
            "- [x] #109 — Update terminology",
        ).replace(
            "### Batch 2 — Weighted profiles API (M+M)",
            "### Batch 2 — Weighted profiles API (M+M) ← current",
        ).replace(
            "- [ ] #111 — Add weight parameter",
            "- [ ] #111 — Add weight parameter ← active",
        ).replace(
            "Current batch: 1",
            "Current batch: 2",
        ).replace(
            "Current issue: #109 — Update terminology",
            "Current issue: #111 — Add weight parameter",
        )
        (tmp_path / ".slot").write_text(md)
        result = epic_manager.parse_batch_plan(tmp_path / ".slot")
        assert result["current_batch"] == 2
        assert result["current_issue"] == 111
        assert set(result["completed"]) == {108, 109}

    def test_empty_batch_plan(self, tmp_path):
        md = """\
# Slot 1 — issue-50-test

## Issue
repo#50
Covers:
Type: epic

## What to do
Test

## Batch Plan

## Repos
- engine
"""
        (tmp_path / ".slot").write_text(md)
        result = epic_manager.parse_batch_plan(tmp_path / ".slot")
        assert result["is_epic"] is True
        assert result["batches"] == []
        assert result["current_issue"] == 0


class TestAdvance:
    def _setup_slot(self, tmp_path, slot_md, covers=""):
        (tmp_path / ".slot").write_text(slot_md)
        design = tmp_path / "work" / "engine" / "design"
        design.mkdir(parents=True)
        (design / ".meta").write_text(
            "branch: issue-50-weighted-profiles\n"
            "issue: 50\n"
            "issue-repo: casehubio/engine\n"
            f"covers: {covers}\n"
        )
        return design / ".meta"

    def test_advances_to_next_issue_in_batch(self, tmp_path):
        meta = self._setup_slot(tmp_path, SAMPLE_EPIC_SLOT_MD, covers="108")
        result = epic_manager.advance(tmp_path / ".slot", meta_path=meta)
        assert result["completed"] == 109
        assert result["next_issue"] == 111
        assert result["batch_complete"] is True
        assert result["epic_complete"] is False
        assert result["safe_exit"] is True

    def test_advances_within_batch(self, tmp_path):
        md = SAMPLE_EPIC_SLOT_MD.replace(
            "- [x] #108 — Rename disposition\n- [ ] #109 — Update terminology ← active",
            "- [ ] #108 — Rename disposition ← active\n- [ ] #109 — Update terminology",
        ).replace("Covers: 108", "Covers:").replace(
            "Current batch: 1\nCurrent issue: #109 — Update terminology",
            "Current batch: 1\nCurrent issue: #108 — Rename disposition",
        )
        meta = self._setup_slot(tmp_path, md)
        result = epic_manager.advance(tmp_path / ".slot", meta_path=meta)
        assert result["completed"] == 108
        assert result["next_issue"] == 109
        assert result["batch_complete"] is False
        assert result["safe_exit"] is False

    def test_updates_slot_md_checkboxes(self, tmp_path):
        meta = self._setup_slot(tmp_path, SAMPLE_EPIC_SLOT_MD, covers="108")
        epic_manager.advance(tmp_path / ".slot", meta_path=meta)
        updated = (tmp_path / ".slot").read_text()
        assert "- [x] #109 — Update terminology" in updated
        assert "- [ ] #111 — Add weight parameter ← active" in updated

    def test_updates_slot_md_current_markers(self, tmp_path):
        meta = self._setup_slot(tmp_path, SAMPLE_EPIC_SLOT_MD, covers="108")
        epic_manager.advance(tmp_path / ".slot", meta_path=meta)
        updated = (tmp_path / ".slot").read_text()
        assert "### Batch 2 — Weighted profiles API (M+M) ← current" in updated
        # Batch 1 should no longer have ← current
        for line in updated.splitlines():
            if "Batch 1" in line and "###" in line:
                assert "← current" not in line

    def test_updates_meta_covers(self, tmp_path):
        meta = self._setup_slot(tmp_path, SAMPLE_EPIC_SLOT_MD, covers="108")
        epic_manager.advance(tmp_path / ".slot", meta_path=meta)
        content = meta.read_text()
        assert "covers: 108,109" in content

    def test_updates_slot_md_covers(self, tmp_path):
        meta = self._setup_slot(tmp_path, SAMPLE_EPIC_SLOT_MD, covers="108")
        epic_manager.advance(tmp_path / ".slot", meta_path=meta)
        updated = (tmp_path / ".slot").read_text()
        assert "Covers: 108,109" in updated

    def test_updates_session_state(self, tmp_path):
        meta = self._setup_slot(tmp_path, SAMPLE_EPIC_SLOT_MD, covers="108")
        epic_manager.advance(tmp_path / ".slot", meta_path=meta)
        updated = (tmp_path / ".slot").read_text()
        assert "Current batch: 2" in updated
        assert "Current issue: #111 — Add weight parameter" in updated

    def test_epic_complete_on_last_issue(self, tmp_path):
        md = """\
# Slot 1 — issue-50-test

## Issue
repo#50
Covers: 108
Type: epic
Safe exit: after any completed batch

## What to do
Test

## Batch Plan

### Batch 1 — Final (S) ← current
- [x] #108 — First
- [ ] #109 — Last ← active

## Session State
Current batch: 1
Current issue: #109 — Last

## Repos
- engine (primary)

## Created
2026-07-28, branch: issue-50-test
"""
        meta = self._setup_slot(tmp_path, md, covers="108")
        result = epic_manager.advance(tmp_path / ".slot", meta_path=meta)
        assert result["epic_complete"] is True
        assert result["batch_complete"] is True
        assert result["next_issue"] is None

    def test_meta_covers_deduplicates(self, tmp_path):
        meta = self._setup_slot(tmp_path, SAMPLE_EPIC_SLOT_MD, covers="108,109")
        epic_manager.advance(tmp_path / ".slot", meta_path=meta)
        content = meta.read_text()
        assert content.count("109") == 1

    def test_idempotent_slot_md_update(self, tmp_path):
        meta = self._setup_slot(tmp_path, SAMPLE_EPIC_SLOT_MD, covers="108")
        epic_manager.advance(tmp_path / ".slot", meta_path=meta)
        first_state = (tmp_path / ".slot").read_text()
        # Advancing again should not break — current is now #111
        result2 = epic_manager.advance(tmp_path / ".slot", meta_path=meta)
        assert result2["completed"] == 111

    def test_no_meta_path_still_updates_slot(self, tmp_path):
        (tmp_path / ".slot").write_text(SAMPLE_EPIC_SLOT_MD)
        result = epic_manager.advance(tmp_path / ".slot", meta_path=None)
        assert result["completed"] == 109
        updated = (tmp_path / ".slot").read_text()
        assert "- [x] #109 — Update terminology" in updated

    def test_what_to_do_section_updated(self, tmp_path):
        meta = self._setup_slot(tmp_path, SAMPLE_EPIC_SLOT_MD, covers="108")
        epic_manager.advance(tmp_path / ".slot", meta_path=meta)
        updated = (tmp_path / ".slot").read_text()
        assert "Batch 2" in updated.split("## What to do")[1].split("##")[0]


class TestStatus:
    def test_returns_progress(self, tmp_path):
        (tmp_path / ".slot").write_text(SAMPLE_EPIC_SLOT_MD)
        result = epic_manager.status(tmp_path / ".slot")
        assert result["total_issues"] == 4
        assert result["completed_count"] == 1
        assert result["total_batches"] == 2
        assert result["completed_batches"] == 0
        assert result["current_batch"] == 1
        assert result["current_issue"] == 109
        assert result["safe_exit"] is False

    def test_safe_exit_after_batch_complete(self, tmp_path):
        md = SAMPLE_EPIC_SLOT_MD.replace(
            "- [ ] #109 — Update terminology ← active",
            "- [x] #109 — Update terminology",
        ).replace(
            "### Batch 2 — Weighted profiles API (M+M)",
            "### Batch 2 — Weighted profiles API (M+M) ← current",
        ).replace(
            "- [ ] #111 — Add weight parameter",
            "- [ ] #111 — Add weight parameter ← active",
        ).replace(
            "Current batch: 1\nCurrent issue: #109 — Update terminology",
            "Current batch: 2\nCurrent issue: #111 — Add weight parameter",
        )
        (tmp_path / ".slot").write_text(md)
        result = epic_manager.status(tmp_path / ".slot")
        assert result["completed_batches"] == 1
        assert result["safe_exit"] is True

    def test_non_epic(self, tmp_path):
        (tmp_path / ".slot").write_text("# Slot 1\n\n## Issue\nrepo#42\n")
        result = epic_manager.status(tmp_path / ".slot")
        assert result.get("is_epic") is False

    def test_all_complete(self, tmp_path):
        md = """\
# Slot 1 — issue-50-test

## Issue
repo#50
Covers: 108,109
Type: epic

## What to do
All done

## Batch Plan

### Batch 1 — Done (S)
- [x] #108 — First
- [x] #109 — Second

## Session State
Current batch: 0
Current issue:

## Repos
- engine
"""
        (tmp_path / ".slot").write_text(md)
        result = epic_manager.status(tmp_path / ".slot")
        assert result["completed_count"] == 2
        assert result["completed_batches"] == 1
        assert result["current_issue"] == 0


class TestWriteEpicSlotMd:
    def test_writes_and_parses_roundtrip(self, tmp_path):
        batches = [
            {"number": 1, "name": "Vocabulary (S+S)", "issues": [
                {"number": 108, "title": "Rename X"},
                {"number": 109, "title": "Update docs"},
            ]},
            {"number": 2, "name": "API change (M)", "issues": [
                {"number": 111, "title": "Add weights"},
            ]},
        ]
        epic_manager.write_epic_slot_md(
            tmp_path, 1, ["engine"], "issue-50-profiles",
            "50", "casehubio/engine", batches, "Weighted profiles",
        )
        assert (tmp_path / ".slot").exists()
        plan = epic_manager.parse_batch_plan(tmp_path / ".slot")
        assert plan["is_epic"] is True
        assert plan["epic_number"] == "50"
        assert plan["epic_repo"] == "casehubio/engine"
        assert len(plan["batches"]) == 2
        assert plan["current_issue"] == 108
        assert plan["completed"] == []

    def test_first_issue_marked_active(self, tmp_path):
        batches = [
            {"number": 1, "name": "Batch (S)", "issues": [
                {"number": 42, "title": "First issue"},
            ]},
        ]
        epic_manager.write_epic_slot_md(
            tmp_path, 1, ["engine"], "issue-50-test",
            "50", "repo", batches, "Test",
        )
        content = (tmp_path / ".slot").read_text()
        assert "#42 — First issue ← active" in content
        assert "Batch 1 — Batch (S) ← current" in content

    def test_backward_compat_with_parse_slot_md(self, tmp_path):
        """Verify the output can be parsed by slot_manager.parse_slot_md."""
        import slot_manager
        batches = [
            {"number": 1, "name": "Work (M)", "issues": [
                {"number": 42, "title": "Do stuff"},
            ]},
        ]
        epic_manager.write_epic_slot_md(
            tmp_path, 5, ["engine", "iot"], "issue-50-profiles",
            "50", "casehubio/engine", batches, "Weighted profiles",
        )
        md = slot_manager.parse_slot_md(tmp_path)
        assert md["issue"] == "50"
        assert md["issue_repo"] == "casehubio/engine"
        assert md["repos"] == ["engine", "iot"]
        assert "issue-50-profiles" in md["branch"]

    def test_multi_repo(self, tmp_path):
        batches = [{"number": 1, "name": "Work (S)", "issues": [
            {"number": 42, "title": "Test"},
        ]}]
        epic_manager.write_epic_slot_md(
            tmp_path, 1, ["engine", "iot"], "issue-50-test",
            "50", "repo", batches, "Test",
        )
        content = (tmp_path / ".slot").read_text()
        assert "engine (primary)" in content
        assert "- iot" in content


class TestAdvanceReturnsEpicInfo:
    def _setup_slot(self, tmp_path, slot_md, covers=""):
        (tmp_path / ".slot").write_text(slot_md)
        design = tmp_path / "work" / "engine" / "design"
        design.mkdir(parents=True)
        (design / ".meta").write_text(
            "branch: issue-50-weighted-profiles\n"
            "issue: 50\n"
            "issue-repo: casehubio/engine\n"
            f"covers: {covers}\n"
        )
        return design / ".meta"

    def test_advance_returns_epic_number(self, tmp_path):
        meta = self._setup_slot(tmp_path, SAMPLE_EPIC_SLOT_MD, covers="108")
        result = epic_manager.advance(tmp_path / ".slot", meta_path=meta)
        assert result["epic_number"] == "50"
        assert result["epic_repo"] == "casehubio/engine"

    def test_advance_returns_epic_info_on_completion(self, tmp_path):
        md = """\
# Slot 1 — issue-50-test

## Issue
Hortora/soredium#100
Covers: 108
Type: epic
Safe exit: after any completed batch

## Batch Plan

### Batch 1 — Final (S) ← current
- [x] #108 — First
- [ ] #109 — Last ← active

## Session State
Current batch: 1
Current issue: #109 — Last
"""
        meta = self._setup_slot(tmp_path, md, covers="108")
        result = epic_manager.advance(tmp_path / ".slot", meta_path=meta)
        assert result["epic_complete"] is True
        assert result["epic_number"] == "100"
        assert result["epic_repo"] == "Hortora/soredium"


class TestWriteEpic:
    def test_write_epic_creates_file(self, tmp_path):
        batches = [{"number": 1, "name": "Core",
                    "issues": [{"number": 10, "title": "First"}]}]
        epic_manager.write_epic(tmp_path, issue="100", slug="my-epic",
                                issue_repo="Hortora/soredium",
                                batches=batches, context="Test epic")
        epic_path = tmp_path / "design" / ".epic"
        assert epic_path.exists()
        content = epic_path.read_text()
        assert "# Epic #100 — my-epic" in content
        assert "## Repos" not in content
        assert "Type: epic" in content
        assert "← active" in content

    def test_write_epic_roundtrip(self, tmp_path):
        batches = [{"number": 1, "name": "Core",
                    "issues": [{"number": 10, "title": "First"},
                               {"number": 11, "title": "Second"}]},
                   {"number": 2, "name": "Polish",
                    "issues": [{"number": 12, "title": "Third"}]}]
        epic_manager.write_epic(tmp_path, issue="100", slug="my-epic",
                                issue_repo="Hortora/soredium",
                                batches=batches, context="Test")
        plan = epic_manager.parse_batch_plan(tmp_path / "design" / ".epic")
        assert plan["is_epic"] is True
        assert plan["epic_number"] == "100"
        assert len(plan["batches"]) == 2
        assert plan["current_issue"] == 10

    def test_write_epic_file_with_repos(self, tmp_path):
        epic_path = tmp_path / ".slot"
        batches = [{"number": 1, "name": "Core",
                    "issues": [{"number": 10, "title": "First"}]}]
        epic_manager.write_epic_file(
            epic_path, "# Slot 1 — branch", repos=["engine", "iot"],
            issue="50", issue_repo="casehubio/engine",
            batches=batches, context="Test")
        content = epic_path.read_text()
        assert "## Repos" in content
        assert "engine (primary)" in content


class TestDetect:
    def test_detects_single_repo_epic(self, tmp_path):
        epic_dir = tmp_path / "design"
        epic_dir.mkdir()
        (epic_dir / ".epic").write_text(
            "## Issue\nHortora/soredium#99\nType: epic\n\n"
            "## Batch Plan\n\n### Batch 1 — Setup\n"
            "- [ ] #100 — First task ← active\n"
        )
        result = epic_manager.detect(tmp_path)
        assert result is not None
        assert result["is_epic"] is True
        assert result["epic_path"] == epic_dir / ".epic"
        assert result["current_issue"] == 100

    def test_detects_slot_epic(self, tmp_path):
        (tmp_path / ".slot").write_text(SAMPLE_EPIC_SLOT_MD)
        result = epic_manager.detect(tmp_path)
        assert result is not None
        assert result["is_epic"] is True
        assert result["epic_path"] == tmp_path / ".slot"

    def test_detects_project_inside_slot(self, tmp_path):
        (tmp_path / ".slot").write_text(SAMPLE_EPIC_SLOT_MD)
        project_dir = tmp_path / "engine"
        project_dir.mkdir()
        result = epic_manager.detect(project_dir)
        assert result is not None
        assert result["epic_path"] == tmp_path / ".slot"

    def test_returns_none_no_epic(self, tmp_path):
        assert epic_manager.detect(tmp_path) is None

    def test_returns_none_non_epic_slot(self, tmp_path):
        (tmp_path / ".slot").write_text("# Slot 5\n\n## Issue\nrepo#10\n")
        assert epic_manager.detect(tmp_path) is None

    def test_prefers_design_epic_over_slot(self, tmp_path):
        epic_dir = tmp_path / "design"
        epic_dir.mkdir()
        (epic_dir / ".epic").write_text(
            "## Issue\nrepo#1\nType: epic\n\n"
            "## Batch Plan\n\n### Batch 1 — A\n- [ ] #10 — X ← active\n"
        )
        (tmp_path / ".slot").write_text(SAMPLE_EPIC_SLOT_MD)
        result = epic_manager.detect(tmp_path)
        assert result["epic_path"] == epic_dir / ".epic"


class TestSafeExitFix:
    def test_safe_exit_false_mid_batch_with_prior_complete(self, tmp_path):
        md = (
            "## Issue\nrepo#1\nType: epic\n\n## Batch Plan\n\n"
            "### Batch 1 — Done\n- [x] #10 — A\n- [x] #11 — B\n\n"
            "### Batch 2 — In progress\n- [x] #12 — C\n- [ ] #13 — D ← active\n"
        )
        (tmp_path / ".epic").write_text(md)
        result = epic_manager.status(tmp_path / ".epic")
        assert result["safe_exit"] is False

    def test_safe_exit_true_at_batch_boundary(self, tmp_path):
        md = (
            "## Issue\nrepo#1\nType: epic\n\n## Batch Plan\n\n"
            "### Batch 1 — Done\n- [x] #10 — A\n- [x] #11 — B\n\n"
            "### Batch 2 — Next\n- [ ] #12 — C ← active\n- [ ] #13 — D\n"
        )
        (tmp_path / ".epic").write_text(md)
        result = epic_manager.status(tmp_path / ".epic")
        assert result["safe_exit"] is True

    def test_safe_exit_false_no_batches_complete(self, tmp_path):
        md = (
            "## Issue\nrepo#1\nType: epic\n\n## Batch Plan\n\n"
            "### Batch 1 — Work\n- [ ] #10 — A ← active\n- [ ] #11 — B\n"
        )
        (tmp_path / ".epic").write_text(md)
        result = epic_manager.status(tmp_path / ".epic")
        assert result["safe_exit"] is False


class TestCheckSubcommand:
    def test_check_output_format(self, tmp_path):
        epic = tmp_path / ".epic"
        epic.write_text(
            "## Issue\nrepo#1\nType: epic\n\n## Batch Plan\n\n"
            "### Batch 1 — Work\n- [x] #10 — A\n- [ ] #11 — B ← active\n\n"
            "### Batch 2 — More\n- [ ] #12 — C\n"
        )
        import subprocess
        result = subprocess.run(
            [sys.executable, str(skill_dir / "epic_manager.py"),
             "check", str(epic)],
            capture_output=True, text=True,
        )
        lines = dict(l.split("=", 1) for l in result.stdout.strip().split("\n") if "=" in l)
        assert lines["IS_EPIC"] == "yes"
        assert lines["EPIC_COMPLETE"] == "no"
        assert lines["SAFE_EXIT"] == "no"
        assert lines["CURRENT_BATCH"] == "1"
        assert lines["TOTAL_BATCHES"] == "2"
        assert lines["ACTIVE_ISSUE"] == "11"

    def test_check_epic_complete(self, tmp_path):
        epic = tmp_path / ".epic"
        epic.write_text(
            "## Issue\nrepo#1\nType: epic\n\n## Batch Plan\n\n"
            "### Batch 1 — Done\n- [x] #10 — A\n"
        )
        import subprocess
        result = subprocess.run(
            [sys.executable, str(skill_dir / "epic_manager.py"),
             "check", str(epic)],
            capture_output=True, text=True,
        )
        lines = dict(l.split("=", 1) for l in result.stdout.strip().split("\n") if "=" in l)
        assert lines["EPIC_COMPLETE"] == "yes"

    def test_check_empty_plan_not_complete(self, tmp_path):
        epic = tmp_path / ".epic"
        epic.write_text(
            "## Issue\nrepo#1\nType: epic\n\n## Batch Plan\n"
        )
        import subprocess
        result = subprocess.run(
            [sys.executable, str(skill_dir / "epic_manager.py"),
             "check", str(epic)],
            capture_output=True, text=True,
        )
        lines = dict(l.split("=", 1) for l in result.stdout.strip().split("\n") if "=" in l)
        assert lines["EPIC_COMPLETE"] == "no"

    def test_check_non_epic(self, tmp_path):
        f = tmp_path / ".slot"
        f.write_text("# Slot 1\n\n## Issue\nrepo#42\n")
        import subprocess
        result = subprocess.run(
            [sys.executable, str(skill_dir / "epic_manager.py"),
             "check", str(f)],
            capture_output=True, text=True,
        )
        assert "IS_EPIC=no" in result.stdout


class TestTickCheckboxesInBody:
    def test_ticks_matching_checkboxes(self):
        body = "## Scope\n- [ ] #83 — Fix auth\n- [ ] #84 — Add tests\n- [x] #85 — Done\n"
        result = epic_manager._tick_checkboxes_in_body(body, [83])
        assert "- [x] #83 — Fix auth" in result
        assert "- [ ] #84 — Add tests" in result
        assert "- [x] #85 — Done" in result

    def test_idempotent(self):
        body = "- [x] #83 — Already done\n- [ ] #84 — Not done\n"
        result = epic_manager._tick_checkboxes_in_body(body, [83])
        assert result == body

    def test_multiple_issues(self):
        body = "- [ ] #10 — A\n- [ ] #11 — B\n- [ ] #12 — C\n"
        result = epic_manager._tick_checkboxes_in_body(body, [10, 12])
        assert "- [x] #10" in result
        assert "- [ ] #11" in result
        assert "- [x] #12" in result

    def test_preserves_trailing_newline(self):
        body = "- [ ] #10 — A\n"
        result = epic_manager._tick_checkboxes_in_body(body, [10])
        assert result.endswith("\n")
        assert not result.endswith("\n\n")

    def test_write_epic_file_no_repos(self, tmp_path):
        epic_path = tmp_path / ".epic"
        batches = [{"number": 1, "name": "Core",
                    "issues": [{"number": 10, "title": "First"}]}]
        epic_manager.write_epic_file(
            epic_path, "# Epic #100 — test", repos=None,
            issue="100", issue_repo="Hortora/soredium",
            batches=batches, context="Test")
        content = epic_path.read_text()
        assert "## Repos" not in content
        assert "## Created" not in content


class TestCLI:
    def test_plan_subcommand(self, tmp_path, capsys):
        (tmp_path / ".slot").write_text(SAMPLE_EPIC_SLOT_MD)
        sys.argv = ["epic_manager.py", "plan", str(tmp_path / ".slot")]
        epic_manager.main()
        out = capsys.readouterr().out
        assert '"is_epic": true' in out

    def test_status_subcommand(self, tmp_path, capsys):
        (tmp_path / ".slot").write_text(SAMPLE_EPIC_SLOT_MD)
        sys.argv = ["epic_manager.py", "status", str(tmp_path / ".slot")]
        epic_manager.main()
        out = capsys.readouterr().out
        assert '"total_issues": 4' in out

    def test_write_subcommand(self, tmp_path, capsys):
        import json
        batches = json.dumps([{"number": 1, "name": "Batch", "issues": [{"number": 10, "title": "First"}, {"number": 20, "title": "Second"}]}])
        sys.argv = ["epic_manager.py", "write", str(tmp_path / "design" / ".epic"),
                     f"workspace={tmp_path}", "issue=99", "slug=test",
                     "issue-repo=Org/repo", "context=Test epic",
                     f"batches={batches}"]
        epic_manager.main()
        out = capsys.readouterr().out
        assert "WRITTEN=yes" in out
        epic_file = tmp_path / "design" / ".epic"
        assert epic_file.exists()
        content = epic_file.read_text()
        assert "Org/repo#99" in content
        assert "#10 — First" in content
        assert "← active" in content

    def test_unknown_command(self, tmp_path, capsys):
        sys.argv = ["epic_manager.py", "bogus", str(tmp_path / ".slot")]
        with pytest.raises(SystemExit):
            epic_manager.main()
