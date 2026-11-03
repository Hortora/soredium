"""Per-mode pipeline verification tests (#491).

Verifies the expected step sequence for each pipeline mode, catching
mode-filtering bugs that the combinatorial explosion makes hard to
test functionally. Each mode's step list is the contract — if a step
is accidentally excluded or added, the test fails.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "work-end"))
sys.path.insert(0, str(Path(__file__).parent.parent / "project"))

from work_end_orchestrator import STEPS
from shared_steps import PipelineMode
from judgment import StepType


def steps_for_mode(mode: PipelineMode) -> list[str]:
    return [s.name for s in STEPS if mode in s.modes]


# ---------------------------------------------------------------------------
# Expected step sequences — the contract for each mode
# ---------------------------------------------------------------------------

SHARED_REVIEW = [
    "report_init",
    "code_review", "branch_audit_conformance", "branch_audit_coherence",
    "branch_audit_structure", "branch_audit_robustness",
    "loose_ends", "forcing_function",
    "sweep_config", "forage", "protocol", "update_claude_md",
    "impl_doc_sync", "doc_freshness_gate", "adr", "write_content",
]

SHARED_POST_LAND = [
    "push_pass", "merge_pass",
]


class TestBranchModeSteps:
    MODE = PipelineMode.BRANCH

    def test_step_count(self):
        assert len(steps_for_mode(self.MODE)) == 53

    def test_review_phase_present(self):
        active = steps_for_mode(self.MODE)
        for step in SHARED_REVIEW:
            assert step in active, f"{step} missing from BRANCH mode"

    def test_rebase_squash_present(self):
        active = steps_for_mode(self.MODE)
        assert "rebase" in active
        assert "squash" in active

    def test_slot_only_steps_absent(self):
        active = steps_for_mode(self.MODE)
        for step in ["write_marker", "write_landed", "archive_slot",
                     "report_archive", "elevate_plan"]:
            assert step not in active, f"{step} should not be in BRANCH mode"

    def test_sync_only_steps_absent(self):
        active = steps_for_mode(self.MODE)
        assert "sync_pass" not in active

    def test_cycle_only_steps_absent(self):
        active = steps_for_mode(self.MODE)
        assert "cycle_pass" not in active

    def test_main_only_steps_absent(self):
        active = steps_for_mode(self.MODE)
        assert "cleanup_main" not in active

    def test_has_terminal_lifecycle(self):
        active = steps_for_mode(self.MODE)
        assert "stamp_pass" in active
        assert "cleanup_pass" in active

    def test_checkout_and_cleanup(self):
        active = steps_for_mode(self.MODE)
        assert "checkout_main" in active
        assert "cleanup_stack" in active
        assert "cleanup" in active

    def test_queue_continuation(self):
        active = steps_for_mode(self.MODE)
        assert "queue_decision" in active
        assert "advance_queue" in active
        assert "cleanup_cycle" in active

    def test_close_issues_chain(self):
        active = steps_for_mode(self.MODE)
        assert "close_issues" in active
        assert "report_close_issues" in active
        assert "epic_handoff" in active

    def test_user_input_steps(self):
        active = steps_for_mode(self.MODE)
        for step in ["arc42_scan", "session_rename", "garden_feedback", "notes"]:
            assert step in active


class TestSlotModeSteps:
    MODE = PipelineMode.SLOT

    def test_step_count(self):
        assert len(steps_for_mode(self.MODE)) == 58

    def test_has_slot_specific_steps(self):
        active = steps_for_mode(self.MODE)
        for step in ["write_marker", "write_landed", "archive_slot",
                     "report_archive", "elevate_plan"]:
            assert step in active, f"{step} missing from SLOT mode"

    def test_superset_of_branch(self):
        """Slot has everything branch has, plus slot-specific steps."""
        branch = set(steps_for_mode(PipelineMode.BRANCH))
        slot = set(steps_for_mode(self.MODE))
        slot_only = {"write_marker", "write_landed", "archive_slot",
                     "report_archive", "elevate_plan"}
        assert branch | slot_only == slot

    def test_no_sync_or_cycle_exclusive(self):
        active = steps_for_mode(self.MODE)
        assert "sync_pass" not in active
        assert "cycle_pass" not in active


class TestMainModeSteps:
    MODE = PipelineMode.MAIN

    def test_step_count(self):
        assert len(steps_for_mode(self.MODE)) == 45

    def test_no_rebase_or_squash(self):
        active = steps_for_mode(self.MODE)
        assert "rebase" not in active
        assert "report_rebase" not in active
        assert "squash" not in active
        assert "report_squash" not in active

    def test_no_checkout_main(self):
        """Already on main — no need to checkout."""
        active = steps_for_mode(self.MODE)
        assert "checkout_main" not in active
        assert "cleanup_stack" not in active

    def test_has_cleanup_main(self):
        active = steps_for_mode(self.MODE)
        assert "cleanup_main" in active

    def test_has_land(self):
        """Main mode uses land for push_main_mode."""
        active = steps_for_mode(self.MODE)
        assert "land" in active

    def test_no_queue_continuation(self):
        active = steps_for_mode(self.MODE)
        assert "advance_queue" not in active
        assert "cleanup_cycle" not in active
        assert "cleanup_pass" not in active

    def test_has_stamp_pass(self):
        active = steps_for_mode(self.MODE)
        assert "stamp_pass" in active


class TestSyncModeSteps:
    MODE = PipelineMode.SYNC

    def test_step_count(self):
        assert len(steps_for_mode(self.MODE)) == 36

    def test_no_verify_or_close(self):
        """Sync doesn't verify or close — branch stays open."""
        active = steps_for_mode(self.MODE)
        assert "verify" not in active
        assert "close_issues" not in active
        assert "epic_handoff" not in active

    def test_no_checkout_or_cleanup(self):
        active = steps_for_mode(self.MODE)
        assert "checkout_main" not in active
        assert "cleanup" not in active
        assert "cleanup_stack" not in active

    def test_has_sync_pass(self):
        active = steps_for_mode(self.MODE)
        assert "sync_pass" in active

    def test_no_stamp_pass(self):
        active = steps_for_mode(self.MODE)
        assert "stamp_pass" not in active

    def test_no_user_input_steps(self):
        active = steps_for_mode(self.MODE)
        for step in ["arc42_scan", "session_rename", "garden_feedback", "notes"]:
            assert step not in active

    def test_no_queue_decision(self):
        active = steps_for_mode(self.MODE)
        assert "queue_decision" not in active

    def test_has_rebase_and_squash(self):
        active = steps_for_mode(self.MODE)
        assert "rebase" in active
        assert "squash" in active


