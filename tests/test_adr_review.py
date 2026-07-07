"""Tests for adversarial-design-review/review.py

Targets the bugs found in the full audit — F1 through F22.
These test the orchestration logic without invoking real claude sessions.
"""

from __future__ import annotations

from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_workspace(tmp_path: Path) -> Path:
    """Create a minimal workspace structure for testing."""
    ws = tmp_path / "test-project" / "test-review-20260629-120000"
    ws.mkdir(parents=True)
    (ws / "responses").mkdir()
    (ws / "decisions").mkdir()
    (ws / "handovers").mkdir()
    (ws / "agents" / "reviewer").mkdir(parents=True)
    (ws / "agents" / "implementor").mkdir(parents=True)
    return ws


def _write_reviewer(ws: Path, round_num: int, content: str) -> None:
    (ws / "responses" / f"reviewer-{round_num}.md").write_text(content)


def _write_implementor(ws: Path, round_num: int, content: str) -> None:
    (ws / "responses" / f"implementor-{round_num}.md").write_text(content)


# ---------------------------------------------------------------------------
# _detect_last_round
# ---------------------------------------------------------------------------

class TestDetectLastRound:

    def test_empty_workspace(self, tmp_path: Path) -> None:
        from adversarial_design_review.review import _detect_last_round

        ws = _make_workspace(tmp_path)
        last_round, reviewer_only = _detect_last_round(ws)
        assert last_round == 0
        assert reviewer_only is False

    def test_complete_round(self, tmp_path: Path) -> None:
        from adversarial_design_review.review import _detect_last_round

        ws = _make_workspace(tmp_path)
        _write_reviewer(ws, 1, "### Issue 1\nContent.\n\n---\nSIGNAL: CONTINUE\n")
        _write_implementor(ws, 1, "### R1-01: FIXED\nDone.\n\n---\nSIGNAL: CONTINUE\n")

        last_round, reviewer_only = _detect_last_round(ws)
        assert last_round == 1
        assert reviewer_only is False

    def test_partial_round(self, tmp_path: Path) -> None:
        from adversarial_design_review.review import _detect_last_round

        ws = _make_workspace(tmp_path)
        _write_reviewer(ws, 1, "### Issue 1\n\n---\nSIGNAL: CONTINUE\n")
        _write_implementor(ws, 1, "### R1-01: FIXED\n\n---\nSIGNAL: CONTINUE\n")
        _write_reviewer(ws, 2, "### New issue\n\n---\nSIGNAL: CONTINUE\n")

        last_round, reviewer_only = _detect_last_round(ws)
        assert last_round == 2
        assert reviewer_only is True

    def test_multiple_complete_rounds(self, tmp_path: Path) -> None:
        from adversarial_design_review.review import _detect_last_round

        ws = _make_workspace(tmp_path)
        for rn in range(1, 4):
            _write_reviewer(ws, rn, f"### Round {rn} issue\n\n---\nSIGNAL: CONTINUE\n")
            _write_implementor(ws, rn, f"### R{rn}-01: FIXED\n\n---\nSIGNAL: CONTINUE\n")

        last_round, reviewer_only = _detect_last_round(ws)
        assert last_round == 3
        assert reviewer_only is False

    def test_no_responses_dir(self, tmp_path: Path) -> None:
        from adversarial_design_review.review import _detect_last_round

        ws = tmp_path / "no-responses"
        ws.mkdir()
        last_round, reviewer_only = _detect_last_round(ws)
        assert last_round == 0
        assert reviewer_only is False


# ---------------------------------------------------------------------------
# _rebuild_tracker
# ---------------------------------------------------------------------------

