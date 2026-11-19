"""Step progress belongs to one run of one pipeline for one issue (#562)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "project"))
sys.path.insert(0, str(ROOT / "work-slot"))

import work  # noqa: E402
from progress import Progress  # noqa: E402


def args(ws: Path, command: str = "start", **extra: str) -> dict[str, str]:
    return {"command": command, "workspace": str(ws), **extra}


def finished_start(ws: Path, issue: str = "551") -> None:
    """The state the first start leaves behind."""
    work.begin_run(args(ws, issue_n=issue))
    progress = Progress.load(ws)
    for step in ("sync_main", "branch_name", "create_branches", "scaffold"):
        progress.mark_done(step)
    progress.set("selected_branch", "issue-551-x")
    progress.save(ws)
    work.end_run(ws)


class TestBeginRun:

    def test_first_ever_call_records_the_run(self, tmp_path):
        assert work.begin_run(args(tmp_path, issue_n="551")) is True
        assert Progress.load(tmp_path).get("_run") == "start:551"

    def test_the_observed_failure_second_start_does_not_inherit_the_first(self, tmp_path):
        finished_start(tmp_path, "551")

        assert work.begin_run(args(tmp_path, issue_n="561")) is True

        progress = Progress.load(tmp_path)
        assert not progress.is_done("create_branches")
        assert not progress.is_done("branch_name")
        assert progress.get("selected_branch") == ""
        assert progress.get("_run") == "start:561"
        assert progress.get("_run_complete") == ""

    def test_starting_the_same_issue_again_after_it_completed_is_a_new_run(self, tmp_path):
        finished_start(tmp_path, "551")
        assert work.begin_run(args(tmp_path, issue_n="551")) is True
        assert not Progress.load(tmp_path).is_done("create_branches")

    def test_repeating_the_first_call_of_an_unfinished_run_resumes_it(self, tmp_path):
        work.begin_run(args(tmp_path, issue_n="551"))
        progress = Progress.load(tmp_path)
        progress.mark_done("sync_main")
        progress.save(tmp_path)

        assert work.begin_run(args(tmp_path, issue_n="551")) is False
        assert Progress.load(tmp_path).is_done("sync_main")

    def test_another_command_does_not_inherit_either(self, tmp_path):
        work.begin_run(args(tmp_path, issue_n="551"))
        progress = Progress.load(tmp_path)
        progress.mark_done("load_context")
        progress.save(tmp_path)

        assert work.begin_run(args(tmp_path, "continue", covers="o/r#551")) is True
        assert not Progress.load(tmp_path).is_done("load_context")

    def test_a_follow_up_call_never_resets(self, tmp_path):
        work.begin_run(args(tmp_path, issue_n="551"))
        progress = Progress.load(tmp_path)
        progress.mark_done("sync_main")
        progress.save(tmp_path)

        assert work.begin_run(args(tmp_path, issue_n="561", step_done="branch_name")) is False
        after = Progress.load(tmp_path)
        assert after.is_done("sync_main") and after.get("_run") == "start:551"

    def test_progress_written_before_runs_were_recorded_is_not_inherited(self, tmp_path):
        (tmp_path / ".work-progress").write_text("branch_name=done\ncreate_branches=done\n")
        assert work.begin_run(args(tmp_path, issue_n="561")) is True
        assert not Progress.load(tmp_path).is_done("create_branches")

    def test_a_command_with_no_pipeline_touches_nothing(self, tmp_path):
        (tmp_path / ".work-progress").write_text("x=done\n")
        assert work.begin_run(args(tmp_path, "end")) is False
        assert (tmp_path / ".work-progress").read_text() == "x=done\n"

    def test_a_missing_workspace_is_left_alone(self, tmp_path):
        assert work.begin_run(args(tmp_path / "absent", issue_n="1")) is False
        assert not (tmp_path / "absent").exists()

    @pytest.mark.parametrize("given, key", [
        ({"issue_n": "7", "covers": "o/r#9", "branch": "b"}, "start:7"),
        ({"covers": "o/r#9", "branch": "b"}, "start:o/r#9"),
        ({"branch": "b"}, "start:b"),
        ({}, "start:"),
    ])
    def test_run_key(self, given, key):
        assert work.run_key({"command": "start", **given}) == key


class TestEndRun:

    def test_marks_the_run_complete_and_keeps_its_record(self, tmp_path):
        work.begin_run(args(tmp_path, issue_n="551"))
        work.end_run(tmp_path)
        progress = Progress.load(tmp_path)
        assert progress.get("_run_complete") == "yes"
        assert progress.get("_run") == "start:551"


class TestStartMadeNoBranch:

    @pytest.fixture
    def repo(self, tmp_path):
        r = tmp_path / "project"
        r.mkdir()
        env = ["-c", "user.name=T", "-c", "user.email=t@t"]
        subprocess.run(["git", "-C", str(r), "init", "-q", "-b", "main"], check=True)
        subprocess.run(["git", "-C", str(r), *env, "commit", "-q", "--allow-empty", "-m", "i"],
                       check=True)
        return r

    def test_project_still_on_base_is_reported(self, repo):
        problem = work.start_made_no_branch({"project": str(repo), "base_branch": "main"})
        assert "still on main" in problem and "project" in problem

    def test_project_on_a_working_branch_is_fine(self, repo):
        subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "issue-1-x"], check=True)
        assert work.start_made_no_branch({"project": str(repo), "base_branch": "main"}) == ""

    def test_no_project_given_is_not_judged(self, tmp_path):
        assert work.start_made_no_branch({"project": str(tmp_path / "absent")}) == ""
        assert work.start_made_no_branch({}) == ""
