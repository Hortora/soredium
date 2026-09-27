"""Integration tests for state durability across git operations."""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "project"))

from lifecycle import (
    TransitionResult,
    commit_transition,
    read_state,
    write_state,
    VALID_STATES,
)
from plan_io import write_field


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, timeout=10,
    )


def _init_workspace(path):
    _git(path, "init")
    _git(path, "config", "user.email", "test@test.com")
    _git(path, "config", "user.name", "Test")
    plan = path / ".plan"
    plan.write_text(
        "# Work Plan\n\n## State\n"
        "branch: test-branch\nstate: active\ncovers: 1\n\n"
        "## Queue\n- [ ] test#1 — Test\n"
    )
    _git(path, "add", ".plan")
    _git(path, "commit", "-m", "scaffold")
    _git(path, "checkout", "-b", "test-branch")


class TestStateSurvivesBranchOps:
    def test_state_survives_checkout_and_return(self, tmp_path):
        _init_workspace(tmp_path)
        plan = tmp_path / ".plan"

        result = TransitionResult("active", "closing:review", "work_end")
        commit_transition(plan, result)
        assert read_state(plan) == "closing:review"

        _git(tmp_path, "checkout", "main")
        _git(tmp_path, "checkout", "test-branch")

        assert read_state(plan) == "closing:review"

    def test_state_survives_stash_cycle(self, tmp_path):
        _init_workspace(tmp_path)
        plan = tmp_path / ".plan"

        result = TransitionResult("active", "closing:review", "work_end")
        commit_transition(plan, result)

        (tmp_path / "other.txt").write_text("change")
        _git(tmp_path, "add", "other.txt")
        _git(tmp_path, "stash", "push", "-u")
        _git(tmp_path, "stash", "pop")

        assert read_state(plan) == "closing:review"

    def test_state_survives_rebase(self, tmp_path):
        _init_workspace(tmp_path)
        plan = tmp_path / ".plan"

        (tmp_path / "feature.txt").write_text("feature")
        _git(tmp_path, "add", "feature.txt")
        _git(tmp_path, "commit", "-m", "feature work")

        result = TransitionResult("active", "closing:review", "work_end")
        commit_transition(plan, result)

        _git(tmp_path, "checkout", "main")
        (tmp_path / "main-change.txt").write_text("main work")
        _git(tmp_path, "add", "main-change.txt")
        _git(tmp_path, "commit", "-m", "main work")
        _git(tmp_path, "checkout", "test-branch")

        rebase = _git(tmp_path, "rebase", "main")
        assert rebase.returncode == 0, f"Rebase failed: {rebase.stderr}"

        assert read_state(plan) == "closing:review"

    def test_multiple_transitions_all_survive_rebase(self, tmp_path):
        _init_workspace(tmp_path)
        plan = tmp_path / ".plan"

        transitions = [
            ("active", "closing:review", "work_end"),
            ("closing:review", "closing:verified", "review_pass"),
        ]
        for from_s, to_s, event in transitions:
            result = TransitionResult(from_state=from_s, new_state=to_s, event=event)
            evidence = {"review_result": "pass"} if event == "review_pass" else None
            commit_transition(plan, result, evidence=evidence)

        _git(tmp_path, "checkout", "main")
        (tmp_path / "main.txt").write_text("main")
        _git(tmp_path, "add", "main.txt")
        _git(tmp_path, "commit", "-m", "main")
        _git(tmp_path, "checkout", "test-branch")
        _git(tmp_path, "rebase", "main")

        assert read_state(plan) == "closing:verified"


class TestInvalidStateRejection:
    def test_write_field_rejects_closing_landed(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text("## State\nstate: active\n\n## Queue\n")
        with pytest.raises(ValueError):
            write_field(plan, "state", "closing:landed")

    def test_write_field_rejects_arbitrary_string(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text("## State\nstate: active\n\n## Queue\n")
        with pytest.raises(ValueError):
            write_field(plan, "state", "banana")

    def test_write_field_rejects_typo_states(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text("## State\nstate: active\n\n## Queue\n")
        typos = ["closig:review", "closing:Landed", "ACTIVE", "idle "]
        for typo in typos:
            with pytest.raises(ValueError, match="Invalid state"):
                write_field(plan, "state", typo)

    def test_write_field_allows_all_valid_states(self, tmp_path):
        for state in sorted(VALID_STATES):
            plan = tmp_path / ".plan"
            plan.write_text("## State\nstate: active\n\n## Queue\n")
            write_field(plan, "state", state)
            assert f"state: {state}" in plan.read_text()

    def test_plan_manager_set_state_blocked(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text("## State\nstate: active\n\n## Queue\n")
        result = subprocess.run(
            [sys.executable,
             str(Path(__file__).parent.parent / "work-slot" / "plan_manager.py"),
             "set-state", str(plan), "key=state", "value=active"],
            capture_output=True, text=True,
        )
        assert result.returncode != 0


class TestLifecycleAuditTrail:
    def test_git_log_shows_transition_history(self, tmp_path):
        _init_workspace(tmp_path)
        plan = tmp_path / ".plan"

        transitions = [
            ("active", "closing:review", "work_end"),
            ("closing:review", "closing:verified", "review_pass"),
            ("closing:verified", "closing:promoted", "promote_pass"),
        ]
        for from_s, to_s, event in transitions:
            result = TransitionResult(from_state=from_s, new_state=to_s, event=event)
            evidence = None
            if event == "review_pass":
                evidence = {"review_result": "pass"}
            elif event == "promote_pass":
                evidence = {"promoted_files": 1, "target_repos": ["test"]}
            commit_transition(plan, result, evidence=evidence)

        log = _git(tmp_path, "log", "--oneline", "--", ".plan")
        lines = log.stdout.strip().splitlines()
        assert len(lines) >= 4  # scaffold + 3 transitions

        assert any("closing:promoted" in l for l in lines)
        assert any("closing:verified" in l for l in lines)
        assert any("closing:review" in l for l in lines)