class TestRebuildTracker:

    def test_rebuilds_from_response_files(self, tmp_path: Path) -> None:
        from adversarial_design_review.review import _rebuild_tracker
        from adversarial_design_review.tracker import Tracker, IssueStatus

        ws = _make_workspace(tmp_path)
        _write_reviewer(ws, 1, """\
### Missing aggregate boundary

The Invoice aggregate has no upper bound on line items.

### No failure mode for payment timeout

The spec defines PAYMENT_PENDING but no terminal failure state.

---
SIGNAL: CONTINUE
""")
        _write_implementor(ws, 1, """\
### R1-01: FIXED
Updated §2.3 with a maximum of 500 line items.

### R1-02: REJECTED
This is already handled by existing retry logic.

---
SIGNAL: CONTINUE
""")

        tracker = Tracker(project_name="test")
        _rebuild_tracker(ws, tracker, through_round=1)

        assert len(tracker.issues()) == 2
        assert tracker.get_issue("R1-01").status == IssueStatus.ADDRESSED
        assert tracker.get_issue("R1-02").status == IssueStatus.REJECTED

    def test_rebuild_with_confirmations(self, tmp_path: Path) -> None:
        from adversarial_design_review.review import _rebuild_tracker
        from adversarial_design_review.tracker import Tracker, IssueStatus

        ws = _make_workspace(tmp_path)
        _write_reviewer(ws, 1, "### Issue A\nContent.\n\n---\nSIGNAL: CONTINUE\n")
        _write_implementor(ws, 1, "### R1-01: FIXED\nUpdated §2.3.\n\n---\nSIGNAL: CONTINUE\n")
        _write_reviewer(ws, 2, """\
## Addressed Items
- R1-01: resolved

---
SIGNAL: CONTINUE
""")

        tracker = Tracker(project_name="test")
        _rebuild_tracker(ws, tracker, through_round=2)

        assert tracker.get_issue("R1-01").status == IssueStatus.VERIFIED

    def test_rebuild_with_checkpoint_deferrals(self, tmp_path: Path) -> None:
        """F17: Checkpoint deferrals should be preserved across resume."""
        from adversarial_design_review.review import _rebuild_tracker
        from adversarial_design_review.tracker import Tracker, IssueStatus

        ws = _make_workspace(tmp_path)
        _write_reviewer(ws, 1, "### Issue A\nContent.\n### Issue B\nMore.\n\n---\nSIGNAL: CONTINUE\n")
        _write_implementor(ws, 1, "### R1-01: FIXED\nDone.\n\n---\nSIGNAL: CONTINUE\n")

        # Simulate checkpoint deferral file
        checkpoint = ws / "responses" / "checkpoint-1.md"
        checkpoint.write_text("### R1-02: ESCALATED\n\n---\nSIGNAL: CONTINUE\n")

        tracker = Tracker(project_name="test")
        _rebuild_tracker(ws, tracker, through_round=1)

        assert tracker.get_issue("R1-01").status == IssueStatus.ADDRESSED
        assert tracker.get_issue("R1-02").status == IssueStatus.DEFERRED

    def test_rebuild_checkpoint_force_defers_addressed_items(self, tmp_path: Path) -> None:
        """F17: Checkpoint should force-defer items in non-deferrable states."""
        from adversarial_design_review.review import _rebuild_tracker
        from adversarial_design_review.tracker import Tracker, IssueStatus

        ws = _make_workspace(tmp_path)
        _write_reviewer(ws, 1, "### Issue A\nContent.\n\n---\nSIGNAL: CONTINUE\n")
        _write_implementor(ws, 1, "### R1-01: FIXED\nDone §2.3.\n\n---\nSIGNAL: CONTINUE\n")

        # R1-01 is ADDRESSED after implementor, checkpoint tries to defer it
        checkpoint = ws / "responses" / "checkpoint-1.md"
        checkpoint.write_text("### R1-01: ESCALATED\n\n---\nSIGNAL: CONTINUE\n")

        tracker = Tracker(project_name="test")
        _rebuild_tracker(ws, tracker, through_round=1)

        # ADDRESSED → DEFERRED is invalid, but checkpoint forces it
        assert tracker.get_issue("R1-01").status == IssueStatus.DEFERRED
        assert "checkpoint" in tracker.get_issue("R1-01").notes

    def test_rebuild_partial_round(self, tmp_path: Path) -> None:
        """Rebuild including a partial round (reviewer only, no implementor)."""
        from adversarial_design_review.review import _rebuild_tracker
        from adversarial_design_review.tracker import Tracker, IssueStatus

        ws = _make_workspace(tmp_path)
        _write_reviewer(ws, 1, "### Issue A\nContent.\n\n---\nSIGNAL: CONTINUE\n")
        _write_implementor(ws, 1, "### R1-01: FIXED\nDone.\n\n---\nSIGNAL: CONTINUE\n")
        _write_reviewer(ws, 2, """\
### New issue B

Content for issue B.

## Addressed Items
- R1-01: resolved

---
SIGNAL: CONTINUE
""")
        # No implementor-2 — partial round

        tracker = Tracker(project_name="test")
        _rebuild_tracker(ws, tracker, through_round=2)

        assert len(tracker.issues()) == 2
        assert tracker.get_issue("R1-01").status == IssueStatus.VERIFIED
        assert tracker.get_issue("R2-01").status == IssueStatus.OPEN

    def test_rebuild_invalid_transitions_are_guarded(self, tmp_path: Path) -> None:
        """Reviewer confirming an OPEN issue (never addressed) should not crash."""
        from adversarial_design_review.review import _rebuild_tracker
        from adversarial_design_review.tracker import Tracker, IssueStatus

        ws = _make_workspace(tmp_path)
        _write_reviewer(ws, 1, "### Issue A\nContent.\n\n---\nSIGNAL: CONTINUE\n")
        # No implementor-1 — R1-01 stays OPEN
        _write_reviewer(ws, 2, """\
## Addressed Items
- R1-01: resolved

---
SIGNAL: CONTINUE
""")

        tracker = Tracker(project_name="test")
        _rebuild_tracker(ws, tracker, through_round=2)

        # OPEN → VERIFIED is invalid, should be silently skipped
        assert tracker.get_issue("R1-01").status == IssueStatus.OPEN

    def test_rebuild_accepted_rejection(self, tmp_path: Path) -> None:
        """Reviewer accepting an implementor's rejection should transition REJECTED → ACCEPTED."""
        from adversarial_design_review.review import _rebuild_tracker
        from adversarial_design_review.tracker import Tracker, IssueStatus

        ws = _make_workspace(tmp_path)
        _write_reviewer(ws, 1, "### Issue A\nContent.\n### Issue B\nMore.\n\n---\nSIGNAL: CONTINUE\n")
        _write_implementor(ws, 1, "### R1-01: FIXED\nDone §2.3.\n### R1-02: REJECTED\nAlready covered.\n\n---\nSIGNAL: CONTINUE\n")
        _write_reviewer(ws, 2, """\
## Addressed Items
- R1-01: resolved
- R1-02: **accepted** — the implementor's rejection is correct

---
SIGNAL: APPROVED
""")

        tracker = Tracker(project_name="test")
        _rebuild_tracker(ws, tracker, through_round=2)

        assert tracker.get_issue("R1-01").status == IssueStatus.VERIFIED
        assert tracker.get_issue("R1-02").status == IssueStatus.ACCEPTED

    def test_rebuild_resolved_on_rejected_falls_through_to_accepted(self, tmp_path: Path) -> None:
        """Reviewer says 'resolved' for a REJECTED item — should fall through to ACCEPTED."""
        from adversarial_design_review.review import _rebuild_tracker
        from adversarial_design_review.tracker import Tracker, IssueStatus

        ws = _make_workspace(tmp_path)
        _write_reviewer(ws, 1, "### Issue A\nContent.\n### Issue B\nMore.\n\n---\nSIGNAL: CONTINUE\n")
        _write_implementor(ws, 1, "### R1-01: FIXED\nDone §2.3.\n### R1-02: REJECTED\nNot applicable.\n\n---\nSIGNAL: CONTINUE\n")
        _write_reviewer(ws, 2, """\
## Addressed Items
- R1-01: resolved
- R1-02: resolved — rejection is well-supported

---
SIGNAL: APPROVED
""")

        tracker = Tracker(project_name="test")
        _rebuild_tracker(ws, tracker, through_round=2)

        assert tracker.get_issue("R1-01").status == IssueStatus.VERIFIED
        assert tracker.get_issue("R1-02").status == IssueStatus.ACCEPTED


# ---------------------------------------------------------------------------
# APPROVED gate — tracker state is authority
# ---------------------------------------------------------------------------

class TestApprovedGate:

    def test_approved_with_open_items_not_resolved(self, tmp_path: Path) -> None:
        """Simulates desiredstate scenario: reviewer approves while raising new issues."""
        from adversarial_design_review.review import _rebuild_tracker
        from adversarial_design_review.tracker import Tracker

        ws = _make_workspace(tmp_path)
        _write_reviewer(ws, 1, "### Issue A\nContent.\n\n---\nSIGNAL: CONTINUE\n")
        _write_implementor(ws, 1, "### R1-01: FIXED\nDone §2.3.\n\n---\nSIGNAL: CONTINUE\n")
        _write_reviewer(ws, 2, """\
## Addressed Items
- R1-01: resolved — §2.3 now caps at 500

### New edge case found

This is a new issue raised in the same breath as APPROVED.

---
SIGNAL: APPROVED
""")

        tracker = Tracker(project_name="test")
        _rebuild_tracker(ws, tracker, through_round=2)

        # R1-01 is VERIFIED, but R2-01 is OPEN — all_resolved must be False
        assert not tracker.all_resolved()
        assert tracker.get_focus_items() == ["R2-01"]

    def test_approved_with_all_terminal_is_resolved(self, tmp_path: Path) -> None:
        from adversarial_design_review.review import _rebuild_tracker
        from adversarial_design_review.tracker import Tracker

        ws = _make_workspace(tmp_path)
        _write_reviewer(ws, 1, "### Issue A\nContent.\n\n---\nSIGNAL: CONTINUE\n")
        _write_implementor(ws, 1, "### R1-01: FIXED\nDone §2.3.\n\n---\nSIGNAL: CONTINUE\n")
        _write_reviewer(ws, 2, """\
## Addressed Items
- R1-01: resolved — §2.3 now caps at 500

---
SIGNAL: APPROVED
""")

        tracker = Tracker(project_name="test")
        _rebuild_tracker(ws, tracker, through_round=2)

        assert tracker.all_resolved()
        assert tracker.get_focus_items() == []

    def test_approved_with_rejected_not_accepted_blocks(self, tmp_path: Path) -> None:
        """REJECTED items must be explicitly accepted before APPROVED is valid."""
        from adversarial_design_review.review import _rebuild_tracker
        from adversarial_design_review.tracker import Tracker, IssueStatus

        ws = _make_workspace(tmp_path)
        _write_reviewer(ws, 1, "### Issue A\nContent.\n### Issue B\nMore.\n\n---\nSIGNAL: CONTINUE\n")
        _write_implementor(ws, 1, "### R1-01: FIXED\nDone.\n### R1-02: REJECTED\nNot applicable.\n\n---\nSIGNAL: CONTINUE\n")
        _write_reviewer(ws, 2, """\
## Addressed Items
- R1-01: resolved — fix confirmed in §2.3

---
SIGNAL: APPROVED
""")
        # R1-02 silently dropped — reviewer didn't accept or contest the rejection

        tracker = Tracker(project_name="test")
        _rebuild_tracker(ws, tracker, through_round=2)

        assert tracker.get_issue("R1-01").status == IssueStatus.VERIFIED
        assert tracker.get_issue("R1-02").status == IssueStatus.REJECTED
        assert not tracker.all_resolved()
        assert "R1-02" in tracker.get_focus_items()


