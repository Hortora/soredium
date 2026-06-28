"""Tests for adversarial-design-review/tracker.py"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# 2a. Issue state transitions
# ---------------------------------------------------------------------------

class TestIssueTransitions:

    def test_open_to_addressed(self) -> None:
        from adversarial_design_review.tracker import Tracker, IssueStatus

        t = Tracker(project_name="test")
        t.add_issue("R1-01", "Missing boundary", round_raised=1)
        t.mark_addressed("R1-01", section_ref="2.3", commit_hash="abc123", rationale="Added cap")
        assert t.get_issue("R1-01").status == IssueStatus.ADDRESSED

    def test_open_to_rejected(self) -> None:
        from adversarial_design_review.tracker import Tracker, IssueStatus

        t = Tracker(project_name="test")
        t.add_issue("R1-01", "Missing boundary", round_raised=1)
        t.mark_rejected("R1-01", rationale="Not applicable")
        assert t.get_issue("R1-01").status == IssueStatus.REJECTED

    def test_addressed_to_verified(self) -> None:
        from adversarial_design_review.tracker import Tracker, IssueStatus

        t = Tracker(project_name="test")
        t.add_issue("R1-01", "Missing boundary", round_raised=1)
        t.mark_addressed("R1-01", section_ref="2.3", commit_hash="abc123", rationale="Fixed")
        t.mark_verified("R1-01")
        assert t.get_issue("R1-01").status == IssueStatus.VERIFIED

    def test_addressed_to_contested(self) -> None:
        from adversarial_design_review.tracker import Tracker, IssueStatus

        t = Tracker(project_name="test")
        t.add_issue("R1-01", "Missing boundary", round_raised=1)
        t.mark_addressed("R1-01", section_ref="2.3", commit_hash="abc123", rationale="Fixed")
        t.mark_contested("R1-01", reason="Still not right")
        assert t.get_issue("R1-01").status == IssueStatus.CONTESTED
        assert t.get_issue("R1-01").contested_rounds == 1

    def test_rejected_to_accepted(self) -> None:
        from adversarial_design_review.tracker import Tracker, IssueStatus

        t = Tracker(project_name="test")
        t.add_issue("R1-01", "Missing boundary", round_raised=1)
        t.mark_rejected("R1-01", rationale="Not applicable")
        t.mark_accepted("R1-01")
        assert t.get_issue("R1-01").status == IssueStatus.ACCEPTED

    def test_rejected_to_contested(self) -> None:
        from adversarial_design_review.tracker import Tracker, IssueStatus

        t = Tracker(project_name="test")
        t.add_issue("R1-01", "Missing boundary", round_raised=1)
        t.mark_rejected("R1-01", rationale="Not applicable")
        t.mark_contested("R1-01", reason="Disagree")
        assert t.get_issue("R1-01").status == IssueStatus.CONTESTED

    def test_contested_auto_escalation(self) -> None:
        from adversarial_design_review.tracker import Tracker, IssueStatus

        t = Tracker(project_name="test")
        t.add_issue("R1-01", "Missing boundary", round_raised=1)
        t.mark_addressed("R1-01", section_ref="2.3", commit_hash="abc", rationale="Fixed")
        t.mark_contested("R1-01", reason="Nope")
        t.mark_addressed("R1-01", section_ref="2.3", commit_hash="def", rationale="Fixed again")
        t.mark_contested("R1-01", reason="Still nope")
        assert t.get_issue("R1-01").status == IssueStatus.DEFERRED
        assert t.get_issue("R1-01").contested_rounds == 2

    def test_unknown_issue_raises(self) -> None:
        from adversarial_design_review.tracker import Tracker

        t = Tracker(project_name="test")
        with pytest.raises(KeyError):
            t.mark_addressed("R9-99", section_ref="1.1", commit_hash="x", rationale="x")

    def test_invalid_open_to_verified_raises(self) -> None:
        from adversarial_design_review.tracker import Tracker

        t = Tracker(project_name="test")
        t.add_issue("R1-01", "Issue", round_raised=1)
        with pytest.raises(ValueError, match="Invalid transition"):
            t.mark_verified("R1-01")

    def test_invalid_open_to_accepted_raises(self) -> None:
        from adversarial_design_review.tracker import Tracker

        t = Tracker(project_name="test")
        t.add_issue("R1-01", "Issue", round_raised=1)
        with pytest.raises(ValueError, match="Invalid transition"):
            t.mark_accepted("R1-01")

    def test_invalid_verified_to_addressed_raises(self) -> None:
        from adversarial_design_review.tracker import Tracker

        t = Tracker(project_name="test")
        t.add_issue("R1-01", "Issue", round_raised=1)
        t.mark_addressed("R1-01", section_ref="1.1", commit_hash="a", rationale="x")
        t.mark_verified("R1-01")
        with pytest.raises(ValueError, match="Invalid transition"):
            t.mark_addressed("R1-01", section_ref="1.1", commit_hash="b", rationale="y")


# ---------------------------------------------------------------------------
# 2b. Premature convergence detection
# ---------------------------------------------------------------------------

class TestPrematureConvergence:

    def test_approved_round2_unconfirmed_issues_overrides(self) -> None:
        from adversarial_design_review.tracker import Tracker

        t = Tracker(project_name="test")
        for i in range(1, 7):
            t.add_issue(f"R1-{i:02d}", f"Issue {i}", round_raised=1)
        t.mark_addressed("R1-01", section_ref="1.1", commit_hash="a", rationale="x")
        t.mark_addressed("R1-02", section_ref="1.2", commit_hash="a", rationale="x")
        t.mark_verified("R1-01")
        t.mark_verified("R1-02")

        result = t.check_premature_convergence(round_num=2)
        assert result.should_override
        assert len(result.unconfirmed_ids) == 4

    def test_approved_round4_no_override(self) -> None:
        from adversarial_design_review.tracker import Tracker

        t = Tracker(project_name="test")
        t.add_issue("R1-01", "Issue", round_raised=1)
        result = t.check_premature_convergence(round_num=4)
        assert not result.should_override

    def test_approved_all_confirmed_no_override(self) -> None:
        from adversarial_design_review.tracker import Tracker

        t = Tracker(project_name="test")
        for i in range(1, 4):
            t.add_issue(f"R1-{i:02d}", f"Issue {i}", round_raised=1)
            t.mark_addressed(f"R1-{i:02d}", section_ref="1.1", commit_hash="a", rationale="x")
            t.mark_verified(f"R1-{i:02d}")

        result = t.check_premature_convergence(round_num=2)
        assert not result.should_override


# ---------------------------------------------------------------------------
# 2c. Focus section generation
# ---------------------------------------------------------------------------

class TestFocusItems:

    def test_returns_unresolved_items(self) -> None:
        from adversarial_design_review.tracker import Tracker, IssueStatus

        t = Tracker(project_name="test")
        t.add_issue("R1-01", "Issue 1", round_raised=1)
        t.add_issue("R1-02", "Issue 2", round_raised=1)
        t.add_issue("R1-03", "Issue 3", round_raised=1)
        t.add_issue("R1-04", "Issue 4", round_raised=1)
        t.add_issue("R1-05", "Issue 5", round_raised=1)

        t.mark_addressed("R1-02", section_ref="1.1", commit_hash="a", rationale="x")
        t.mark_verified("R1-02")
        t.mark_addressed("R1-03", section_ref="1.2", commit_hash="a", rationale="x")
        t.mark_contested("R1-03", reason="Nope")
        t.mark_addressed("R1-04", section_ref="1.3", commit_hash="a", rationale="x")
        t.mark_rejected("R1-05", rationale="Not applicable")

        focus = t.get_focus_items()
        assert "R1-01" in focus      # OPEN — needs attention
        assert "R1-02" not in focus  # VERIFIED — done
        assert "R1-03" in focus      # CONTESTED — needs attention
        assert "R1-04" in focus      # ADDRESSED — awaiting reviewer confirmation
        assert "R1-05" in focus      # REJECTED — awaiting reviewer response


# ---------------------------------------------------------------------------
# 2d. Tracker rendering
# ---------------------------------------------------------------------------

class TestTrackerRendering:

    def test_renders_markdown(self) -> None:
        from adversarial_design_review.tracker import Tracker

        t = Tracker(project_name="test-project")
        t.add_issue("R1-01", "Missing boundary", round_raised=1)
        t.mark_addressed("R1-01", section_ref="2.3", commit_hash="abc123", rationale="Added cap")

        md = t.render()
        assert "# Design Review Tracker" in md
        assert "test-project" in md
        assert "R1-01" in md
        assert "ADDRESSED" in md
        assert "abc123" in md

    def test_renders_summary_table_with_per_round_deltas(self) -> None:
        from adversarial_design_review.tracker import Tracker

        t = Tracker(project_name="test")
        t.add_issue("R1-01", "Issue 1", round_raised=1)
        t.add_issue("R1-02", "Issue 2", round_raised=1)
        t.add_issue("R1-03", "Issue 3", round_raised=1)
        t.mark_addressed("R1-01", section_ref="1.1", commit_hash="a", rationale="x")
        t.mark_verified("R1-01")
        t.record_round(1)

        # Round 2: one new issue, one more verified
        t.add_issue("R2-01", "Issue 4", round_raised=2)
        t.mark_addressed("R1-02", section_ref="1.2", commit_hash="b", rationale="x")
        t.mark_verified("R1-02")
        t.record_round(2)

        summaries = t.get_round_summaries()
        assert len(summaries) == 2

        r1 = summaries[0]
        assert r1.round_num == 1
        assert r1.raised == 3
        assert r1.verified == 1

        r2 = summaries[1]
        assert r2.round_num == 2
        assert r2.raised == 1
        assert r2.verified == 1  # only R1-02 was verified in round 2, not R1-01

    def test_renders_summary_table(self) -> None:
        from adversarial_design_review.tracker import Tracker

        t = Tracker(project_name="test")
        t.add_issue("R1-01", "Issue 1", round_raised=1)
        t.add_issue("R1-02", "Issue 2", round_raised=1)
        t.mark_addressed("R1-01", section_ref="1.1", commit_hash="a", rationale="x")
        t.mark_verified("R1-01")
        t.record_round(1)

        md = t.render()
        assert "| 1" in md
        assert "Summary" in md

    def test_renders_navigatable_links(self) -> None:
        from adversarial_design_review.tracker import Tracker

        t = Tracker(project_name="test")
        t.add_issue("R1-01", "Missing boundary", round_raised=1)
        t.mark_addressed("R1-01", section_ref="2.3", commit_hash="abc", rationale="Fixed")

        md = t.render()
        assert "[responses/reviewer-1.md]" in md
        assert "(responses/reviewer-1.md#" in md
        assert "[§2.3](spec.md)" in md

    def test_renders_focus_section(self) -> None:
        from adversarial_design_review.tracker import Tracker

        t = Tracker(project_name="test")
        t.add_issue("R1-01", "Issue 1", round_raised=1)

        md = t.render()
        assert "Focus for next round" in md
        assert "R1-01" in md

    def test_renders_assumptions(self) -> None:
        from adversarial_design_review.tracker import Tracker

        t = Tracker(project_name="test")
        t.add_assumption("Event store supports exactly-once", round_surfaced=1, source="reviewer-1.md")

        md = t.render()
        assert "Assumptions" in md
        assert "exactly-once" in md

    def test_renders_settled_decisions(self) -> None:
        from adversarial_design_review.tracker import Tracker

        t = Tracker(project_name="test")
        t.add_settled_decision("Strong consistency for writes", from_issue="R1-04", rationale="Required by policy")

        md = t.render()
        assert "Settled Decisions" in md
        assert "Strong consistency" in md

    def test_write_and_read_roundtrip(self, tmp_path) -> None:
        from adversarial_design_review.tracker import Tracker

        t = Tracker(project_name="test")
        t.add_issue("R1-01", "Missing boundary", round_raised=1)
        t.mark_addressed("R1-01", section_ref="2.3", commit_hash="abc", rationale="Fixed")

        path = tmp_path / "tracker.md"
        t.write(path)
        assert path.exists()
        content = path.read_text()
        assert "R1-01" in content
        assert "ADDRESSED" in content


# ---------------------------------------------------------------------------
# 2e. Diff verification
# ---------------------------------------------------------------------------

class TestDiffVerification:

    def test_section_found_in_diff(self) -> None:
        from adversarial_design_review.tracker import verify_against_diff

        diff = """\
@@ -10,6 +10,8 @@
 ## 4.1 Payment Flow
+
+After 3 retries with exponential backoff, transition to PAYMENT_FAILED.
"""
        result = verify_against_diff(diff, "4.1")
        assert result.section_changed

    def test_section_not_found_in_diff(self) -> None:
        from adversarial_design_review.tracker import verify_against_diff

        diff = """\
@@ -10,6 +10,8 @@
 ## 2.3 Line Items
+Maximum 500 line items per invoice.
"""
        result = verify_against_diff(diff, "4.1")
        assert not result.section_changed

    def test_no_section_ref(self) -> None:
        from adversarial_design_review.tracker import verify_against_diff

        diff = "some diff content"
        result = verify_against_diff(diff, None)
        assert result.section_changed
        assert "no section reference" in result.note.lower()

    def test_section_ref_as_section_word(self) -> None:
        from adversarial_design_review.tracker import verify_against_diff

        diff = """\
@@ -10,6 +10,8 @@
 ## 4.1 Payment Flow
+Added terminal state.
"""
        result = verify_against_diff(diff, "4.1")
        assert result.section_changed
