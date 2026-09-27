"""Tests for work_sync and sync_pass lifecycle transitions."""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "project"))

from lifecycle import (
    TRANSITION_TABLE,
    EVIDENCE_GATES,
    InvalidTransition,
    TransitionResult,
    commit_transition,
    transition,
    read_state,
    write_state,
)


def _init_git_repo(path: Path, state: str = "active") -> Path:
    subprocess.run(["git", "init", str(path)], capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@test.com"], capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], capture_output=True)
    plan = path / ".plan"
    plan.write_text(
        f"# Work Plan\n\n## State\nbranch: test-branch\nstate: {state}\ncovers: 1\n\n"
        f"## Queue\n- [ ] test#1 — Test\n"
    )
    subprocess.run(["git", "-C", str(path), "add", ".plan"], capture_output=True)
    subprocess.run(["git", "-C", str(path), "commit", "-m", "initial"], capture_output=True)
    return plan


class TestWorkSyncTransition:
    def test_work_sync_in_transition_table(self):
        assert ("active", "work_sync") in TRANSITION_TABLE

    def test_work_sync_goes_to_closing_review(self):
        new_state, effects, _ = TRANSITION_TABLE[("active", "work_sync")]
        assert new_state == "closing:review"

    def test_work_sync_has_pre_close_sweep_effect(self):
        _, effects, _ = TRANSITION_TABLE[("active", "work_sync")]
        assert "pre_close_sweep" in effects

    def test_work_sync_transition_from_active(self, tmp_path):
        plan = _init_git_repo(tmp_path, "active")
        result = transition(plan, "work_sync")
        assert result.from_state == "active"
        assert result.new_state == "closing:review"
        assert result.event == "work_sync"

    def test_work_sync_rejected_from_idle(self, tmp_path):
        plan = tmp_path / ".plan"
        with pytest.raises(InvalidTransition):
            transition(plan, "work_sync")

    def test_work_sync_rejected_from_paused(self, tmp_path):
        plan = _init_git_repo(tmp_path, "paused")
        with pytest.raises(InvalidTransition):
            transition(plan, "work_sync")

    def test_work_sync_rejected_from_closing(self, tmp_path):
        plan = _init_git_repo(tmp_path, "closing:review")
        with pytest.raises(InvalidTransition):
            transition(plan, "work_sync")


class TestSyncPassTransition:
    def test_sync_pass_in_transition_table(self):
        assert ("closing:stamped", "sync_pass") in TRANSITION_TABLE

    def test_sync_pass_goes_to_active(self):
        new_state, effects, _ = TRANSITION_TABLE[("closing:stamped", "sync_pass")]
        assert new_state == "active"

    def test_sync_pass_has_clear_closing_markers_effect(self):
        _, effects, _ = TRANSITION_TABLE[("closing:stamped", "sync_pass")]
        assert "clear_closing_markers" in effects

    def test_sync_pass_transition_from_stamped(self, tmp_path):
        plan = _init_git_repo(tmp_path, "closing:stamped")
        result = transition(plan, "sync_pass")
        assert result.from_state == "closing:stamped"
        assert result.new_state == "active"

    def test_sync_pass_commits_state(self, tmp_path):
        plan = _init_git_repo(tmp_path, "closing:stamped")
        result = TransitionResult(
            from_state="closing:stamped",
            new_state="active",
            event="sync_pass",
        )
        commit_transition(plan, result, evidence={"stamp_shas": {}})
        assert read_state(plan) == "active"
        show = subprocess.run(
            ["git", "-C", str(tmp_path), "show", "HEAD:.plan"],
            capture_output=True, text=True,
        )
        assert "state: active" in show.stdout

    def test_sync_pass_rejected_from_active(self, tmp_path):
        plan = _init_git_repo(tmp_path, "active")
        with pytest.raises(InvalidTransition):
            transition(plan, "sync_pass")


class TestSyncPassEvidenceGating:
    def test_sync_pass_in_evidence_gates(self):
        assert "sync_pass" in EVIDENCE_GATES

    def test_sync_pass_requires_stamp_shas(self):
        assert "stamp_shas" in EVIDENCE_GATES["sync_pass"]
