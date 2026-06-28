"""Tests for adversarial-design-review/prompts.py"""

from __future__ import annotations


class TestReviewerPrompt:

    def test_round1_no_calibration(self) -> None:
        from adversarial_design_review.prompts import build_reviewer_prompt

        prompt = build_reviewer_prompt(round_num=1, focus_items=[], handover_path=None)
        assert "round 1" in prompt.lower()
        assert "ultrathink" in prompt.lower()
        assert "CALIBRATION" not in prompt
        assert "Do NOT update the spec" in prompt

    def test_round3_has_calibration(self) -> None:
        from adversarial_design_review.prompts import build_reviewer_prompt

        prompt = build_reviewer_prompt(round_num=3, focus_items=["R1-02", "R2-01"], handover_path=None)
        assert "CALIBRATION" in prompt
        assert "R1-02" in prompt
        assert "R2-01" in prompt

    def test_post_reset_includes_handover(self) -> None:
        from adversarial_design_review.prompts import build_reviewer_prompt

        prompt = build_reviewer_prompt(
            round_num=6, focus_items=[], handover_path="handovers/reviewer-handover-5.md",
        )
        assert "handovers/reviewer-handover-5.md" in prompt

    def test_premature_convergence_override(self) -> None:
        from adversarial_design_review.prompts import build_reviewer_prompt

        prompt = build_reviewer_prompt(
            round_num=2, focus_items=[], handover_path=None,
            convergence_override_ids=["R1-03", "R1-04", "R1-05"],
        )
        assert "R1-03" in prompt
        assert "R1-04" in prompt
        assert "confirm" in prompt.lower()


class TestImplementorPrompt:

    def test_standard_prompt(self) -> None:
        from adversarial_design_review.prompts import build_implementor_prompt

        prompt = build_implementor_prompt(round_num=2, focus_items=["R1-02", "R2-01"])
        assert "round 2" in prompt.lower()
        assert "push back" in prompt.lower()
        assert "R1-02" in prompt
        assert "R2-01" in prompt

    def test_no_focus_items(self) -> None:
        from adversarial_design_review.prompts import build_implementor_prompt

        prompt = build_implementor_prompt(round_num=1, focus_items=[])
        assert "round 1" in prompt.lower()


class TestSweepPrompt:

    def test_reviewer_sweep(self) -> None:
        from adversarial_design_review.prompts import build_sweep_prompt

        prompt = build_sweep_prompt(role="reviewer", round_num=5)
        assert "handovers/reviewer-handover-5.md" in prompt
        assert "confidence" in prompt.lower()

    def test_implementor_sweep(self) -> None:
        from adversarial_design_review.prompts import build_sweep_prompt

        prompt = build_sweep_prompt(role="implementor", round_num=5)
        assert "handovers/implementor-handover-5.md" in prompt
        assert "rationale" in prompt.lower()


