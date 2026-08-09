"""Tests for decision review type integration."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

_SKILL_DIR = Path(__file__).parent.parent
if "adversarial_design_review" not in sys.modules:
    _spec = importlib.util.spec_from_file_location(
        "adversarial_design_review",
        _SKILL_DIR / "__init__.py",
        submodule_search_locations=[str(_SKILL_DIR)],
    )
    if _spec and _spec.loader:
        _mod = importlib.util.module_from_spec(_spec)
        sys.modules["adversarial_design_review"] = _mod
        _spec.loader.exec_module(_mod)


class TestDecisionReviewConstants:
    def test_decision_in_review_modes(self):
        from adversarial_design_review.review import REVIEW_MODES
        assert "decision" in REVIEW_MODES

    def test_decision_in_review_types(self):
        from adversarial_design_review.review import REVIEW_TYPES
        assert "decision" in REVIEW_TYPES

    def test_decision_type_defaults(self):
        from adversarial_design_review.review import TYPE_DEFAULTS
        assert TYPE_DEFAULTS["decision"] == "standard"

    def test_decision_type_to_mode(self):
        from adversarial_design_review.review import TYPE_TO_MODE
        assert TYPE_TO_MODE["decision"] == "decision"

    def test_decision_mode_to_type(self):
        from adversarial_design_review.review import MODE_TO_TYPE
        assert MODE_TO_TYPE["decision"] == ("decision", "standard")

    def test_decision_mode_defaults(self):
        from adversarial_design_review.review import MODE_DEFAULTS
        assert "decision" in MODE_DEFAULTS
        assert MODE_DEFAULTS["decision"]["max_rounds"] == 3
        assert MODE_DEFAULTS["decision"]["min_rounds"] == 2


class TestDecisionReviewPrompts:
    def test_reviewer_prompt_dispatches_for_decision(self):
        from adversarial_design_review.prompts import build_reviewer_prompt
        prompt = build_reviewer_prompt(
            round_num=1, focus_items=[], handover_path=None,
            mode="decision", workspace_root="/tmp/test",
            spec_path="/tmp/decisions.md",
        )
        assert "decision" in prompt.lower()
        assert "rationale" in prompt.lower()
        assert "SOURCES.md" in prompt

    def test_implementor_prompt_dispatches_for_decision(self):
        from adversarial_design_review.prompts import build_implementor_prompt
        prompt = build_implementor_prompt(
            round_num=1, focus_items=[], mode="decision",
            workspace_root="/tmp/test", spec_path="/tmp/decisions.md",
        )
        assert "decision" in prompt.lower()

    def test_reviewer_prompt_includes_calibration(self):
        from adversarial_design_review.prompts import build_reviewer_prompt
        prompt = build_reviewer_prompt(
            round_num=1, focus_items=[], handover_path=None,
            mode="decision", workspace_root="/tmp/test",
            spec_path="/tmp/decisions.md",
        )
        assert "quick" in prompt.lower()
        assert "scrutiny" in prompt.lower()

    def test_reviewer_round2_includes_evidence(self):
        from adversarial_design_review.prompts import build_reviewer_prompt
        prompt = build_reviewer_prompt(
            round_num=2, focus_items=["R1-01"],
            handover_path=None, mode="decision",
            workspace_root="/tmp/test",
            spec_path="/tmp/decisions.md",
        )
        assert "EVIDENCE REQUIRED" in prompt


class TestDecisionReviewSetup:
    def test_mode_generators_has_decision(self):
        from adversarial_design_review.setup import _MODE_GENERATORS
        assert "decision" in _MODE_GENERATORS
        assert "reviewer" in _MODE_GENERATORS["decision"]
        assert "implementor" in _MODE_GENERATORS["decision"]

    def test_decision_reviewer_md_generated(self):
        from adversarial_design_review.setup import _MODE_GENERATORS
        md = _MODE_GENERATORS["decision"]["reviewer"]()
        assert "Decision" in md
        assert "rationale" in md.lower()

    def test_decision_implementor_md_generated(self):
        from adversarial_design_review.setup import _MODE_GENERATORS
        md = _MODE_GENERATORS["decision"]["implementor"]()
        assert "decision" in md.lower()
        assert "defend" in md.lower() or "pivot" in md.lower()


class TestTrackerDecisionParsing:
    def test_extract_section_number_decision_format(self):
        from adversarial_design_review.tracker import _extract_section_number
        assert _extract_section_number("D3") == "D3"
        assert _extract_section_number("EVIDENCE: D3 | commit:abc") == "D3"

    def test_extract_section_number_preserves_existing(self):
        from adversarial_design_review.tracker import _extract_section_number
        assert _extract_section_number("§4.1") == "4.1"
        assert _extract_section_number("§2") == "2"

    def test_find_section_range_decision_heading(self):
        from adversarial_design_review.tracker import _find_section_range
        content = "# Decisions\n\n## D1: First\n\nContent here\n\n## D2: Second\n\nMore content"
        result = _find_section_range(content, "D1")
        assert result is not None
        assert result[0] == 3

    def test_find_section_range_preserves_existing(self):
        from adversarial_design_review.tracker import _find_section_range
        content = "# Spec\n\n## S1: Intro\n\nContent\n\n## S2: Design\n\nMore"
        result = _find_section_range(content, "1")
        assert result is not None
        assert result[0] == 3


class TestAnnotateSkipForDecision:
    def test_annotate_skips_decision_headings(self):
        from adversarial_design_review.setup import annotate_spec_headings
        content = "# Decisions\n\n## D1: First choice\n\nContent\n\n## D2: Second choice\n\nMore"
        result = annotate_spec_headings(content, mode="decision")
        assert "## D1: First choice" in result
        assert "## S1:" not in result

    def test_annotate_works_normally_for_other_modes(self):
        from adversarial_design_review.setup import annotate_spec_headings
        content = "# Spec\n\n## Intro\n\nContent\n\n## Design\n\nMore"
        result = annotate_spec_headings(content)
        assert "## S1: Intro" in result
        assert "## S2: Design" in result
