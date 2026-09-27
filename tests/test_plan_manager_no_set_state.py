"""Tests that plan_manager set-state blocks state field writes."""

import subprocess
import sys
from pathlib import Path

import pytest

PLAN_MANAGER = Path(__file__).parent.parent / "work-slot" / "plan_manager.py"


class TestSetStateBlocked:
    def test_rejects_state_field(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text("## State\nstate: active\n\n## Queue\n")
        result = subprocess.run(
            [sys.executable, str(PLAN_MANAGER),
             "set-state", str(plan), "key=state", "value=closing:landed"],
            capture_output=True, text=True,
        )
        assert result.returncode != 0
        assert "lifecycle" in result.stdout.lower()

    def test_allows_non_state_fields(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text("## State\nbranch: old\n\n## Queue\n")
        result = subprocess.run(
            [sys.executable, str(PLAN_MANAGER),
             "set-state", str(plan), "key=branch", "value=new-branch"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "SET=branch=new-branch" in result.stdout

    def test_rejects_even_valid_state_values(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text("## State\nstate: active\n\n## Queue\n")
        result = subprocess.run(
            [sys.executable, str(PLAN_MANAGER),
             "set-state", str(plan), "key=state", "value=closing:review"],
            capture_output=True, text=True,
        )
        assert result.returncode != 0, "Even valid states must go through lifecycle.py"