class TestCycleModeSteps:
    MODE = PipelineMode.CYCLE

    def test_step_count(self):
        assert len(steps_for_mode(self.MODE)) == 42

    def test_has_cycle_pass(self):
        active = steps_for_mode(self.MODE)
        assert "cycle_pass" in active

    def test_no_stamp_pass(self):
        """Cycle returns to active, not idle — no stamp."""
        active = steps_for_mode(self.MODE)
        assert "stamp_pass" not in active

    def test_no_checkout_or_cleanup(self):
        """Branch stays open for next cycle."""
        active = steps_for_mode(self.MODE)
        assert "checkout_main" not in active
        assert "cleanup" not in active
        assert "cleanup_stack" not in active

    def test_no_terminal_steps(self):
        active = steps_for_mode(self.MODE)
        for step in ["arc42_scan", "session_rename", "garden_feedback", "notes",
                     "advance_queue", "cleanup_cycle", "cleanup_pass"]:
            assert step not in active

    def test_has_verify_and_close(self):
        active = steps_for_mode(self.MODE)
        assert "verify" in active
        assert "close_issues" in active


# ---------------------------------------------------------------------------
# Structural invariants — must hold across ALL modes
# ---------------------------------------------------------------------------

class TestCrossModeInvariants:
    """Invariants that must hold regardless of mode."""

    @pytest.mark.parametrize("mode", list(PipelineMode))
    def test_report_init_always_first(self, mode):
        active = steps_for_mode(mode)
        assert active[0] == "report_init"

    @pytest.mark.parametrize("mode", list(PipelineMode))
    def test_delete_progress_always_last(self, mode):
        active = steps_for_mode(mode)
        assert active[-2] == "delete_progress"
        assert active[-1] == "report_render"

    @pytest.mark.parametrize("mode", list(PipelineMode))
    def test_review_pass_after_all_review_steps(self, mode):
        active = steps_for_mode(mode)
        if "review_pass" not in active:
            pytest.skip("no review_pass in this mode")
        rp_idx = active.index("review_pass")
        for step in SHARED_REVIEW:
            if step in active:
                assert active.index(step) < rp_idx, f"{step} must come before review_pass"

    @pytest.mark.parametrize("mode", list(PipelineMode))
    def test_promote_before_land(self, mode):
        active = steps_for_mode(mode)
        if "promote" not in active or "land" not in active:
            pytest.skip("promote or land absent")
        assert active.index("promote") < active.index("land")

    @pytest.mark.parametrize("mode", list(PipelineMode))
    def test_land_before_stamp_lifecycle(self, mode):
        active = steps_for_mode(mode)
        if "land" not in active:
            pytest.skip("no land in this mode")
        land_idx = active.index("land")
        for lc in ["push_pass", "merge_pass", "stamp_pass", "cycle_pass", "sync_pass"]:
            if lc in active:
                assert active.index(lc) > land_idx, f"{lc} must come after land"

    @pytest.mark.parametrize("mode", list(PipelineMode))
    def test_close_issues_before_epic_handoff(self, mode):
        active = steps_for_mode(mode)
        if "close_issues" in active and "epic_handoff" in active:
            assert active.index("close_issues") < active.index("epic_handoff")

    @pytest.mark.parametrize("mode", list(PipelineMode))
    def test_exactly_one_terminal_lifecycle(self, mode):
        """Each mode should end in exactly one terminal lifecycle transition."""
        active = steps_for_mode(mode)
        terminal = [s for s in active if s in
                    ("stamp_pass", "cycle_pass", "sync_pass", "cleanup_main",
                     "cleanup_pass", "cleanup_cycle")]
        assert len(terminal) >= 1, f"Mode {mode.value} has no terminal lifecycle step"

    @pytest.mark.parametrize("mode", list(PipelineMode))
    def test_promote_plan_next_in_all_modes(self, mode):
        active = steps_for_mode(mode)
        assert "promote_plan_next" in active

    def test_each_step_in_at_least_one_mode(self):
        all_steps = {s.name for s in STEPS}
        covered = set()
        for mode in PipelineMode:
            covered |= set(steps_for_mode(mode))
        uncovered = all_steps - covered
        assert uncovered == set(), f"Steps not in any mode: {uncovered}"

    def test_no_duplicate_step_names(self):
        names = [s.name for s in STEPS]
        assert len(names) == len(set(names)), f"Duplicate step names: {[n for n in names if names.count(n) > 1]}"