# ---------------------------------------------------------------------------
# ReviewAborted
# ---------------------------------------------------------------------------

class TestReviewAborted:

    def test_review_aborted_is_distinct_from_exception(self) -> None:
        """F3: ReviewAborted should not be caught by generic Exception handler."""
        from adversarial_design_review.review import ReviewAborted

        assert issubclass(ReviewAborted, Exception)
        # Verify it can be caught separately
        try:
            raise ReviewAborted("test abort")
        except ReviewAborted as e:
            assert "test abort" in str(e)

    def test_review_aborted_not_runtime_error(self) -> None:
        from adversarial_design_review.review import ReviewAborted

        assert not issubclass(ReviewAborted, RuntimeError)


# ---------------------------------------------------------------------------
# Pre-review mode prompts and templates
# ---------------------------------------------------------------------------

class TestPreReviewPrompts:

    def test_reviewer_prompt_is_approach_focused(self) -> None:
        from adversarial_design_review.prompts import build_reviewer_prompt

        prompt = build_reviewer_prompt(
            round_num=1, focus_items=[], handover_path=None,
            mode="pre-review", spec_path="/tmp/spec.md",
        )

        assert "pre-review" in prompt
        assert "APPROACH" in prompt
        assert "Do NOT update the spec" in prompt

    def test_reviewer_prompt_round2_has_evidence_requirement(self) -> None:
        from adversarial_design_review.prompts import build_reviewer_prompt

        prompt = build_reviewer_prompt(
            round_num=2, focus_items=["R1-01"], handover_path=None,
            mode="pre-review", spec_path="/tmp/spec.md",
        )

        assert "EVIDENCE REQUIRED" in prompt
        assert "R1-01" in prompt

    def test_implementor_prompt_is_approach_focused(self) -> None:
        from adversarial_design_review.prompts import build_implementor_prompt

        prompt = build_implementor_prompt(
            round_num=1, focus_items=[], mode="pre-review",
            workspace_root="/tmp/ws", spec_path="/tmp/spec.md",
        )

        assert "pre-review" in prompt
        assert "challenges" in prompt.lower()
        assert "pivot" in prompt.lower()

    def test_reviewer_prompt_convergence_override(self) -> None:
        from adversarial_design_review.prompts import build_reviewer_prompt

        prompt = build_reviewer_prompt(
            round_num=2, focus_items=["R1-01"], handover_path=None,
            convergence_override_ids=["R1-02", "R1-03"],
            mode="pre-review", spec_path="/tmp/spec.md",
        )

        assert "R1-02" in prompt
        assert "R1-03" in prompt
        assert "NOT in terminal state" in prompt


class TestPreReviewTemplates:

    def test_reviewer_template_has_approach_constraints(self) -> None:
        from adversarial_design_review.setup import _pre_review_reviewer_md

        md = _pre_review_reviewer_md()

        assert "Approach Reviewer" in md
        assert "simpler ways" in md.lower() or "simpler" in md.lower()
        assert "architectural trajectory" in md.lower() or "platform" in md.lower()
        assert "technical debt" in md.lower() or "age well" in md.lower()

    def test_implementor_template_has_approach_constraints(self) -> None:
        from adversarial_design_review.setup import _pre_review_implementor_md

        md = _pre_review_implementor_md()

        assert "Approach Author" in md
        assert "pivot" in md.lower()
        assert "DECISION_NEEDED" in md

    def test_reviewer_template_differs_from_spec_review(self) -> None:
        from adversarial_design_review.setup import _default_reviewer_md, _pre_review_reviewer_md

        spec_md = _default_reviewer_md()
        pre_md = _pre_review_reviewer_md()

        assert "Adversarial Design Reviewer" in spec_md
        assert "Approach Reviewer" in pre_md
        assert spec_md != pre_md

    def test_mode_generators_registered(self) -> None:
        from adversarial_design_review.setup import _MODE_GENERATORS

        assert "pre-review" in _MODE_GENERATORS
        assert "reviewer" in _MODE_GENERATORS["pre-review"]
        assert "implementor" in _MODE_GENERATORS["pre-review"]


# ---------------------------------------------------------------------------
# Code review mode prompts and templates
# ---------------------------------------------------------------------------

class TestCodeReviewPrompts:

    def test_reviewer_prompt_is_code_vs_spec(self) -> None:
        from adversarial_design_review.prompts import build_reviewer_prompt

        prompt = build_reviewer_prompt(
            round_num=1, focus_items=[], handover_path=None,
            mode="code-review", spec_path="/tmp/spec.md",
        )

        assert "code review against the reviewed spec" in prompt
        assert "Do NOT modify the code" in prompt

    def test_reviewer_prompt_round2_has_evidence_requirement(self) -> None:
        from adversarial_design_review.prompts import build_reviewer_prompt

        prompt = build_reviewer_prompt(
            round_num=2, focus_items=["R1-01"], handover_path=None,
            mode="code-review", spec_path="/tmp/spec.md",
        )

        assert "EVIDENCE REQUIRED" in prompt
        assert "R1-01" in prompt
        assert "code change that now aligns with the spec" in prompt

    def test_implementor_prompt_is_code_focused(self) -> None:
        from adversarial_design_review.prompts import build_implementor_prompt

        prompt = build_implementor_prompt(
            round_num=1, focus_items=[], mode="code-review",
            workspace_root="/tmp/ws", spec_path="/tmp/spec.md",
        )

        assert "code review against the reviewed spec" in prompt
        assert "divergence" in prompt.lower()
        assert "fix the code" in prompt.lower()

    def test_reviewer_prompt_convergence_override(self) -> None:
        from adversarial_design_review.prompts import build_reviewer_prompt

        prompt = build_reviewer_prompt(
            round_num=2, focus_items=["R1-01"], handover_path=None,
            convergence_override_ids=["R1-02"],
            mode="code-review", spec_path="/tmp/spec.md",
        )

        assert "R1-02" in prompt
        assert "NOT in terminal state" in prompt


