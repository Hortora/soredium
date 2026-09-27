"""Tests that .plan is NOT in the lifecycle files strip list."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "work-end"))


class TestPlanNotInLifecycleFiles:
    def test_plan_not_in_lifecycle_files(self):
        from land_flow import LIFECYCLE_FILES
        assert ".plan" not in LIFECYCLE_FILES, (
            ".plan should not be stripped before merge — state changes need "
            "to survive post-land lifecycle transitions"
        )
