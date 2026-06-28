"""Tests for adversarial-design-review/parser.py"""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "adversarial-review"


def _read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


# ---------------------------------------------------------------------------
# 1a. Signal extraction
# ---------------------------------------------------------------------------

class TestExtractSignal:

    def test_clean_continue(self) -> None:
        from adversarial_design_review.parser import extract_signal

        content = "Some review text.\n\n---\nSIGNAL: CONTINUE\n"
        result = extract_signal(content)
        assert result.signal_type == "CONTINUE"
        assert result.description is None
        assert not result.is_default

    def test_clean_approved(self) -> None:
        from adversarial_design_review.parser import extract_signal

        content = "All good.\n\n---\nSIGNAL: APPROVED\n"
        result = extract_signal(content)
        assert result.signal_type == "APPROVED"

    def test_decision_needed_with_description(self) -> None:
        from adversarial_design_review.parser import extract_signal

        content = "---\nSIGNAL: DECISION_NEEDED: saga timeout under partial failure\n"
        result = extract_signal(content)
        assert result.signal_type == "DECISION_NEEDED"
        assert result.description == "saga timeout under partial failure"

    def test_lowercase_signal(self) -> None:
        from adversarial_design_review.parser import extract_signal

        content = "---\nsignal: continue\n"
        result = extract_signal(content)
        assert result.signal_type == "CONTINUE"

    def test_trailing_punctuation(self) -> None:
        from adversarial_design_review.parser import extract_signal

        content = "---\nSIGNAL: CONTINUE.\n"
        result = extract_signal(content)
        assert result.signal_type == "CONTINUE"

    def test_extra_whitespace(self) -> None:
        from adversarial_design_review.parser import extract_signal

        content = "---\n  SIGNAL:   CONTINUE  \n"
        result = extract_signal(content)
        assert result.signal_type == "CONTINUE"

    def test_no_separator(self) -> None:
        from adversarial_design_review.parser import extract_signal

        content = "Some text.\nSIGNAL: CONTINUE\n"
        result = extract_signal(content)
        assert result.signal_type == "CONTINUE"

    def test_no_signal_found_defaults_to_continue(self) -> None:
        from adversarial_design_review.parser import extract_signal

        content = "Just some review text with no signal at all.\n"
        result = extract_signal(content)
        assert result.signal_type == "CONTINUE"
        assert result.is_default

    def test_signal_in_fixture_round1(self) -> None:
        from adversarial_design_review.parser import extract_signal

        content = _read_fixture("reviewer-round1-clean.md")
        result = extract_signal(content)
        assert result.signal_type == "CONTINUE"

    def test_signal_in_fixture_premature_approve(self) -> None:
        from adversarial_design_review.parser import extract_signal

        content = _read_fixture("reviewer-premature-approve.md")
        result = extract_signal(content)
        assert result.signal_type == "APPROVED"

    def test_signal_in_fuzzy_fixture(self) -> None:
        from adversarial_design_review.parser import extract_signal

        content = _read_fixture("reviewer-fuzzy-headings.md")
        result = extract_signal(content)
        assert result.signal_type == "CONTINUE"

    def test_decision_needed_in_fixture(self) -> None:
        from adversarial_design_review.parser import extract_signal

        content = _read_fixture("implementor-mixed-status.md")
        result = extract_signal(content)
        assert result.signal_type == "DECISION_NEEDED"
        assert "correlation ID" in result.description


# ---------------------------------------------------------------------------
# 1b. Reviewer issue extraction
# ---------------------------------------------------------------------------