class TestCodeReviewTemplates:

    def test_reviewer_template_has_code_review_constraints(self) -> None:
        from adversarial_design_review.setup import _code_review_reviewer_md

        md = _code_review_reviewer_md()

        assert "Code vs Spec Reviewer" in md
        assert "spec" in md.lower()
        assert "implementation" in md.lower() or "code" in md.lower()

    def test_implementor_template_has_code_review_constraints(self) -> None:
        from adversarial_design_review.setup import _code_review_implementor_md

        md = _code_review_implementor_md()

        assert "Implementation Author" in md
        assert "DECISION_NEEDED" in md
        assert "spec" in md.lower()

    def test_reviewer_template_differs_from_spec_review(self) -> None:
        from adversarial_design_review.setup import _default_reviewer_md, _code_review_reviewer_md

        spec_md = _default_reviewer_md()
        code_md = _code_review_reviewer_md()

        assert "Adversarial Design Reviewer" in spec_md
        assert "Code vs Spec Reviewer" in code_md
        assert spec_md != code_md

    def test_mode_generators_registered(self) -> None:
        from adversarial_design_review.setup import _MODE_GENERATORS

        assert "code-review" in _MODE_GENERATORS
        assert "reviewer" in _MODE_GENERATORS["code-review"]
        assert "implementor" in _MODE_GENERATORS["code-review"]


# ---------------------------------------------------------------------------
# Diff base
# ---------------------------------------------------------------------------

class TestDiffBase:

    def test_diff_base_persisted_on_setup(self, tmp_path: Path) -> None:
        from adversarial_design_review.setup import setup_review

        spec = tmp_path / "spec.md"
        spec.write_text("# Test\n")

        ws = setup_review(
            spec_path=spec, title="test", source_dirs=[str(tmp_path)],
            adr_root=tmp_path / "adr", diff_base="main",
        )

        assert (ws / ".diff-base").exists()
        assert (ws / ".diff-base").read_text() == "main"

    def test_no_diff_base_file_when_omitted(self, tmp_path: Path) -> None:
        from adversarial_design_review.setup import setup_review

        spec = tmp_path / "spec.md"
        spec.write_text("# Test\n")

        ws = setup_review(
            spec_path=spec, title="test", source_dirs=[str(tmp_path)],
            adr_root=tmp_path / "adr",
        )

        assert not (ws / ".diff-base").exists()

    def test_diff_base_parse_args(self) -> None:
        from adversarial_design_review.review import parse_args
        import sys
        from unittest.mock import patch

        test_args = [
            "--spec", "/tmp/spec.md",
            "--title", "test",
            "--source-dirs", "/tmp/src",
            "--mode", "code-review",
            "--diff-base", "main",
        ]
        with patch.object(sys, "argv", ["review.py"] + test_args):
            args = parse_args()

        assert args.diff_base == "main"

    def test_diff_base_default_none(self) -> None:
        from adversarial_design_review.review import parse_args
        import sys
        from unittest.mock import patch

        test_args = [
            "--spec", "/tmp/spec.md",
            "--title", "test",
            "--source-dirs", "/tmp/src",
        ]
        with patch.object(sys, "argv", ["review.py"] + test_args):
            args = parse_args()

        assert args.diff_base is None


# ---------------------------------------------------------------------------
# Convergence override wiring
# ---------------------------------------------------------------------------

class TestConvergenceOverride:

    def test_convergence_override_ids_included_in_prompt(self) -> None:
        """F14: convergence_override_ids should appear in the reviewer prompt."""
        from adversarial_design_review.prompts import build_reviewer_prompt

        prompt = build_reviewer_prompt(
            round_num=3,
            focus_items=["R1-01", "R1-02"],
            handover_path=None,
            convergence_override_ids=["R1-03", "R1-04"],
        )

        assert "R1-03" in prompt
        assert "R1-04" in prompt
        assert "confirm" in prompt.lower()

    def test_convergence_override_ids_none_by_default(self) -> None:
        from adversarial_design_review.prompts import build_reviewer_prompt

        prompt = build_reviewer_prompt(
            round_num=3,
            focus_items=["R1-01"],
            handover_path=None,
        )

        # Should not contain the convergence override text
        assert "following items were not explicitly confirmed" not in prompt


# ---------------------------------------------------------------------------
# Source dirs warning
# ---------------------------------------------------------------------------

class TestSourceDirsValidation:

    def test_source_dirs_file_round_trip(self, tmp_path: Path) -> None:
        """F1: .source-dirs should persist and reload correctly."""
        from adversarial_design_review.setup import setup_review

        spec = tmp_path / "spec.md"
        spec.write_text("# Test\n")

        ws = setup_review(
            spec_path=spec,
            title="test",
            source_dirs=["/path/one", "/path/two"],
            adr_root=tmp_path / "adr",
        )

        source_dirs_file = ws / ".source-dirs"
        assert source_dirs_file.exists()
        lines = [l for l in source_dirs_file.read_text().splitlines() if l.strip()]
        assert lines == ["/path/one", "/path/two"]

    def test_empty_source_dirs_file(self, tmp_path: Path) -> None:
        """F1: Empty .source-dirs should produce empty list on reload."""
        from adversarial_design_review.setup import setup_review

        spec = tmp_path / "spec.md"
        spec.write_text("# Test\n")

        ws = setup_review(
            spec_path=spec,
            title="test",
            source_dirs=[],
            adr_root=tmp_path / "adr",
        )

        source_dirs_file = ws / ".source-dirs"
        assert source_dirs_file.exists()
        lines = [l for l in source_dirs_file.read_text().splitlines() if l.strip()]
        assert lines == []


# ---------------------------------------------------------------------------
# Decision file naming
# ---------------------------------------------------------------------------

