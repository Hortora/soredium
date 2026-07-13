"""Tests for structured metadata extraction in parser.py."""

import sys
from dataclasses import fields as dataclass_fields
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from parser import (
    Evidence,
    Issue,
    IssueResponse,
    Confirmation,
    extract_new_issues,
    extract_issue_responses,
    extract_confirmations,
)


class TestIssueMetadataExtraction:

    def test_all_metadata_present(self):
        content = (
            "### Missing failure mode\n"
            "LOCATION: §4.1 Payment Flow\n"
            "PRIORITY: HIGH\n"
            "DEPENDS: R1-02, R1-03\n"
            "\n"
            "The spec doesn't handle timeouts.\n"
        )
        issues = extract_new_issues(content, 1, set())
        assert len(issues) == 1
        issue = issues[0]
        assert issue.location == "§4.1 Payment Flow"
        assert issue.priority == "HIGH"
        assert issue.depends == ["R1-02", "R1-03"]
        assert "LOCATION:" not in issue.body
        assert "PRIORITY:" not in issue.body
        assert "DEPENDS:" not in issue.body
        assert "timeouts" in issue.body

    def test_no_metadata(self):
        content = "### Some issue\n\nJust prose here.\n"
        issues = extract_new_issues(content, 1, set())
        assert len(issues) == 1
        assert issues[0].location is None
        assert issues[0].priority == "LOW"
        assert issues[0].depends == []

    def test_partial_metadata_location_only(self):
        content = (
            "### Partial issue\n"
            "LOCATION: §2.3\n"
            "\n"
            "Only location provided.\n"
        )
        issues = extract_new_issues(content, 1, set())
        assert len(issues) == 1
        assert issues[0].location == "§2.3"
        assert issues[0].priority == "LOW"
        assert issues[0].depends == []

    def test_priority_case_insensitive(self):
        content = "### Issue\nPRIORITY: medium\n\nBody.\n"
        issues = extract_new_issues(content, 1, set())
        assert issues[0].priority == "MEDIUM"

    def test_depends_single(self):
        content = "### Issue\nDEPENDS: R1-01\n\nBody.\n"
        issues = extract_new_issues(content, 1, set())
        assert issues[0].depends == ["R1-01"]

    def test_multiple_issues_each_with_metadata(self):
        content = (
            "### First issue\n"
            "LOCATION: §1.1\n"
            "PRIORITY: HIGH\n"
            "\n"
            "First body.\n"
            "\n"
            "### Second issue\n"
            "LOCATION: §2.2\n"
            "PRIORITY: LOW\n"
            "\n"
            "Second body.\n"
        )
        issues = extract_new_issues(content, 1, set())
        assert len(issues) == 2
        assert issues[0].location == "§1.1"
        assert issues[0].priority == "HIGH"
        assert issues[1].location == "§2.2"
        assert issues[1].priority == "LOW"

    def test_metadata_lines_stripped_from_body(self):
        content = (
            "### Issue with all metadata\n"
            "LOCATION: §3.1\n"
            "PRIORITY: MEDIUM\n"
            "DEPENDS: R1-01\n"
            "\n"
            "Actual prose content.\n"
        )
        issues = extract_new_issues(content, 1, set())
        body = issues[0].body
        assert "LOCATION:" not in body
        assert "PRIORITY:" not in body
        assert "DEPENDS:" not in body
        assert "Actual prose content." in body

    def test_existing_issue_extraction_still_works(self):
        content = (
            "## Overview\n\nBrief overview.\n\n"
            "### R1-01: Missing error handling\n\n"
            "Parser doesn't handle malformed input.\n\n"
            "### R1-02: Wrong status code\n\n"
            "Returns 200 on failure.\n"
        )
        issues = extract_new_issues(content, 1, set())
        assert len(issues) == 2
        assert "Missing error handling" in issues[0].title
        assert "Wrong status code" in issues[1].title


class TestEvidenceExtraction:

    def test_single_evidence(self):
        content = (
            "### R1-01: FIXED\n"
            "EVIDENCE: §4.1 | commit:abc123\n"
            "\n"
            "Updated the section.\n"
        )
        responses = extract_issue_responses(content)
        assert len(responses) == 1
        assert len(responses[0].evidence) == 1
        e = responses[0].evidence[0]
        assert e.location == "§4.1"
        assert e.commit == "abc123"
        assert e.lines is None

    def test_multiple_evidence(self):
        content = (
            "### R1-01: FIXED\n"
            "EVIDENCE: §4.1 | commit:abc123\n"
            "EVIDENCE: §4.2 | commit:abc123\n"
            "\n"
            "Updated both sections.\n"
        )
        responses = extract_issue_responses(content)
        assert len(responses[0].evidence) == 2
        assert responses[0].evidence[0].location == "§4.1"
        assert responses[0].evidence[1].location == "§4.2"

    def test_evidence_with_lines(self):
        content = (
            "### R1-01: FIXED\n"
            "EVIDENCE: src/Main.java | commit:def456 | lines:45-78\n"
            "\n"
            "Fixed the code.\n"
        )
        responses = extract_issue_responses(content)
        e = responses[0].evidence[0]
        assert e.location == "src/Main.java"
        assert e.commit == "def456"
        assert e.lines == "45-78"

    def test_no_evidence_on_fixed(self):
        content = "### R1-01: FIXED\n\nFixed it without evidence.\n"
        responses = extract_issue_responses(content)
        assert responses[0].evidence == []

    def test_evidence_not_extracted_on_rejected(self):
        content = (
            "### R1-01: REJECTED\n"
            "EVIDENCE: §4.1 | commit:abc123\n"
            "\n"
            "Not a real issue.\n"
        )
        responses = extract_issue_responses(content)
        assert responses[0].evidence == []

    def test_evidence_stripped_from_body(self):
        content = (
            "### R1-01: FIXED\n"
            "EVIDENCE: §4.1 | commit:abc123\n"
            "\n"
            "Updated the section.\n"
        )
        responses = extract_issue_responses(content)
        assert "EVIDENCE:" not in responses[0].body
        assert "Updated the section." in responses[0].body

    def test_existing_section_ref_still_extracted(self):
        content = (
            "### R1-01: FIXED\n"
            "\n"
            "Updated §3.2 with error handling.\n"
        )
        responses = extract_issue_responses(content)
        assert responses[0].section_ref == "3.2"
        assert responses[0].evidence == []


class TestConfirmationVerdict:

    def test_resolved(self):
        content = "- R1-01: resolved\n"
        confs = extract_confirmations(content)
        assert len(confs) == 1
        assert confs[0].verdict == "resolved"
        assert confs[0].reason == ""

    def test_accepted(self):
        content = "- R1-02: accepted\n"
        confs = extract_confirmations(content)
        assert confs[0].verdict == "accepted"

    def test_still_open(self):
        content = "- R1-03: still open — needs more work\n"
        confs = extract_confirmations(content)
        assert confs[0].verdict == "contested"
        assert "needs more work" in confs[0].reason

    def test_multiple_confirmations(self):
        content = (
            "- R1-01: resolved — fix is correct\n"
            "- R1-02: accepted — envelope pattern is fine\n"
            "- R1-03: still open — race condition not addressed\n"
        )
        confs = extract_confirmations(content)
        assert len(confs) == 3
        assert confs[0].verdict == "resolved"
        assert confs[1].verdict == "accepted"
        assert confs[2].verdict == "contested"

    def test_verdict_has_no_boolean_fields(self):
        field_names = {f.name for f in dataclass_fields(Confirmation)}
        assert "is_resolved" not in field_names
        assert "is_accepted" not in field_names
        assert "verdict" in field_names
