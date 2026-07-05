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
        assert "evidence" in prompt.lower()

    def test_round2_has_evidence_instructions(self) -> None:
        from adversarial_design_review.prompts import build_reviewer_prompt

        prompt = build_reviewer_prompt(
            round_num=2, focus_items=["R1-01"], handover_path=None,
        )
        assert "EVIDENCE REQUIRED" in prompt
        assert "§N.N" in prompt
        assert "APPROVED will only be accepted when ALL items" in prompt

    def test_round1_no_evidence_instructions(self) -> None:
        from adversarial_design_review.prompts import build_reviewer_prompt

        prompt = build_reviewer_prompt(
            round_num=1, focus_items=[], handover_path=None,
        )
        assert "EVIDENCE REQUIRED" not in prompt


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


class TestPreReviewReviewerPrompt:

    def test_pre_review_framing(self) -> None:
        from adversarial_design_review.prompts import build_reviewer_prompt

        prompt = build_reviewer_prompt(
            round_num=1, focus_items=[], handover_path=None, mode="pre-review",
        )
        assert "pre-review" in prompt.lower()
        assert "APPROACH" in prompt
        assert "ultrathink" in prompt.lower()

    def test_pre_review_round1_no_evidence_block(self) -> None:
        from adversarial_design_review.prompts import build_reviewer_prompt

        prompt = build_reviewer_prompt(
            round_num=1, focus_items=[], handover_path=None, mode="pre-review",
        )
        assert "EVIDENCE REQUIRED" not in prompt

    def test_pre_review_round2_has_evidence(self) -> None:
        from adversarial_design_review.prompts import build_reviewer_prompt

        prompt = build_reviewer_prompt(
            round_num=2, focus_items=["R1-01"], handover_path=None, mode="pre-review",
        )
        assert "EVIDENCE REQUIRED" in prompt

    def test_pre_review_no_calibration_block(self) -> None:
        from adversarial_design_review.prompts import build_reviewer_prompt

        prompt = build_reviewer_prompt(
            round_num=3, focus_items=[], handover_path=None, mode="pre-review",
        )
        assert "CALIBRATION" not in prompt

    def test_pre_review_with_focus_items(self) -> None:
        from adversarial_design_review.prompts import build_reviewer_prompt

        prompt = build_reviewer_prompt(
            round_num=2, focus_items=["R1-01", "R1-02"], handover_path=None,
            mode="pre-review",
        )
        assert "R1-01" in prompt
        assert "R1-02" in prompt

    def test_pre_review_convergence_override(self) -> None:
        from adversarial_design_review.prompts import build_reviewer_prompt

        prompt = build_reviewer_prompt(
            round_num=2, focus_items=[], handover_path=None,
            convergence_override_ids=["R1-01"], mode="pre-review",
        )
        assert "R1-01" in prompt
        assert "evidence" in prompt.lower()

    def test_spec_review_mode_uses_original(self) -> None:
        from adversarial_design_review.prompts import build_reviewer_prompt

        prompt = build_reviewer_prompt(
            round_num=1, focus_items=[], handover_path=None, mode="spec-review",
        )
        assert "adversarial design review" in prompt.lower()
        assert "pre-review" not in prompt.lower()


class TestPreReviewImplementorPrompt:

    def test_pre_review_framing(self) -> None:
        from adversarial_design_review.prompts import build_implementor_prompt

        prompt = build_implementor_prompt(
            round_num=1, focus_items=[], mode="pre-review",
        )
        assert "pre-review" in prompt.lower()
        assert "pivot" in prompt.lower()

    def test_pre_review_with_focus_items(self) -> None:
        from adversarial_design_review.prompts import build_implementor_prompt

        prompt = build_implementor_prompt(
            round_num=2, focus_items=["R1-01"], mode="pre-review",
        )
        assert "R1-01" in prompt

    def test_spec_review_mode_uses_original(self) -> None:
        from adversarial_design_review.prompts import build_implementor_prompt

        prompt = build_implementor_prompt(
            round_num=1, focus_items=[], mode="spec-review",
        )
        assert "adversarial design review" in prompt.lower()
        assert "pre-review" not in prompt.lower()


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


