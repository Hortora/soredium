"""Tests for tracker enrichment and evidence verification."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from parser import Evidence
from tracker import (
    EvidenceResult,
    IssueStatus,
    Tracker,
    verify_evidence_against_diff,
)


class TestTrackerEnrichment:

    def test_add_issue_with_metadata(self):
        t = Tracker(project_name="test")
        t.add_issue("R1-01", "Test issue", round_raised=1,
                     location="§4.1", priority="HIGH", depends=["R1-02"])
        issue = t.get_issue("R1-01")
        assert issue.location == "§4.1"
        assert issue.priority == "HIGH"
        assert issue.depends == ["R1-02"]

    def test_add_issue_without_metadata_uses_defaults(self):
        t = Tracker(project_name="test")
        t.add_issue("R1-01", "Test issue", round_raised=1)
        issue = t.get_issue("R1-01")
        assert issue.location == ""
        assert issue.priority == "LOW"
        assert issue.depends == []

    def test_render_includes_metadata(self):
        t = Tracker(project_name="test")
        t.add_issue("R1-01", "Test issue", round_raised=1,
                     location="§4.1", priority="HIGH", depends=["R1-02"])
        rendered = t.render()
        assert "**Location:** §4.1" in rendered
        assert "**Priority:** HIGH" in rendered
        assert "**Depends:** R1-02" in rendered

    def test_render_omits_default_metadata(self):
        t = Tracker(project_name="test")
        t.add_issue("R1-01", "Test issue", round_raised=1)
        rendered = t.render()
        assert "**Location:**" not in rendered
        assert "**Priority:**" not in rendered
        assert "**Depends:**" not in rendered

    def test_render_omits_low_priority(self):
        t = Tracker(project_name="test")
        t.add_issue("R1-01", "Test issue", round_raised=1, priority="LOW")
        rendered = t.render()
        assert "**Priority:**" not in rendered


class TestVerifyEvidenceAgainstDiff:

    def test_empty_evidence_returns_not_verified(self):
        result = verify_evidence_against_diff([], "", "")
        assert not result.verified
        assert "no evidence provided" in result.note

    def test_section_found_in_diff(self):
        spec = "# Spec\n\n## §4.1 Payment Flow\n\nContent here.\n\n## §4.2 Next\n"
        diff = (
            "--- a/spec.md\n"
            "+++ b/spec.md\n"
            "@@ -3,3 +3,4 @@\n"
            " ## §4.1 Payment Flow\n"
            " \n"
            "-Content here.\n"
            "+Updated content here.\n"
            "+Added line.\n"
        )
        evidence = [Evidence(location="§4.1", commit="abc123")]
        result = verify_evidence_against_diff(evidence, diff, spec)
        assert result.verified

    def test_section_not_in_diff(self):
        spec = "# Spec\n\n## §4.1 Payment\n\nContent.\n\n## §4.2 Next\n\nOther.\n"
        diff = (
            "--- a/spec.md\n"
            "+++ b/spec.md\n"
            "@@ -7,2 +7,3 @@\n"
            " ## §4.2 Next\n"
            " \n"
            "-Other.\n"
            "+Changed other.\n"
        )
        evidence = [Evidence(location="§4.1", commit="abc123")]
        result = verify_evidence_against_diff(evidence, diff, spec)
        assert not result.verified
        assert "§4.1" in result.note

    def test_section_not_found_in_spec(self):
        spec = "# Spec\n\n## §1.1 Intro\n\nContent.\n"
        diff = "@@ -1,1 +1,1 @@\n-old\n+new\n"
        evidence = [Evidence(location="§9.9", commit="abc123")]
        result = verify_evidence_against_diff(evidence, diff, spec)
        assert not result.verified
        assert "not found in spec" in result.note

    def test_non_section_location_no_crash(self):
        spec = "# Spec\n\nSome content.\n"
        diff = "@@ -1,1 +1,1 @@\n-old\n+new\n"
        evidence = [Evidence(location="some-file.txt", commit="abc123")]
        result = verify_evidence_against_diff(evidence, diff, spec)
        assert not result.verified

    def test_subsection_match(self):
        spec = (
            "# Spec\n\n"
            "## §4 Payment\n\n"
            "Overview.\n\n"
            "### §4.1 Flow\n\n"
            "Flow content.\n\n"
            "### §4.2 Errors\n\n"
            "Error content.\n"
        )
        diff = (
            "@@ -7,2 +7,3 @@\n"
            " ### §4.1 Flow\n"
            " \n"
            "-Flow content.\n"
            "+Updated flow content.\n"
        )
        evidence = [Evidence(location="§4.1", commit="abc123")]
        result = verify_evidence_against_diff(evidence, diff, spec)
        assert result.verified


class TestVerifyAgainstDiffDeleted:

    def test_verify_against_diff_no_longer_exists(self):
        import tracker
        assert not hasattr(tracker, "verify_against_diff")
