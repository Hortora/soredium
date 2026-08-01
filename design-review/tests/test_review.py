"""Tests for JSONL event building, writing, and CLI parsing."""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from parser import Confirmation, Evidence, Issue, IssueResponse, SettledDecision
from review import (
    _build_reviewer_events,
    _build_implementor_events,
    _build_chunk_start_event,
    _build_chunk_end_event,
    _write_jsonl,
    parse_args,
)
from prompts import build_reviewer_prompt


class TestBuildReviewerEvents:

    def test_issues_become_issue_raised_events(self):
        issues = [
            Issue("R1-01", "Missing handler", "Body text",
                  location="§4.1", priority="HIGH", depends=["R1-02"]),
        ]
        signal = ("CONTINUE", None)
        events = _build_reviewer_events(1, issues, signal, [], [],
                                         "reviewer-1.md")
        raised = [e for e in events if e["event"] == "issue_raised"]
        assert len(raised) == 1
        assert raised[0]["id"] == "R1-01"
        assert raised[0]["location"] == "§4.1"
        assert raised[0]["priority"] == "HIGH"
        assert raised[0]["depends"] == ["R1-02"]
        assert raised[0]["round"] == 1
        assert raised[0]["body"] == "Body text"
        assert raised[0]["scope"] is None

    def test_signal_event(self):
        events = _build_reviewer_events(1, [], ("CONTINUE", None), [], [],
                                         "reviewer-1.md")
        signals = [e for e in events if e["event"] == "round_signal"]
        assert len(signals) == 1
        assert signals[0]["signal"] == "CONTINUE"
        assert signals[0]["role"] == "reviewer"
        assert signals[0]["round"] == 1

    def test_decision_needed_signal(self):
        events = _build_reviewer_events(1, [], ("DECISION_NEEDED", "concurrency model"),
                                         [], [], "reviewer-1.md")
        signals = [e for e in events if e["event"] == "round_signal"]
        assert signals[0]["signal"] == "DECISION_NEEDED"
        assert signals[0]["description"] == "concurrency model"

    def test_assumption_events(self):
        events = _build_reviewer_events(1, [], ("CONTINUE", None),
                                         ["Assumption one"], [],
                                         "reviewer-1.md")
        assumptions = [e for e in events if e["event"] == "assumption"]
        assert len(assumptions) == 1
        assert assumptions[0]["text"] == "Assumption one"
        assert assumptions[0]["source"] == "reviewer-1.md"

    def test_confirmation_events(self):
        confs = [
            Confirmation("R1-01", "resolved", ""),
            Confirmation("R1-02", "accepted", ""),
            Confirmation("R1-03", "contested", "needs work"),
        ]
        events = _build_reviewer_events(2, [], ("CONTINUE", None), [], confs,
                                         "reviewer-2.md")
        conf_events = [e for e in events if e["event"] == "confirmation"]
        assert len(conf_events) == 3
        assert conf_events[0]["verdict"] == "resolved"
        assert conf_events[1]["verdict"] == "accepted"
        assert conf_events[2]["verdict"] == "contested"
        assert conf_events[2]["reason"] == "needs work"

    def test_issue_with_no_metadata(self):
        issues = [Issue("R1-01", "Simple issue", "Body")]
        events = _build_reviewer_events(1, issues, ("CONTINUE", None), [], [],
                                         "reviewer-1.md")
        raised = [e for e in events if e["event"] == "issue_raised"]
        assert raised[0]["location"] is None
        assert raised[0]["priority"] == "LOW"
        assert raised[0]["depends"] == []


