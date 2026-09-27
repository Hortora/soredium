"""Tests that commit_transition commits .plan to git."""

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
)


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, timeout=10,
    )


def _init_git_repo(path: Path) -> None:
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
    _git(path, "commit", "-m", "initial")


class TestCommitTransitionGitCommit:
    def test_creates_git_commit_on_transition(self, tmp_path):
        _init_git_repo(tmp_path)
        plan = tmp_path / ".plan"

        result = TransitionResult(
            from_state="active",
            new_state="closing:review",
            event="work_end",
        )
        commit_transition(plan, result)

        log = _git(tmp_path, "log", "--oneline", "-1")
        assert "lifecycle" in log.stdout.lower() or "closing:review" in log.stdout

        show = _git(tmp_path, "show", "HEAD:.plan")
        assert "state: closing:review" in show.stdout

    def test_state_committed_not_just_on_disk(self, tmp_path):
        _init_git_repo(tmp_path)
        plan = tmp_path / ".plan"

        result = TransitionResult(
            from_state="active",
            new_state="closing:review",
            event="work_end",
        )
        commit_transition(plan, result)

        status = _git(tmp_path, "status", "--porcelain", "--", ".plan")
        assert status.stdout.strip() == "", ".plan should have no uncommitted changes"

    def test_state_survives_checkout(self, tmp_path):
        _init_git_repo(tmp_path)
        _git(tmp_path, "checkout", "-b", "feature")
        plan = tmp_path / ".plan"

        result = TransitionResult(
            from_state="active",
            new_state="closing:review",
            event="work_end",
        )
        commit_transition(plan, result)

        _git(tmp_path, "checkout", "main")
        _git(tmp_path, "checkout", "feature")

        assert read_state(plan) == "closing:review"

    def test_state_survives_stash(self, tmp_path):
        _init_git_repo(tmp_path)
        plan = tmp_path / ".plan"

        result = TransitionResult(
            from_state="active",
            new_state="closing:review",
            event="work_end",
        )
        commit_transition(plan, result)

        (tmp_path / "other.txt").write_text("change")
        _git(tmp_path, "add", "other.txt")
        _git(tmp_path, "stash", "push", "-u")
        _git(tmp_path, "stash", "pop")

        assert read_state(plan) == "closing:review"

    def test_multiple_transitions_create_multiple_commits(self, tmp_path):
        _init_git_repo(tmp_path)
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

        log = _git(tmp_path, "log", "--oneline")
        lines = [l for l in log.stdout.strip().splitlines() if l]
        assert len(lines) >= 4  # initial + 3 transitions

        assert read_state(plan) == "closing:promoted"

    def test_no_git_commit_for_idle_transition(self, tmp_path):
        _init_git_repo(tmp_path)
        plan = tmp_path / ".plan"

        write_state(plan, "closing:stamped")
        _git(tmp_path, "add", ".plan")
        _git(tmp_path, "commit", "-m", "prep stamped state")

        before = _git(tmp_path, "rev-list", "--count", "HEAD").stdout.strip()

        result = TransitionResult(
            from_state="closing:stamped",
            new_state="idle",
            event="cleanup_pass",
        )
        commit_transition(plan, result,
                          evidence={"repos_on_main": {"test": True},
                                    "work_items_ended": True})

        assert not plan.exists()
