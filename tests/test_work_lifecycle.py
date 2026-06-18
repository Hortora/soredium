#!/usr/bin/env python3
"""
Tests for work lifecycle skill content — enforces correct routing rules.

These tests treat SKILL.md files as specifications: they validate that
the routing logic described in work/, work-pause/, and work-start/ is
self-consistent and makes the "pause then start new work" path visible.

The specific regression guarded here: work/SKILL.md previously
auto-resumed when stack depth was 1, hiding the ability to start new
work after pausing. The fix: stack 1+ always shows a picker.
"""

from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).parent.parent
WORK_SKILL = REPO_ROOT / "work" / "SKILL.md"
WORK_PAUSE_SKILL = REPO_ROOT / "work-pause" / "SKILL.md"
WORK_START_SKILL = REPO_ROOT / "work-start" / "SKILL.md"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def work_text():
    return WORK_SKILL.read_text()


@pytest.fixture(scope="module")
def work_pause_text():
    return WORK_PAUSE_SKILL.read_text()


@pytest.fixture(scope="module")
def work_start_text():
    return WORK_START_SKILL.read_text()


# ---------------------------------------------------------------------------
# work/SKILL.md — routing table
# ---------------------------------------------------------------------------

class TestWorkRouting:

    def test_stack_empty_routes_to_work_start(self, work_text):
        """Stack empty on main must route to work-start."""
        assert "stack empty" in work_text.lower()
        assert "work-start" in work_text

    def test_stack_one_plus_shows_picker_not_auto_resume(self, work_text):
        """Stack 1+ must show picker — never auto-resume."""
        # Extract routing table rows (lines containing pipes)
        table_rows = [line for line in work_text.splitlines() if "|" in line]
        table_text = "\n".join(table_rows)

        # The prohibited pattern in the routing table: a row that maps stack=1
        # directly to work-resume (any markdown form)
        assert "stack has 1 entry" not in table_text, (
            "Routing table must not have a separate stack=1 row — "
            "it silently auto-resumes and hides the 'start new work' path"
        )
        # Routing table must not say work-resume is automatic for any stack row
        # (checks both plain and markdown-bold forms)
        auto_resume_in_table = any(
            "resume" in row.lower() and "automatically" in row.lower()
            for row in table_rows
        )
        assert not auto_resume_in_table, (
            "Routing table must not auto-resume for any stack depth — "
            "user must always be shown the picker"
        )

    def test_stack_one_plus_routes_to_picker(self, work_text):
        """The routing table must direct stack 1+ to the picker step."""
        # Accept either "1+" or "1 or more" or "1 and above" style
        assert any(phrase in work_text for phrase in [
            "1+ entries",
            "1+ paused",
            "1 or more",
            "stack has 1+",
        ]), (
            "work/SKILL.md routing table must explicitly handle stack 1+ "
            "with the same picker as stack 2+"
        )

    def test_picker_offers_new_work_option(self, work_text):
        """The picker must always include a 'new' option."""
        assert "new" in work_text, "Picker must include 'new' option to start new work"
        assert "work-start" in work_text, "Picker 'new' option must route to work-start"

    def test_picker_section_present(self, work_text):
        """Step 3 (stack picker) must be present."""
        assert "Stack picker" in work_text or "stack picker" in work_text


# ---------------------------------------------------------------------------
# work-pause/SKILL.md — post-pause confirmation
# ---------------------------------------------------------------------------

class TestWorkPauseConfirmation:

    def test_step5_present(self, work_pause_text):
        """Step 5 (confirm) must be present."""
        assert "Step 5" in work_pause_text

    def test_step5_mentions_work_for_next_action(self, work_pause_text):
        """Step 5 must tell user to type 'work' — not just 'work-resume'."""
        # Find the Step 5 section
        idx = work_pause_text.find("Step 5")
        assert idx != -1
        step5_section = work_pause_text[idx:]

        assert "work" in step5_section, (
            "Step 5 confirmation must mention 'work' as the next command"
        )

    def test_step5_does_not_only_advertise_work_resume(self, work_pause_text):
        """Step 5 must not leave user thinking work-resume is the only option."""
        idx = work_pause_text.find("Step 5")
        step5_section = work_pause_text[idx:]

        # If the only command mentioned is "work-resume", that's the bug
        has_work_resume_only = (
            "work-resume" in step5_section
            and "start new" not in step5_section
            and "new work" not in step5_section
            and "type work" not in step5_section.lower()
        )
        assert not has_work_resume_only, (
            "Step 5 must not advertise work-resume as the only option — "
            "user must know they can start new work from main"
        )

    def test_step5_references_main_branch_context(self, work_pause_text):
        """Step 5 should tell user they are on main after pausing."""
        idx = work_pause_text.find("Step 5")
        step5_section = work_pause_text[idx:]
        assert "main" in step5_section, (
            "Step 5 should confirm user is on main, "
            "making it clear new work can begin"
        )


# ---------------------------------------------------------------------------
# work-start/SKILL.md — detection routing consistency
# ---------------------------------------------------------------------------

class TestWorkStartDetection:

    def test_no_auto_resume_for_stack_depth_1(self, work_start_text):
        """work-start detection must not auto-route stack=1 to work-resume."""
        assert "Stack depth 1: auto-route to work-resume" not in work_start_text, (
            "work-start must not auto-resume for stack depth 1 — "
            "it should always show picker via the work skill"
        )

    def test_pause_stack_routes_to_work_skill_picker(self, work_start_text):
        """When pause-stack has entries, work-start must route to work skill picker."""
        assert "stack picker" in work_start_text.lower(), (
            "work-start must delegate stack routing to the work skill picker"
        )

    def test_stack_detection_says_always_show_picker(self, work_start_text):
        """The detection note must indicate picker is shown for all stack depths."""
        # Look for the stack depth note in detection
        assert any(phrase in work_start_text for phrase in [
            "always show picker",
            "1+: always",
            "never auto-resume",
        ]), (
            "work-start detection note must say picker is shown for all depths (1+), "
            "not just depth 2+"
        )


# ---------------------------------------------------------------------------
# Cross-skill consistency
# ---------------------------------------------------------------------------

class TestCrossSkillConsistency:

    def test_work_and_work_start_agree_on_stack_routing(self, work_text, work_start_text):
        """work and work-start must both show picker for stack 1+ (never auto-resume)."""
        # Neither should say stack=1 auto-resumes
        for skill_name, text in [("work", work_text), ("work-start", work_start_text)]:
            assert "1 entry" not in text or "auto-resume" not in text, (
                f"{skill_name}/SKILL.md must not auto-resume for stack depth 1"
            )

    def test_work_pause_and_work_agree_on_next_step(self, work_text, work_pause_text):
        """work-pause Step 5 must align with work's picker — 'work' is the next command."""
        # work-pause tells user to type 'work'; work has the picker
        idx = work_pause_text.find("Step 5")
        step5 = work_pause_text[idx:]
        assert "work" in step5, "work-pause Step 5 must reference 'work' as next command"
        # And work must have a picker that offers new work
        assert "new" in work_text, "work skill picker must offer 'new' option"