class TestDecisionFileNaming:

    def test_decision_file_includes_role(self, tmp_path: Path) -> None:
        """F8: Decision files should be unique per role."""
        from adversarial_design_review.review import _handle_decision_needed
        from adversarial_design_review.tracker import Tracker

        ws = _make_workspace(tmp_path)
        tracker = Tracker(project_name="test")

        # Simulate non-interactive (skip)
        import sys
        from unittest.mock import patch

        with patch("adversarial_design_review.review._is_interactive", return_value=False):
            _handle_decision_needed(ws, tracker, 3, "test decision", role="reviewer")
            _handle_decision_needed(ws, tracker, 3, "another decision", role="implementor")

        assert (ws / "decisions" / "decision-3-reviewer.md").exists()
        assert (ws / "decisions" / "decision-3-implementor.md").exists()

    def test_decision_file_without_role_backward_compatible(self, tmp_path: Path) -> None:
        """Decision files without role should still work."""
        from adversarial_design_review.review import _handle_decision_needed
        from adversarial_design_review.tracker import Tracker
        from unittest.mock import patch

        ws = _make_workspace(tmp_path)
        tracker = Tracker(project_name="test")

        with patch("adversarial_design_review.review._is_interactive", return_value=False):
            _handle_decision_needed(ws, tracker, 3, "test decision")

        assert (ws / "decisions" / "decision-3.md").exists()

    def test_decision_file_extracts_issue_id_from_description(self, tmp_path: Path) -> None:
        """Issue ID should be auto-extracted from signal description."""
        from adversarial_design_review.review import _handle_decision_needed
        from adversarial_design_review.tracker import Tracker
        from unittest.mock import patch

        ws = _make_workspace(tmp_path)
        tracker = Tracker(project_name="test")

        with patch("adversarial_design_review.review._is_interactive", return_value=False):
            _handle_decision_needed(ws, tracker, 2, "R1-03 needs human decision on retry strategy", role="reviewer")

        decision_file = ws / "decisions" / "decision-2-reviewer.md"
        assert decision_file.exists()
        content = decision_file.read_text()
        assert "issue: R1-03" in content

    def test_decision_file_no_issue_id_when_absent_from_description(self, tmp_path: Path) -> None:
        """No issue line when description has no issue reference."""
        from adversarial_design_review.review import _handle_decision_needed
        from adversarial_design_review.tracker import Tracker
        from unittest.mock import patch

        ws = _make_workspace(tmp_path)
        tracker = Tracker(project_name="test")

        with patch("adversarial_design_review.review._is_interactive", return_value=False):
            _handle_decision_needed(ws, tracker, 2, "general design question", role="reviewer")

        decision_file = ws / "decisions" / "decision-2-reviewer.md"
        content = decision_file.read_text()
        assert "issue:" not in content


# ---------------------------------------------------------------------------
# _check_unresolved_before_done HIL
# ---------------------------------------------------------------------------

class TestCheckUnresolvedBeforeDone:

    def test_no_focus_items_returns_empty(self) -> None:
        from adversarial_design_review.review import _check_unresolved_before_done
        from adversarial_design_review.tracker import Tracker

        tracker = Tracker(project_name="test")
        tracker.add_issue("R1-01", "Issue 1", round_raised=1)
        tracker.mark_addressed("R1-01", section_ref="1.1", commit_hash="a", rationale="x")
        tracker.mark_verified("R1-01")

        result = _check_unresolved_before_done(tracker, round_num=1, cumulative_cost=5.0)
        assert result == []

    def test_non_interactive_defaults_to_accept(self) -> None:
        from adversarial_design_review.review import _check_unresolved_before_done
        from adversarial_design_review.tracker import Tracker
        from unittest.mock import patch

        tracker = Tracker(project_name="test")
        tracker.add_issue("R1-01", "Issue 1", round_raised=1)
        tracker.add_issue("R1-02", "Issue 2", round_raised=1)

        with patch("adversarial_design_review.review._is_interactive", return_value=False):
            result = _check_unresolved_before_done(tracker, round_num=1, cumulative_cost=5.0)

        assert result == []

    def test_fix_all_returns_all_items(self) -> None:
        from adversarial_design_review.review import _check_unresolved_before_done
        from adversarial_design_review.tracker import Tracker
        from unittest.mock import patch

        tracker = Tracker(project_name="test")
        tracker.add_issue("R1-01", "Issue 1", round_raised=1)
        tracker.add_issue("R1-02", "Issue 2", round_raised=1)

        with patch("adversarial_design_review.review._is_interactive", return_value=True), \
             patch("builtins.input", return_value="f"):
            result = _check_unresolved_before_done(tracker, round_num=1, cumulative_cost=5.0)

        assert result == ["R1-01", "R1-02"]

    def test_specific_items_by_number(self) -> None:
        from adversarial_design_review.review import _check_unresolved_before_done
        from adversarial_design_review.tracker import Tracker
        from unittest.mock import patch

        tracker = Tracker(project_name="test")
        tracker.add_issue("R1-01", "Issue 1", round_raised=1)
        tracker.add_issue("R1-02", "Issue 2", round_raised=1)
        tracker.add_issue("R1-03", "Issue 3", round_raised=1)

        with patch("adversarial_design_review.review._is_interactive", return_value=True), \
             patch("builtins.input", return_value="1,3"):
            result = _check_unresolved_before_done(tracker, round_num=1, cumulative_cost=5.0)

        assert result == ["R1-01", "R1-03"]

    def test_invalid_input_falls_back_to_accept(self) -> None:
        from adversarial_design_review.review import _check_unresolved_before_done
        from adversarial_design_review.tracker import Tracker
        from unittest.mock import patch

        tracker = Tracker(project_name="test")
        tracker.add_issue("R1-01", "Issue 1", round_raised=1)

        with patch("adversarial_design_review.review._is_interactive", return_value=True), \
             patch("builtins.input", return_value="xyz"):
            result = _check_unresolved_before_done(tracker, round_num=1, cumulative_cost=5.0)

        assert result == []

    def test_accept_returns_empty(self) -> None:
        from adversarial_design_review.review import _check_unresolved_before_done
        from adversarial_design_review.tracker import Tracker
        from unittest.mock import patch

        tracker = Tracker(project_name="test")
        tracker.add_issue("R1-01", "Issue 1", round_raised=1)

        with patch("adversarial_design_review.review._is_interactive", return_value=True), \
             patch("builtins.input", return_value="a"):
            result = _check_unresolved_before_done(tracker, round_num=1, cumulative_cost=5.0)

        assert result == []

    def test_out_of_range_numbers_ignored(self) -> None:
        from adversarial_design_review.review import _check_unresolved_before_done
        from adversarial_design_review.tracker import Tracker
        from unittest.mock import patch

        tracker = Tracker(project_name="test")
        tracker.add_issue("R1-01", "Issue 1", round_raised=1)
        tracker.add_issue("R1-02", "Issue 2", round_raised=1)

        with patch("adversarial_design_review.review._is_interactive", return_value=True), \
             patch("builtins.input", return_value="1,5,2"):
            result = _check_unresolved_before_done(tracker, round_num=1, cumulative_cost=5.0)

        assert result == ["R1-01", "R1-02"]


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