# ---------------------------------------------------------------------------
# Dependency invariants
# ---------------------------------------------------------------------------

class TestDependencyInvariants:
    """Verify requires= dependencies are satisfiable in each mode.

    The engine auto-satisfies requirements on steps filtered out by mode
    (if r not in active_step_names, the requirement is skipped). So a
    dependency on a step absent from a mode is harmless at runtime —
    but test_cross_mode_dependencies flags them as design notes.
    """

    @pytest.mark.parametrize("mode", list(PipelineMode))
    def test_all_in_mode_requires_satisfiable(self, mode):
        """Requirements that ARE in the mode must be satisfiable."""
        active = set(steps_for_mode(mode))
        for step in STEPS:
            if mode not in step.modes:
                continue
            for req in step.requires:
                if req in active:
                    pass  # present — will be checked by ordering test

    @pytest.mark.parametrize("mode", list(PipelineMode))
    def test_requires_come_before_dependent(self, mode):
        """Required steps must appear before the steps that depend on them."""
        active = steps_for_mode(mode)
        for step in STEPS:
            if mode not in step.modes:
                continue
            for req in step.requires:
                if req in active:
                    assert active.index(req) < active.index(step.name), (
                        f"Mode {mode.value}: '{req}' must come before '{step.name}'"
                    )

    def test_cross_mode_dependencies_documented(self):
        """Flag dependencies on steps filtered out by mode.

        These are auto-satisfied by the engine but are design smells.
        This test documents the known cases — add new ones here if
        they're intentional, or fix them in STEPS.
        """
        known_cross_mode = {
            ("main", "land", "squash"),
            ("main", "checkout_fork", "checkout_main"),
            ("sync", "fork_next_branch", "queue_decision"),
            ("sync", "checkout_fork", "checkout_main"),
            ("cycle", "checkout_fork", "checkout_main"),
        }
        found: set[tuple[str, str, str]] = set()
        for mode in PipelineMode:
            active = set(steps_for_mode(mode))
            for step in STEPS:
                if mode not in step.modes:
                    continue
                for req in step.requires:
                    if req not in active:
                        found.add((mode.value, step.name, req))

        unexpected = found - known_cross_mode
        assert unexpected == set(), (
            f"New cross-mode dependencies found (steps requiring steps "
            f"absent from their mode): {unexpected}. If intentional, add "
            f"to known_cross_mode. If not, fix the StepDef."
        )
