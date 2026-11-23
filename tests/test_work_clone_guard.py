"""work.py refuses to start work in a canonical repo of a family that uses clones (#553)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "project"))
sys.path.insert(0, str(ROOT / "work-slot"))

import work  # noqa: E402


@pytest.fixture
def family(tmp_path):
    root = tmp_path / "fam"
    (root / "P").mkdir(parents=True)
    (root / "W").mkdir()
    return root


def call(project: Path, command: str = "continue", **extra: str):
    return work.apply_clone_guard({"command": command, "project": str(project),
                                   "on_main": "yes", **extra})


def make_clone(family: Path, with_workspace: bool = True) -> Path:
    clone = family / "clone" / "P"
    (clone / "P").mkdir(parents=True)
    (clone / ".slot").write_text("# Clone P\n")
    (clone / ".permanent").touch()
    if with_workspace:
        (clone / "W").mkdir()
        (clone / "W" / ".workspace").touch()
    return clone


class TestFamilyNotEnabled:

    @pytest.mark.parametrize("command", ["start", "continue", "next", "done"])
    def test_nothing_is_stopped(self, family, command):
        assert call(family / "P", command) == ([], False)

    def test_another_family_s_marker_does_not_count(self, family, tmp_path):
        other = tmp_path / "other"
        (other / "Q").mkdir(parents=True)
        (other / ".clone-enabled").touch()
        assert call(family / "P") == ([], False)
        assert call(other / "Q")[1] is True


class TestEnabledFamily:

    @pytest.fixture(autouse=True)
    def _enable(self, family):
        (family / ".clone-enabled").touch()

    @pytest.mark.parametrize("command", ["start", "continue", "next", "done"])
    def test_canonical_on_base_emits_decision_with_open_clone(self, family, command):
        clone = make_clone(family)
        lines, stop = call(family / "P", command)
        assert stop
        assert "ACTION=decision" in lines
        assert "DECISION=clone_guard" in lines
        assert "OPTIONS=open_clone,stop" in lines
        assert any("HANDLER=" in l for l in lines)
        assert f"CLONE={clone.resolve()}" in lines

    def test_named_start_emits_decision_too(self, family):
        make_clone(family)
        lines, stop = call(family / "P", "start", issue_n="9")
        assert stop
        assert "ACTION=decision" in lines

    def test_clone_without_a_workspace_names_the_project_clone(self, family):
        clone = make_clone(family, with_workspace=False)
        lines, stop = call(family / "P")
        assert stop
        assert any(str((clone / "P").resolve()) in l for l in lines if l.startswith("NEXT="))

    def test_no_clone_yet_emits_decision_with_create(self, family):
        lines, stop = call(family / "P")
        assert stop
        assert "ACTION=decision" in lines
        assert "DECISION=clone_guard" in lines
        assert "OPTIONS=create_and_open,stop" in lines
        assert any("CREATE_CMD=" in l for l in lines)

    def test_a_directory_without_slot_file_offers_create(self, family):
        (family / "clone" / "P" / "P").mkdir(parents=True)
        lines, _ = call(family / "P")
        assert "OPTIONS=create_and_open,stop" in lines

    def test_work_already_on_a_branch_in_canonical_may_finish(self, family):
        make_clone(family)
        assert call(family / "P", on_main="no") == ([], False)

    def test_inside_the_clone_nothing_is_stopped(self, family):
        clone = make_clone(family)
        assert call(clone / "P") == ([], False)

    def test_inside_a_numbered_slot_nothing_is_stopped(self, family):
        slot = family / "slots" / "3"
        (slot / "P").mkdir(parents=True)
        (slot / ".slot").write_text("# Slot 3\n")
        assert call(slot / "P") == ([], False)

    def test_follow_up_calls_are_not_stopped(self, family):
        make_clone(family)
        assert call(family / "P", step_done="resolve_issue") == ([], False)

    @pytest.mark.parametrize("command", ["pause", "resume", "find"])
    def test_other_commands_are_not_stopped(self, family, command):
        make_clone(family)
        assert call(family / "P", command) == ([], False)

    def test_through_main_nothing_else_runs(self, family, monkeypatch, capsys):
        make_clone(family)
        monkeypatch.setattr(sys, "argv", [
            "work.py", "continue", f"project={family / 'P'}", f"workspace={family / 'W'}",
            "base_branch=main", "branch=main", "on_main=yes"])
        assert work.main() == 0
        out = capsys.readouterr().out
        assert "DECISION=clone_guard" in out
        assert "ROUTE_REASON" not in out and "ALIGNMENT" not in out