class TestNotifications:

    def test_build_command_with_terminal_notifier(self) -> None:
        from adversarial_design_review.review import _build_notify_command
        from unittest.mock import patch

        ws = Path("/Users/test/adr/casehub-iot/audit-20260629-120000")
        with patch("shutil.which", return_value="/opt/homebrew/bin/terminal-notifier"):
            cmd = _build_notify_command("test message", ws)

        assert cmd[0] == "/opt/homebrew/bin/terminal-notifier"
        assert "-title" in cmd
        assert "Design Review" in cmd
        assert "-message" in cmd
        assert "test message" in cmd
        assert "-execute" in cmd
        exec_idx = cmd.index("-execute")
        assert cmd[exec_idx + 1] == f"open {ws}"

    def test_build_command_without_terminal_notifier_falls_back(self) -> None:
        from adversarial_design_review.review import _build_notify_command
        from unittest.mock import patch

        with patch("shutil.which", return_value=None):
            cmd = _build_notify_command("test message")

        assert cmd[0] == "osascript"
        assert "test message" in cmd[-1]

    def test_build_command_without_ws_has_no_execute(self) -> None:
        from adversarial_design_review.review import _build_notify_command
        from unittest.mock import patch

        with patch("shutil.which", return_value="/opt/homebrew/bin/terminal-notifier"):
            cmd = _build_notify_command("test message", ws=None)

        assert "-execute" not in cmd

    def test_build_command_execute_opens_folder_not_file_url(self) -> None:
        """Click should open Finder via 'open /path', not file:// URL."""
        from adversarial_design_review.review import _build_notify_command
        from unittest.mock import patch

        ws = Path("/Users/test/adr/project/review-20260629")
        with patch("shutil.which", return_value="/opt/homebrew/bin/terminal-notifier"):
            cmd = _build_notify_command("msg", ws)

        exec_idx = cmd.index("-execute")
        assert cmd[exec_idx + 1].startswith("open /")
        assert "file://" not in cmd[exec_idx + 1]


# ---------------------------------------------------------------------------
# Spec symlink
# ---------------------------------------------------------------------------

class TestSpecSymlink:

    def test_spec_symlink_created_at_setup(self, tmp_path: Path) -> None:
        from adversarial_design_review.setup import setup_review

        spec = tmp_path / "my-design-spec.md"
        spec.write_text("# Test Spec\n")

        ws = setup_review(
            spec_path=spec, title="test", source_dirs=[str(tmp_path)],
            adr_root=tmp_path / "adr",
        )

        symlink = ws / "spec.md"
        assert symlink.is_symlink()
        assert symlink.resolve() == spec.resolve()

    def test_spec_symlink_points_to_correct_file(self, tmp_path: Path) -> None:
        from adversarial_design_review.setup import setup_review

        spec = tmp_path / "subdir" / "complex-name.md"
        spec.parent.mkdir()
        spec.write_text("# Spec\n")

        ws = setup_review(
            spec_path=spec, title="test", source_dirs=[str(tmp_path)],
            adr_root=tmp_path / "adr",
        )

        content = (ws / "spec.md").read_text()
        assert "# Spec" in content

    def test_issue_file_created_when_provided(self, tmp_path: Path) -> None:
        from adversarial_design_review.setup import setup_review

        spec = tmp_path / "spec.md"
        spec.write_text("# Test\n")

        ws = setup_review(
            spec_path=spec, title="test", source_dirs=[str(tmp_path)],
            adr_root=tmp_path / "adr", issue="42",
        )

        assert (ws / ".issue").exists()
        assert (ws / ".issue").read_text() == "42"

    def test_no_issue_file_when_not_provided(self, tmp_path: Path) -> None:
        from adversarial_design_review.setup import setup_review

        spec = tmp_path / "spec.md"
        spec.write_text("# Test\n")

        ws = setup_review(
            spec_path=spec, title="test", source_dirs=[str(tmp_path)],
            adr_root=tmp_path / "adr",
        )

        assert not (ws / ".issue").exists()


# ---------------------------------------------------------------------------
# Arch files
# ---------------------------------------------------------------------------

class TestArchFiles:

    def test_arch_files_persisted_on_setup(self, tmp_path: Path) -> None:
        from adversarial_design_review.setup import setup_review

        spec = tmp_path / "spec.md"
        spec.write_text("# Test\n")

        ws = setup_review(
            spec_path=spec, title="test", source_dirs=[str(tmp_path)],
            adr_root=tmp_path / "adr",
            arch_files=["/path/to/PLATFORM.md", "/path/to/ARC42STORIES.MD"],
        )

        arch_file = ws / ".arch-files"
        assert arch_file.exists()
        lines = [l for l in arch_file.read_text().splitlines() if l.strip()]
        assert lines == ["/path/to/PLATFORM.md", "/path/to/ARC42STORIES.MD"]

    def test_arch_files_in_context_md(self, tmp_path: Path) -> None:
        from adversarial_design_review.setup import setup_review

        spec = tmp_path / "spec.md"
        spec.write_text("# Test\n")

        ws = setup_review(
            spec_path=spec, title="test", source_dirs=[str(tmp_path)],
            adr_root=tmp_path / "adr",
            arch_files=["/path/to/PLATFORM.md"],
        )

        context = (ws / "context.md").read_text()
        assert "Architectural Files" in context
        assert "/path/to/PLATFORM.md" in context

    def test_no_arch_files_section_when_omitted(self, tmp_path: Path) -> None:
        from adversarial_design_review.setup import setup_review

        spec = tmp_path / "spec.md"
        spec.write_text("# Test\n")

        ws = setup_review(
            spec_path=spec, title="test", source_dirs=[str(tmp_path)],
            adr_root=tmp_path / "adr",
        )

        context = (ws / "context.md").read_text()
        assert "Architectural Files" not in context
        assert not (ws / ".arch-files").exists()

    def test_arch_files_parse_args(self) -> None:
        from adversarial_design_review.review import parse_args
        import sys
        from unittest.mock import patch

        test_args = [
            "--spec", "/tmp/spec.md",
            "--title", "test",
            "--source-dirs", "/tmp/src",
            "--arch-files", "/path/PLATFORM.md", "/path/ARC42.md",
        ]
        with patch.object(sys, "argv", ["review.py"] + test_args):
            args = parse_args()

        assert args.arch_files == ["/path/PLATFORM.md", "/path/ARC42.md"]

    def test_arch_files_default_none(self) -> None:
        from adversarial_design_review.review import parse_args
        import sys
        from unittest.mock import patch

        test_args = [
            "--spec", "/tmp/spec.md",
            "--title", "test",
            "--source-dirs", "/tmp/src",
        ]
        with patch.object(sys, "argv", ["review.py"] + test_args):
            args = parse_args()

        assert args.arch_files is None


# ---------------------------------------------------------------------------
# Mode defaults and persistence
# ---------------------------------------------------------------------------

class TestModeDefaults:

    def test_mode_defaults_exist(self) -> None:
        from adversarial_design_review.review import MODE_DEFAULTS, REVIEW_MODES

        for mode in REVIEW_MODES:
            assert mode in MODE_DEFAULTS
            defaults = MODE_DEFAULTS[mode]
            assert "max_rounds" in defaults
            assert "min_rounds" in defaults
            assert "budget_per_session" in defaults

    def test_pre_review_fewer_rounds(self) -> None:
        from adversarial_design_review.review import MODE_DEFAULTS

        pre = MODE_DEFAULTS["pre-review"]
        spec = MODE_DEFAULTS["spec-review"]
        assert pre["max_rounds"] < spec["max_rounds"]
        assert pre["min_rounds"] < spec["min_rounds"]

    def test_pre_review_lower_budget(self) -> None:
        from adversarial_design_review.review import MODE_DEFAULTS

        pre = MODE_DEFAULTS["pre-review"]
        spec = MODE_DEFAULTS["spec-review"]
        assert pre["budget_per_session"] <= spec["budget_per_session"]


