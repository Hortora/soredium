"""Tests that write_field validates state values against VALID_STATES."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "project"))

from plan_io import write_field


class TestWriteFieldStateValidation:
    def test_rejects_invalid_state(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text("## State\nstate: active\n\n## Queue\n")
        with pytest.raises(ValueError, match="Invalid state"):
            write_field(plan, "state", "closing:landed")

    def test_rejects_arbitrary_string(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text("## State\nstate: active\n\n## Queue\n")
        with pytest.raises(ValueError, match="Invalid state"):
            write_field(plan, "state", "banana")

    def test_accepts_valid_state(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text("## State\nstate: active\n\n## Queue\n")
        write_field(plan, "state", "closing:review")
        assert "state: closing:review" in plan.read_text()

    def test_accepts_all_valid_states(self, tmp_path):
        from lifecycle import VALID_STATES
        for state in sorted(VALID_STATES):
            plan = tmp_path / ".plan"
            plan.write_text("## State\nstate: active\n\n## Queue\n")
            write_field(plan, "state", state)
            assert f"state: {state}" in plan.read_text()

    def test_allows_non_state_fields(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text("## State\nbranch: old\n\n## Queue\n")
        write_field(plan, "branch", "anything-goes")
        assert "branch: anything-goes" in plan.read_text()

    def test_allows_covers_field(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text("## State\ncovers: 1\n\n## Queue\n")
        write_field(plan, "covers", "1,2,3")
        assert "covers: 1,2,3" in plan.read_text()