class TestExtractNewIssues:

    def test_round1_clean_extracts_three_issues(self) -> None:
        from adversarial_design_review.parser import extract_new_issues

        content = _read_fixture("reviewer-round1-clean.md")
        issues = extract_new_issues(content, round_num=1, existing_ids=set())
        assert len(issues) == 3
        assert issues[0].issue_id == "R1-01"
        assert "aggregate boundary" in issues[0].title.lower() or "line items" in issues[0].body.lower()
        assert issues[1].issue_id == "R1-02"
        assert issues[2].issue_id == "R1-03"

    def test_skips_known_sections(self) -> None:
        from adversarial_design_review.parser import extract_new_issues

        content = _read_fixture("reviewer-round2-confirmations.md")
        issues = extract_new_issues(content, round_num=2, existing_ids={"R1-01", "R1-02", "R1-03"})
        assert len(issues) == 1
        assert issues[0].issue_id == "R2-01"
        assert "batch" in issues[0].title.lower() or "orchestration" in issues[0].title.lower()

    def test_skips_headings_with_existing_issue_ids(self) -> None:
        from adversarial_design_review.parser import extract_new_issues

        content = _read_fixture("reviewer-round2-confirmations.md")
        issues = extract_new_issues(content, round_num=2, existing_ids={"R1-01", "R1-02", "R1-03"})
        issue_ids = [i.issue_id for i in issues]
        assert "R1-02" not in issue_ids

    def test_handles_h2_headings(self) -> None:
        from adversarial_design_review.parser import extract_new_issues

        content = _read_fixture("reviewer-fuzzy-headings.md")
        issues = extract_new_issues(content, round_num=1, existing_ids=set())
        assert len(issues) == 1
        assert "failure mode" in issues[0].title.lower() or "timeout" in issues[0].title.lower()

    def test_extracts_body_text(self) -> None:
        from adversarial_design_review.parser import extract_new_issues

        content = _read_fixture("reviewer-round1-clean.md")
        issues = extract_new_issues(content, round_num=1, existing_ids=set())
        assert len(issues[0].body) > 0
        assert "payload" in issues[0].body.lower() or "line items" in issues[0].body.lower()


# ---------------------------------------------------------------------------
# 1c. Confirmation extraction
# ---------------------------------------------------------------------------

class TestExtractConfirmations:

    def test_clean_confirmations(self) -> None:
        from adversarial_design_review.parser import extract_confirmations

        content = _read_fixture("reviewer-round2-confirmations.md")
        confirmations = extract_confirmations(content)
        assert len(confirmations) == 3

        resolved = [c for c in confirmations if c.is_resolved]
        still_open = [c for c in confirmations if not c.is_resolved]
        assert len(resolved) == 2
        assert len(still_open) == 1
        assert still_open[0].issue_id == "R1-02"
        assert "concurrent" in still_open[0].reason.lower()

    def test_fuzzy_confirmations(self) -> None:
        from adversarial_design_review.parser import extract_confirmations

        content = _read_fixture("reviewer-fuzzy-headings.md")
        confirmations = extract_confirmations(content)
        assert len(confirmations) == 3
        resolved_ids = {c.issue_id for c in confirmations if c.is_resolved}
        assert "R1-01" in resolved_ids
        assert "R1-02" in resolved_ids
        assert "R1-03" in resolved_ids

    def test_no_confirmations_section(self) -> None:
        from adversarial_design_review.parser import extract_confirmations

        content = _read_fixture("reviewer-round1-clean.md")
        confirmations = extract_confirmations(content)
        assert len(confirmations) == 0


# ---------------------------------------------------------------------------
# 1d. Implementor response parsing
# ---------------------------------------------------------------------------