class TestModeResume:

    def test_mode_loaded_on_resume(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        (ws / ".mode").write_text("pre-review")
        (ws / ".source-dirs").write_text(str(tmp_path))
        (ws / ".spec-path").write_text(str(tmp_path / "spec.md"))

        from adversarial_design_review.review import REVIEW_MODES
        mode_file = ws / ".mode"
        saved_mode = mode_file.read_text().strip()
        assert saved_mode in REVIEW_MODES
        assert saved_mode == "pre-review"

    def test_invalid_mode_file_ignored(self, tmp_path: Path) -> None:
        ws = _make_workspace(tmp_path)
        (ws / ".mode").write_text("invalid-mode")

        from adversarial_design_review.review import REVIEW_MODES
        saved_mode = (ws / ".mode").read_text().strip()
        assert saved_mode not in REVIEW_MODES


# ---------------------------------------------------------------------------
# Depth presets
# ---------------------------------------------------------------------------

class TestDepthPresets:
    def test_depth_presets_exist(self) -> None:
        from adversarial_design_review.review import DEPTH_PRESETS
        assert "light" in DEPTH_PRESETS
        assert "standard" in DEPTH_PRESETS
        assert "deep" in DEPTH_PRESETS

    def test_light_is_single_round(self) -> None:
        from adversarial_design_review.review import DEPTH_PRESETS
        assert DEPTH_PRESETS["light"]["max_rounds"] == 1
        assert DEPTH_PRESETS["light"]["min_rounds"] == 1

    def test_standard_preset(self) -> None:
        from adversarial_design_review.review import DEPTH_PRESETS
        assert DEPTH_PRESETS["standard"]["max_rounds"] == 3
        assert DEPTH_PRESETS["standard"]["min_rounds"] == 2
        assert DEPTH_PRESETS["standard"]["budget_per_session"] == 5.0

    def test_deep_preset(self) -> None:
        from adversarial_design_review.review import DEPTH_PRESETS
        assert DEPTH_PRESETS["deep"]["max_rounds"] == 5
        assert DEPTH_PRESETS["deep"]["min_rounds"] == 3
        assert DEPTH_PRESETS["deep"]["budget_per_session"] == 8.0


# ---------------------------------------------------------------------------
# Auto-detect depth
# ---------------------------------------------------------------------------

class TestAutoDetectDepth:
    def test_small_diff_is_light(self, tmp_path: Path) -> None:
        from adversarial_design_review.review import _auto_detect_depth
        stats = "2 files changed, 30 insertions(+), 5 deletions(-)"
        result = _auto_detect_depth(stats, new_file_count=0)
        assert result == "light"

    def test_medium_diff_is_standard(self, tmp_path: Path) -> None:
        from adversarial_design_review.review import _auto_detect_depth
        stats = "6 files changed, 120 insertions(+), 30 deletions(-)"
        result = _auto_detect_depth(stats, new_file_count=0)
        assert result == "standard"

    def test_large_diff_is_deep(self, tmp_path: Path) -> None:
        from adversarial_design_review.review import _auto_detect_depth
        stats = "15 files changed, 400 insertions(+), 100 deletions(-)"
        result = _auto_detect_depth(stats, new_file_count=0)
        assert result == "deep"

    def test_new_files_double_count(self, tmp_path: Path) -> None:
        from adversarial_design_review.review import _auto_detect_depth
        # 40 lines + 2 new files = 80 effective lines → standard, not light
        stats = "3 files changed, 30 insertions(+), 10 deletions(-)"
        result = _auto_detect_depth(stats, new_file_count=2)
        assert result == "standard"

    def test_many_files_triggers_deep(self, tmp_path: Path) -> None:
        from adversarial_design_review.review import _auto_detect_depth
        stats = "12 files changed, 100 insertions(+), 20 deletions(-)"
        result = _auto_detect_depth(stats, new_file_count=0)
        assert result == "deep"


# ---------------------------------------------------------------------------
# Depth flag
# ---------------------------------------------------------------------------

class TestDepthFlag:
    def test_depth_flag_parsed(self) -> None:
        from adversarial_design_review.review import parse_args
        import sys
        from unittest.mock import patch

        test_args = [
            "--spec", "s.md",
            "--title", "t",
            "--source-dirs", "/src",
            "--mode", "final-review",
            "--depth", "deep",
        ]
        with patch.object(sys, "argv", ["review.py"] + test_args):
            args = parse_args()

        assert args.depth == "deep"

    def test_depth_default_none(self) -> None:
        from adversarial_design_review.review import parse_args
        import sys
        from unittest.mock import patch

        test_args = [
            "--spec", "s.md",
            "--title", "t",
            "--source-dirs", "/src",
        ]
        with patch.object(sys, "argv", ["review.py"] + test_args):
            args = parse_args()

        assert args.depth is None

    def test_depth_choices(self) -> None:
        import pytest
        from adversarial_design_review.review import parse_args
        import sys
        from unittest.mock import patch

        test_args = [
            "--spec", "s.md",
            "--title", "t",
            "--source-dirs", "/src",
            "--mode", "final-review",
            "--depth", "extreme",
        ]
        with patch.object(sys, "argv", ["review.py"] + test_args):
            with pytest.raises(SystemExit):
                parse_args()


# ---------------------------------------------------------------------------
# Depth persistence
# ---------------------------------------------------------------------------

class TestDepthPersistence:
    def test_depth_file_written(self, tmp_path: Path) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        depth_file = ws / ".depth"
        depth_file.write_text("standard")
        assert depth_file.read_text() == "standard"

    def test_depth_file_loaded_on_resume(self, tmp_path: Path) -> None:
        from adversarial_design_review.review import _load_depth
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / ".depth").write_text("deep")
        assert _load_depth(ws) == "deep"

    def test_depth_file_missing_returns_none(self, tmp_path: Path) -> None:
        from adversarial_design_review.review import _load_depth
        ws = tmp_path / "ws"
        ws.mkdir()
        assert _load_depth(ws) is None


# ---------------------------------------------------------------------------
# Final review mode templates
# ---------------------------------------------------------------------------

