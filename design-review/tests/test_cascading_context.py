"""Tests for cascading context injection in ordered dimensional reviews."""

from __future__ import annotations

import importlib.util
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


class TestCascadingContext:
    def test_prior_dimension_findings_injected(self, tmp_path):
        """context.md includes prior dimension findings when arch-files have .mode."""
        from adversarial_design_review.setup import _generate_context_md

        structure_ws = tmp_path / "structure-ws"
        structure_ws.mkdir()
        (structure_ws / ".mode").write_text("structure")
        (structure_ws / "tracker.md").write_text(
            "## Issues\n\n"
            "### R1-01: Unclear boundary between scanner and lifecycle\n"
            "- **Status:** VERIFIED\n"
            "- **Location:** §2.1\n"
            "- **Priority:** HIGH\n\n"
            "### R1-02: Circular dependency\n"
            "- **Status:** ADDRESSED\n"
            "- **Priority:** MEDIUM\n"
        )

        coherence_ws = tmp_path / "coherence-ws"
        coherence_ws.mkdir()
        (coherence_ws / "responses").mkdir()
        (coherence_ws / "agents" / "reviewer").mkdir(parents=True)
        (coherence_ws / "agents" / "implementor").mkdir(parents=True)

        _generate_context_md(
            coherence_ws,
            source_dirs=["/tmp/project"],
            spec_path=Path("/tmp/spec.md"),
            arch_files=[str(structure_ws / "tracker.md")],
        )

        context = (coherence_ws / "context.md").read_text()
        assert "Prior dimension findings" in context
        assert "STR-R1-01" in context
        assert "Unclear boundary" in context
        assert "STR-R1-02" in context

    def test_multiple_prior_dimensions(self, tmp_path):
        """context.md includes findings from multiple prior dimensions."""
        from adversarial_design_review.setup import _generate_context_md

        structure_ws = tmp_path / "structure-ws"
        structure_ws.mkdir()
        (structure_ws / ".mode").write_text("structure")
        (structure_ws / "tracker.md").write_text(
            "## Issues\n\n"
            "### R1-01: Boundary issue\n"
            "- **Status:** VERIFIED\n"
            "- **Priority:** HIGH\n"
        )

        coherence_ws = tmp_path / "coherence-ws"
        coherence_ws.mkdir()
        (coherence_ws / ".mode").write_text("coherence")
        (coherence_ws / "tracker.md").write_text(
            "## Issues\n\n"
            "### R1-01: Missing requirement\n"
            "- **Status:** VERIFIED\n"
            "- **Priority:** MEDIUM\n"
        )

        robustness_ws = tmp_path / "robustness-ws"
        robustness_ws.mkdir()
        (robustness_ws / "responses").mkdir()
        (robustness_ws / "agents" / "reviewer").mkdir(parents=True)
        (robustness_ws / "agents" / "implementor").mkdir(parents=True)

        _generate_context_md(
            robustness_ws,
            source_dirs=["/tmp/project"],
            spec_path=Path("/tmp/spec.md"),
            arch_files=[
                str(structure_ws / "tracker.md"),
                str(coherence_ws / "tracker.md"),
            ],
        )

        context = (robustness_ws / "context.md").read_text()
        assert "STR-R1-01" in context
        assert "COH-R1-01" in context
        assert "Structure" in context
        assert "Coherence" in context

    def test_no_cascading_without_mode_file(self, tmp_path):
        """No cascading context when arch-files don't have .mode."""
        from adversarial_design_review.setup import _generate_context_md

        other_ws = tmp_path / "other-ws"
        other_ws.mkdir()
        (other_ws / "tracker.md").write_text(
            "## Issues\n\n### R1-01: Something\n- **Status:** OPEN\n"
        )

        target_ws = tmp_path / "target-ws"
        target_ws.mkdir()
        (target_ws / "responses").mkdir()
        (target_ws / "agents" / "reviewer").mkdir(parents=True)
        (target_ws / "agents" / "implementor").mkdir(parents=True)

        _generate_context_md(
            target_ws,
            source_dirs=["/tmp/project"],
            spec_path=Path("/tmp/spec.md"),
            arch_files=[str(other_ws / "tracker.md")],
        )

        context = (target_ws / "context.md").read_text()
        assert "Prior dimension findings" not in context

    def test_unknown_dimension_skipped(self, tmp_path):
        """Arch-files with unknown .mode values are included as regular arch-files, not cascading."""
        from adversarial_design_review.setup import _generate_context_md

        unknown_ws = tmp_path / "unknown-ws"
        unknown_ws.mkdir()
        (unknown_ws / ".mode").write_text("conformance")
        (unknown_ws / "tracker.md").write_text(
            "## Issues\n\n### R1-01: Something\n- **Status:** OPEN\n"
        )

        target_ws = tmp_path / "target-ws"
        target_ws.mkdir()
        (target_ws / "responses").mkdir()
        (target_ws / "agents" / "reviewer").mkdir(parents=True)
        (target_ws / "agents" / "implementor").mkdir(parents=True)

        _generate_context_md(
            target_ws,
            source_dirs=["/tmp/project"],
            spec_path=Path("/tmp/spec.md"),
            arch_files=[str(unknown_ws / "tracker.md")],
        )

        context = (target_ws / "context.md").read_text()
        assert "Prior dimension findings" not in context
        assert "Architectural Files" in context