class TestBuildImplementorEvents:

    def test_fixed_with_evidence(self):
        responses = [
            IssueResponse("R1-01", "FIXED", "4.1", "Updated section",
                          "Full body", [Evidence("§4.1", "abc123")]),
        ]
        events = _build_implementor_events(1, responses, ("CONTINUE", None),
                                            [], [])
        fixed = [e for e in events if e["event"] == "issue_fixed"]
        assert len(fixed) == 1
        assert fixed[0]["evidence"][0]["location"] == "§4.1"
        assert fixed[0]["evidence"][0]["commit"] == "abc123"
        assert fixed[0]["sectionRef"] == "4.1"

    def test_rejected(self):
        responses = [
            IssueResponse("R1-01", "REJECTED", rationale="Not a bug"),
        ]
        events = _build_implementor_events(1, responses, ("CONTINUE", None),
                                            [], [])
        rejected = [e for e in events if e["event"] == "issue_rejected"]
        assert len(rejected) == 1
        assert rejected[0]["rationale"] == "Not a bug"

    def test_escalated(self):
        responses = [
            IssueResponse("R1-02", "ESCALATED", rationale="Needs decision"),
        ]
        events = _build_implementor_events(1, responses, ("CONTINUE", None),
                                            [], [])
        escalated = [e for e in events if e["event"] == "issue_escalated"]
        assert len(escalated) == 1

    def test_settled_decision_events(self):
        settled = [SettledDecision("Use response-envelope pattern", "R1-02")]
        events = _build_implementor_events(1, [], ("CONTINUE", None), [], settled)
        sd_events = [e for e in events if e["event"] == "settled_decision"]
        assert len(sd_events) == 1
        assert sd_events[0]["text"] == "Use response-envelope pattern"
        assert sd_events[0]["fromIssue"] == "R1-02"

    def test_assumption_events(self):
        events = _build_implementor_events(1, [], ("CONTINUE", None),
                                            ["Some assumption"], [])
        assumptions = [e for e in events if e["event"] == "assumption"]
        assert len(assumptions) == 1
        assert assumptions[0]["source"] == "implementor-1.md"

    def test_fixed_without_evidence(self):
        responses = [
            IssueResponse("R1-01", "FIXED", body="Fixed without evidence"),
        ]
        events = _build_implementor_events(1, responses, ("CONTINUE", None),
                                            [], [])
        fixed = [e for e in events if e["event"] == "issue_fixed"]
        assert fixed[0]["evidence"] == []