class TestFinalReviewTemplates:
    def test_mode_generators_registered(self) -> None:
        from adversarial_design_review.setup import _MODE_GENERATORS
        assert "final-review" in _MODE_GENERATORS
        assert "reviewer" in _MODE_GENERATORS["final-review"]
        assert "implementor" in _MODE_GENERATORS["final-review"]

    def test_reviewer_template_has_final_review_constraints(self) -> None:
        from adversarial_design_review.setup import _MODE_GENERATORS
        content = _MODE_GENERATORS["final-review"]["reviewer"]()
        assert "production" in content.lower() or "readiness" in content.lower()
        assert "branch diff" in content.lower() or "branch changes" in content.lower()

    def test_implementor_template_has_final_review_constraints(self) -> None:
        from adversarial_design_review.setup import _MODE_GENERATORS
        content = _MODE_GENERATORS["final-review"]["implementor"]()
        assert "fix" in content.lower() or "code" in content.lower()

    def test_reviewer_template_has_main_code_focus(self) -> None:
        from adversarial_design_review.setup import _MODE_GENERATORS
        content = _MODE_GENERATORS["final-review"]["reviewer"]()
        assert "correctness" in content.lower()
        assert "security" in content.lower()
        assert "error handling" in content.lower()

    def test_reviewer_template_has_test_code_focus(self) -> None:
        from adversarial_design_review.setup import _MODE_GENERATORS
        content = _MODE_GENERATORS["final-review"]["reviewer"]()
        assert "coverage" in content.lower()
        assert "assertion" in content.lower()

    def test_reviewer_template_differs_from_spec_review(self) -> None:
        from adversarial_design_review.setup import _default_reviewer_md, _MODE_GENERATORS
        spec_content = _default_reviewer_md()
        final_content = _MODE_GENERATORS["final-review"]["reviewer"]()
        assert spec_content != final_content

    def test_implementor_fixes_code_not_spec(self) -> None:
        from adversarial_design_review.setup import _MODE_GENERATORS
        content = _MODE_GENERATORS["final-review"]["implementor"]()
        assert "source" in content.lower() or "code" in content.lower()


# ---------------------------------------------------------------------------
# Final-review prompt builders
# ---------------------------------------------------------------------------

class TestFinalReviewPrompts:
    def test_reviewer_prompt_is_production_focused(self) -> None:
        from adversarial_design_review.prompts import build_reviewer_prompt
        prompt = build_reviewer_prompt(
            round_num=1, focus_items=[], handover_path=None,
            convergence_override_ids=None,
            source_dirs=["/src"], workspace_root="/ws",
            spec_path="", mode="final-review",
        )
        assert "production" in prompt.lower() or "branch diff" in prompt.lower()

    def test_reviewer_prompt_round2_has_evidence_requirement(self) -> None:
        from adversarial_design_review.prompts import build_reviewer_prompt
        prompt = build_reviewer_prompt(
            round_num=2, focus_items=["R1-01: Bug found"],
            handover_path=None,
            convergence_override_ids=None,
            source_dirs=["/src"], workspace_root="/ws",
            spec_path="", mode="final-review",
        )
        assert "R1-01" in prompt

    def test_implementor_prompt_is_code_focused(self) -> None:
        from adversarial_design_review.prompts import build_implementor_prompt
        prompt = build_implementor_prompt(
            round_num=1, focus_items=["R1-01: Bug found"],
            source_dirs=["/src"], workspace_root="/ws",
            spec_path="", mode="final-review",
        )
        assert "fix" in prompt.lower() or "code" in prompt.lower()

    def test_reviewer_prompt_light_depth_is_focused(self) -> None:
        from adversarial_design_review.prompts import build_reviewer_prompt
        prompt = build_reviewer_prompt(
            round_num=1, focus_items=[], handover_path=None,
            convergence_override_ids=None,
            source_dirs=["/src"], workspace_root="/ws",
            spec_path="", mode="final-review", depth="light",
        )
        assert "quick" in prompt.lower() or "sanity" in prompt.lower()

    def test_reviewer_prompt_deep_depth_has_cross_module(self) -> None:
        from adversarial_design_review.prompts import build_reviewer_prompt
        prompt = build_reviewer_prompt(
            round_num=1, focus_items=[], handover_path=None,
            convergence_override_ids=None,
            source_dirs=["/src"], workspace_root="/ws",
            spec_path="", mode="final-review", depth="deep",
        )
        assert "cross-module" in prompt.lower() or "cross module" in prompt.lower()

    def test_reviewer_prompt_convergence_override(self) -> None:
        from adversarial_design_review.prompts import build_reviewer_prompt
        prompt = build_reviewer_prompt(
            round_num=2, focus_items=["R1-01: Bug"],
            handover_path=None,
            convergence_override_ids=["R1-01"],
            source_dirs=["/src"], workspace_root="/ws",
            spec_path="", mode="final-review",
        )
        assert "R1-01" in prompt


# ---------------------------------------------------------------------------
# _detect_last_round with depth parameter
# ---------------------------------------------------------------------------

class TestDetectLastRoundWithDepth:
    def test_light_depth_reviewer_only_is_complete(self, tmp_path: Path) -> None:
        from adversarial_design_review.review import _detect_last_round
        ws = _make_workspace(tmp_path)
        _write_reviewer(ws, 1, "review findings")
        # No implementor-1.md — for light depth this is complete
        last, reviewer_only = _detect_last_round(ws, depth="light")
        assert last == 1
        assert reviewer_only is False  # complete, not partial

    def test_standard_depth_reviewer_only_is_partial(self, tmp_path: Path) -> None:
        from adversarial_design_review.review import _detect_last_round
        ws = _make_workspace(tmp_path)
        _write_reviewer(ws, 1, "review findings")
        last, reviewer_only = _detect_last_round(ws, depth="standard")
        assert last == 1
        assert reviewer_only is True  # partial — implementor needed

    def test_none_depth_preserves_existing_behavior(self, tmp_path: Path) -> None:
        from adversarial_design_review.review import _detect_last_round
        ws = _make_workspace(tmp_path)
        _write_reviewer(ws, 1, "review findings")
        last, reviewer_only = _detect_last_round(ws, depth=None)
        assert last == 1
        assert reviewer_only is True  # backward compatible


# ---------------------------------------------------------------------------
# Code mode helpers
# ---------------------------------------------------------------------------

class TestCodeModeHelpers:
    def test_get_source_diff_combines_repos(self, tmp_path: Path) -> None:
        import subprocess
        from adversarial_design_review.review import _get_source_diff
        # Set up two git repos with changes
        for name in ("repo1", "repo2"):
            d = tmp_path / name
            d.mkdir()
            subprocess.run(["git", "init"], cwd=d, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=d, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=d, capture_output=True)
            (d / "file.py").write_text("initial")
            subprocess.run(["git", "add", "."], cwd=d, capture_output=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=d, capture_output=True)
            (d / "file.py").write_text("modified")
            subprocess.run(["git", "add", "."], cwd=d, capture_output=True)
            subprocess.run(["git", "commit", "-m", "change"], cwd=d, capture_output=True)

        diff = _get_source_diff([str(tmp_path / "repo1"), str(tmp_path / "repo2")])
        assert "file.py" in diff
        assert diff.count("diff --git") == 2  # one per repo

    def test_verify_code_changed_with_diff(self) -> None:
        from adversarial_design_review.review import verify_code_changed
        result = verify_code_changed("diff --git a/file.py b/file.py\n+new line")
        assert result.section_changed is True

    def test_verify_code_changed_empty(self) -> None:
        from adversarial_design_review.review import verify_code_changed
        result = verify_code_changed("")
        assert result.section_changed is False
