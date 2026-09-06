"""Tests for verification/cross_checks.py"""

from pathlib import Path

from verification.cross_checks import (
    check_duplicate_issues,
    check_duplicate_slots,
    check_split_brain,
)


def _make_slot(slots_dir: Path, num: str, branch: str, covers: str = "") -> Path:
    slot = slots_dir / num
    slot.mkdir(parents=True, exist_ok=True)
    content = f"# Slot {num} — {branch}\n"
    if covers:
        content += f"Covers: {covers}\n"
    (slot / ".slot").write_text(content)
    return slot


class TestCheckDuplicateSlots:
    def test_no_slots(self, tmp_path):
        assert check_duplicate_slots(tmp_path / "slots") == []

    def test_unique_branches(self, tmp_path):
        slots = tmp_path / "slots"
        _make_slot(slots, "1", "issue-10-feature")
        _make_slot(slots, "2", "issue-20-other")
        assert check_duplicate_slots(slots) == []

    def test_duplicate_branch(self, tmp_path):
        slots = tmp_path / "slots"
        _make_slot(slots, "1", "issue-10-feature")
        _make_slot(slots, "2", "issue-10-feature")
        findings = check_duplicate_slots(slots)
        assert len(findings) == 1
        assert findings[0].category == "duplicate-slot"
        assert "issue-10-feature" in findings[0].message

    def test_non_numeric_dirs_ignored(self, tmp_path):
        slots = tmp_path / "slots"
        _make_slot(slots, "1", "issue-10-feature")
        (slots / "attic").mkdir(parents=True)
        assert check_duplicate_slots(slots) == []


class TestCheckDuplicateIssues:
    def test_no_slots(self, tmp_path):
        assert check_duplicate_issues(tmp_path / "slots") == []

    def test_unique_issues(self, tmp_path):
        slots = tmp_path / "slots"
        _make_slot(slots, "1", "issue-10", covers="10")
        _make_slot(slots, "2", "issue-20", covers="20")
        assert check_duplicate_issues(slots) == []

    def test_duplicate_issue(self, tmp_path):
        slots = tmp_path / "slots"
        _make_slot(slots, "1", "issue-10", covers="10,11")
        _make_slot(slots, "2", "issue-20", covers="10,12")
        findings = check_duplicate_issues(slots)
        assert len(findings) == 1
        assert findings[0].category == "duplicate-issue"
        assert "10" in findings[0].message

    def test_no_covers_line_ok(self, tmp_path):
        slots = tmp_path / "slots"
        _make_slot(slots, "1", "issue-10")
        _make_slot(slots, "2", "issue-20")
        assert check_duplicate_issues(slots) == []


class TestCheckSplitBrain:
    def test_no_overlap(self, tmp_path):
        slots = tmp_path / "slots"
        attic = slots / "attic"
        _make_slot(slots, "1", "issue-10")
        _make_slot(attic, "2", "issue-20")
        assert check_split_brain(slots, attic) == []

    def test_overlap_detected(self, tmp_path):
        slots = tmp_path / "slots"
        attic = slots / "attic"
        _make_slot(slots, "3", "issue-30")
        _make_slot(attic, "3", "issue-30")
        findings = check_split_brain(slots, attic)
        assert len(findings) == 1
        assert findings[0].category == "split-brain"
        assert "3" in findings[0].message

    def test_missing_dirs(self, tmp_path):
        assert check_split_brain(tmp_path / "slots", tmp_path / "attic") == []

    def test_multiple_overlaps(self, tmp_path):
        slots = tmp_path / "slots"
        attic = slots / "attic"
        _make_slot(slots, "1", "issue-10")
        _make_slot(attic, "1", "issue-10")
        _make_slot(slots, "2", "issue-20")
        _make_slot(attic, "2", "issue-20")
        findings = check_split_brain(slots, attic)
        assert len(findings) == 2