class TestWriteJsonl:

    def test_writes_schema_version_and_events(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            (ws / "responses").mkdir()
            events = [{"event": "issue_raised", "round": 1, "id": "R1-01"}]
            _write_jsonl(ws, "reviewer", 1, events)

            jsonl_path = ws / "responses" / "reviewer-1.jsonl"
            assert jsonl_path.exists()
            lines = jsonl_path.read_text().strip().split("\n")
            assert len(lines) == 2
            header = json.loads(lines[0])
            assert header["event"] == "schema_version"
            assert header["version"] == 1
            event = json.loads(lines[1])
            assert event["event"] == "issue_raised"

    def test_atomic_write(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            (ws / "responses").mkdir()
            events = [{"event": "test"}]
            _write_jsonl(ws, "reviewer", 1, events)
            tmp_path = ws / "responses" / "reviewer-1.jsonl.tmp"
            assert not tmp_path.exists()

    def test_empty_events(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            (ws / "responses").mkdir()
            _write_jsonl(ws, "reviewer", 1, [])

            jsonl_path = ws / "responses" / "reviewer-1.jsonl"
            lines = jsonl_path.read_text().strip().split("\n")
            assert len(lines) == 1
            header = json.loads(lines[0])
            assert header["event"] == "schema_version"


class TestChunkEvents:

    def test_chunk_start_event(self):
        event = _build_chunk_start_event(round_num=1, priority="HIGH",
                                          chunk_index=0, total_chunks=3,
                                          item_count=4)
        assert event["event"] == "chunk_start"
        assert event["round"] == 1
        assert event["priority"] == "HIGH"
        assert event["chunkIndex"] == 0
        assert event["totalChunks"] == 3
        assert event["itemCount"] == 4

    def test_chunk_end_event(self):
        event = _build_chunk_end_event(round_num=1, priority="HIGH",
                                        chunk_index=0, addressed=3, skipped=1)
        assert event["event"] == "chunk_end"
        assert event["round"] == 1
        assert event["priority"] == "HIGH"
        assert event["addressed"] == 3
        assert event["skipped"] == 1


class TestParseArgs:

    def _parse(self, argv: list[str]):
        with patch("sys.argv", ["review.py"] + argv):
            return parse_args()

    def test_type_flag_accepted(self):
        args = self._parse(["--spec", "x.md", "--title", "t",
                            "--source-dirs", "/tmp", "--type", "coherence"])
        assert args.review_type == "coherence"

    def test_all_types_accepted(self):
        for t in ("coherence", "structure", "robustness", "conformance", "readiness"):
            args = self._parse(["--spec", "x.md", "--title", "t",
                                "--source-dirs", "/tmp", "--type", t])
            assert args.review_type == t

    def test_degree_flag_accepted(self):
        args = self._parse(["--spec", "x.md", "--title", "t",
                            "--source-dirs", "/tmp", "--type", "structure",
                            "--degree", "adversarial"])
        assert args.degree == "adversarial"

    def test_degree_presets_applied(self):
        args = self._parse(["--spec", "x.md", "--title", "t",
                            "--source-dirs", "/tmp", "--type", "coherence",
                            "--degree", "adversarial"])
        assert args.max_rounds == 6
        assert args.min_rounds == 4

    def test_default_degree_per_type(self):
        args = self._parse(["--spec", "x.md", "--title", "t",
                            "--source-dirs", "/tmp", "--type", "robustness"])
        assert args.degree == "adversarial"
        assert args.max_rounds == 6

    def test_default_degree_coherence_is_light(self):
        args = self._parse(["--spec", "x.md", "--title", "t",
                            "--source-dirs", "/tmp", "--type", "coherence"])
        assert args.degree == "light"
        assert args.max_rounds == 1

    def test_default_degree_structure_is_standard(self):
        args = self._parse(["--spec", "x.md", "--title", "t",
                            "--source-dirs", "/tmp", "--type", "structure"])
        assert args.degree == "standard"
        assert args.max_rounds == 3

    def test_backward_compat_mode_maps_to_type(self):
        args = self._parse(["--spec", "x.md", "--title", "t",
                            "--source-dirs", "/tmp", "--mode", "pre-review"])
        assert args.review_type == "coherence"

    def test_backward_compat_spec_review_maps_to_structure(self):
        args = self._parse(["--spec", "x.md", "--title", "t",
                            "--source-dirs", "/tmp", "--mode", "spec-review"])
        assert args.review_type == "structure"

    def test_backward_compat_depth_alias(self):
        args = self._parse(["--spec", "x.md", "--title", "t",
                            "--source-dirs", "/tmp", "--type", "structure",
                            "--depth", "light"])
        assert args.degree == "light"

    def test_no_flags_defaults_to_structure_adversarial(self):
        args = self._parse(["--spec", "x.md", "--title", "t",
                            "--source-dirs", "/tmp"])
        assert args.review_type == "structure"
        assert args.degree == "adversarial"

    def test_mode_kept_for_internal_use(self):
        args = self._parse(["--spec", "x.md", "--title", "t",
                            "--source-dirs", "/tmp", "--type", "conformance"])
        assert args.mode == "code-review"

    def test_readiness_maps_to_final_review_mode(self):
        args = self._parse(["--spec", "x.md", "--title", "t",
                            "--source-dirs", "/tmp", "--type", "readiness"])
        assert args.mode == "final-review"


class TestReviewerBriefsByType:

    def test_coherence_brief_focuses_on_completeness(self):
        prompt = build_reviewer_prompt(
            round_num=1, focus_items=[], handover_path=None,
            mode="coherence",
        )
        assert "completeness" in prompt.lower() or "complete" in prompt.lower()

    def test_structure_brief_focuses_on_decomposition(self):
        prompt = build_reviewer_prompt(
            round_num=1, focus_items=[], handover_path=None,
            mode="structure",
        )
        assert "decomposition" in prompt.lower() or "boundaries" in prompt.lower()

    def test_robustness_brief_focuses_on_failure(self):
        prompt = build_reviewer_prompt(
            round_num=1, focus_items=[], handover_path=None,
            mode="robustness",
        )
        assert "failure" in prompt.lower() or "break" in prompt.lower()

    def test_light_degree_includes_escalation_instruction(self):
        prompt = build_reviewer_prompt(
            round_num=1, focus_items=[], handover_path=None,
            mode="coherence", degree="light",
        )
        assert "ESCALATE:" in prompt

    def test_standard_degree_includes_escalation(self):
        prompt = build_reviewer_prompt(
            round_num=1, focus_items=[], handover_path=None,
            mode="structure", degree="standard",
        )
        assert "ESCALATE:" in prompt

    def test_adversarial_degree_no_escalation(self):
        prompt = build_reviewer_prompt(
            round_num=1, focus_items=[], handover_path=None,
            mode="robustness", degree="adversarial",
        )
        assert "ESCALATE:" not in prompt

    def test_deep_degree_no_escalation(self):
        prompt = build_reviewer_prompt(
            round_num=1, focus_items=[], handover_path=None,
            mode="robustness", degree="deep",
        )
        assert "ESCALATE:" not in prompt

    def test_coherence_does_not_include_adversarial_framing(self):
        prompt = build_reviewer_prompt(
            round_num=1, focus_items=[], handover_path=None,
            mode="coherence", degree="light",
        )
        assert "try to break" not in prompt.lower()
        assert "adversarial design review" not in prompt.lower()

    def test_crosscutting_brief_mentions_contradictions(self):
        prompt = build_reviewer_prompt(
            round_num=1, focus_items=[], handover_path=None,
            mode="crosscutting",
        )
        assert "contradiction" in prompt.lower()
        assert "intersection" in prompt.lower()

    def test_crosscutting_brief_does_not_re_review(self):
        prompt = build_reviewer_prompt(
            round_num=1, focus_items=[], handover_path=None,
            mode="crosscutting",
        )
        assert "not re-review" in prompt.lower() or "do not re-review" in prompt.lower()

    def test_crosscutting_light_includes_escalation(self):
        prompt = build_reviewer_prompt(
            round_num=1, focus_items=[], handover_path=None,
            mode="crosscutting", degree="light",
        )
        assert "ESCALATE:" in prompt


class TestParseArgsCrosscutting:

    def _parse(self, argv: list[str]):
        with patch("sys.argv", ["review.py"] + argv):
            return parse_args()

    def test_crosscutting_type_accepted(self):
        args = self._parse(["--spec", "x.md", "--title", "t",
                            "--source-dirs", "/tmp", "--type", "crosscutting"])
        assert args.review_type == "crosscutting"

    def test_crosscutting_maps_to_crosscutting_mode(self):
        args = self._parse(["--spec", "x.md", "--title", "t",
                            "--source-dirs", "/tmp", "--type", "crosscutting"])
        assert args.mode == "crosscutting"

    def test_crosscutting_default_degree_is_standard(self):
        args = self._parse(["--spec", "x.md", "--title", "t",
                            "--source-dirs", "/tmp", "--type", "crosscutting"])
        assert args.degree == "standard"

    def test_all_types_includes_crosscutting(self):
        for t in ("coherence", "structure", "robustness", "conformance",
                  "readiness", "crosscutting"):
            args = self._parse(["--spec", "x.md", "--title", "t",
                                "--source-dirs", "/tmp", "--type", t])
            assert args.review_type == t
