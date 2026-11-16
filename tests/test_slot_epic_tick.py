"""#524: slots tick the epic's checkboxes on GitHub with a correct issue reference.

Both call sites passed three positional arguments to a two-argument function; the
TypeError was swallowed and reported as GitHub being unreachable.
"""
import inspect
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "work-slot"))
sys.path.insert(0, str(ROOT / "scripts"))

import plan_manager  # noqa: E402
import slot_lifecycle  # noqa: E402


class TestTickEpic:
    def test_passes_an_issue_reference_and_the_completed_numbers(self):
        with patch.object(plan_manager, "_tick_github_checkboxes", return_value=True) as tick:
            assert slot_lifecycle._tick_epic("o/r", 7, [1, 2]) is True
        (ref, completed), _ = tick.call_args
        assert (ref.repo, ref.number) == ("o/r", 7)
        assert completed == [1, 2]

    def test_arguments_fit_the_real_function(self):
        """Guards the mock above: the real ticker must accept exactly what we pass."""
        inspect.signature(plan_manager._tick_github_checkboxes).bind(
            plan_manager.IssueRef("o/r", 7), [1, 2])

    def test_reports_failure_from_github(self):
        with patch.object(plan_manager, "_tick_github_checkboxes", return_value=False):
            assert slot_lifecycle._tick_epic("o/r", 7, [1]) is False

    def test_nothing_to_tick_is_not_a_call(self):
        with patch.object(plan_manager, "_tick_github_checkboxes") as tick:
            assert slot_lifecycle._tick_epic("", 0, [1]) is True
            assert slot_lifecycle._tick_epic("o/r", 7, []) is True
        tick.assert_not_called()

    def test_no_call_site_bypasses_the_helper(self):
        source = (ROOT / "work-slot" / "slot_lifecycle.py").read_text()
        assert source.count("_tick_github_checkboxes(") == 1