class TestExtractIssueResponses:

    def test_clean_responses(self) -> None:
        from adversarial_design_review.parser import extract_issue_responses

        content = _read_fixture("implementor-round1-clean.md")
        responses = extract_issue_responses(content)
        assert len(responses) == 3

        by_id = {r.issue_id: r for r in responses}
        assert by_id["R1-01"].status == "FIXED"
        assert by_id["R1-01"].section_ref == "2.3"
        assert by_id["R1-02"].status == "FIXED"
        assert by_id["R1-02"].section_ref == "4.1"
        assert by_id["R1-03"].status == "REJECTED"
        assert by_id["R1-03"].section_ref is None
        assert "envelope" in by_id["R1-03"].rationale.lower()

    def test_fuzzy_status_and_punctuation(self) -> None:
        from adversarial_design_review.parser import extract_issue_responses

        content = _read_fixture("implementor-mixed-status.md")
        responses = extract_issue_responses(content)
        assert len(responses) == 3

        by_id = {r.issue_id: r for r in responses}
        assert by_id["R1-01"].status == "FIXED"
        assert by_id["R1-02"].status == "FIXED"
        assert by_id["R1-03"].status == "ESCALATED"

    def test_section_ref_variants(self) -> None:
        from adversarial_design_review.parser import extract_issue_responses

        content = _read_fixture("implementor-mixed-status.md")
        responses = extract_issue_responses(content)
        by_id = {r.issue_id: r for r in responses}
        assert by_id["R1-01"].section_ref == "2.3"
        assert by_id["R1-02"].section_ref == "4.1"

    def test_no_section_ref(self) -> None:
        from adversarial_design_review.parser import extract_issue_responses

        content = _read_fixture("implementor-no-section-ref.md")
        responses = extract_issue_responses(content)
        by_id = {r.issue_id: r for r in responses}
        assert by_id["R1-01"].section_ref is None
        assert by_id["R1-02"].section_ref is None

    def test_extracts_rationale_for_rejected(self) -> None:
        from adversarial_design_review.parser import extract_issue_responses

        content = _read_fixture("implementor-round1-clean.md")
        responses = extract_issue_responses(content)
        rejected = [r for r in responses if r.status == "REJECTED"]
        assert len(rejected) == 1
        assert len(rejected[0].rationale) > 20

    def test_partial_response_missing_items_detectable(self) -> None:
        """PM can diff parsed responses against focus list to find missing items."""
        from adversarial_design_review.parser import extract_issue_responses

        content = """\
### R1-01: FIXED
Updated §2.3 with new validation logic.
### R1-02: REJECTED
This is already handled by the existing retry mechanism.
"""
        responses = extract_issue_responses(content)
        addressed_ids = {r.issue_id for r in responses}
        focus = ["R1-01", "R1-02", "R1-03", "R1-04"]
        missing = [f for f in focus if f not in addressed_ids]
        assert missing == ["R1-03", "R1-04"]


# ---------------------------------------------------------------------------
# 1e. Marker extraction
# ---------------------------------------------------------------------------

class TestExtractMarkers:

    def test_assumption_extraction(self) -> None:
        from adversarial_design_review.parser import extract_assumptions

        content = _read_fixture("reviewer-round1-clean.md")
        assumptions = extract_assumptions(content)
        assert len(assumptions) == 1
        assert "exactly-once" in assumptions[0].lower()

    def test_assumption_in_round2(self) -> None:
        from adversarial_design_review.parser import extract_assumptions

        content = _read_fixture("reviewer-round2-confirmations.md")
        assumptions = extract_assumptions(content)
        assert len(assumptions) == 1
        assert "idempotency" in assumptions[0].lower()

    def test_settled_decision_extraction(self) -> None:
        from adversarial_design_review.parser import extract_settled_decisions

        content = _read_fixture("implementor-round1-clean.md")
        decisions = extract_settled_decisions(content)
        assert len(decisions) == 1
        assert "500" in decisions[0].text or "line items" in decisions[0].text.lower()
        assert decisions[0].from_issue == "R1-01"

    def test_no_markers(self) -> None:
        from adversarial_design_review.parser import extract_assumptions, extract_settled_decisions

        content = _read_fixture("implementor-no-section-ref.md")
        assert len(extract_assumptions(content)) == 0
        assert len(extract_settled_decisions(content)) == 0

    def test_assumption_only_at_line_start(self) -> None:
        from adversarial_design_review.parser import extract_assumptions

        content = "This is not an ASSUMPTION: just text in a sentence.\nASSUMPTION: Real assumption here\n"
        assumptions = extract_assumptions(content)
        assert len(assumptions) == 1
        assert "Real assumption" in assumptions[0]
