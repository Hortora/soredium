"""Tests for promote_plan_next orchestrator step."""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "work-end"))
sys.path.insert(0, str(Path(__file__).parent.parent / "project"))

from work_end_orchestrator import (
    OrchestratorContext,
    STEPS,
    _promote_plan_next_inline,
)


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init", str(path)], capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@test.com"], capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], capture_output=True)
    (path / ".gitkeep").write_text("")
    subprocess.run(["git", "-C", str(path), "add", "."], capture_output=True)
    subprocess.run(["git", "-C", str(path), "commit", "-m", "initial"], capture_output=True)


def _make_ctx(workspace: Path, **overrides) -> OrchestratorContext:
    defaults = dict(
        workspace=workspace,
        project=workspace,
        branch="test-branch",
        base_branch="main",
        meta_state="active",
        on_main=False,
        in_slot=False,
        covers="1",
        issue_repo="test/repo",
        progress={},
        mode="sync",
    )
    defaults.update(overrides)
    return OrchestratorContext(**defaults)


class TestPromotePlanNextInline:
    def test_promotes_plan_next_to_plan(self, tmp_path):
        _init_git_repo(tmp_path)
        plan = tmp_path / ".plan"
        plan.write_text("# Old Plan\n\n## State\nstate: active\n\n## Queue\n- [x] test/repo#1 — Done\n")
        plan_next = tmp_path / ".plan-next"
        plan_next.write_text("# Work Plan\n\n## State\nstate: active\n\n## Queue\n- [ ] test/repo#2 — Next\n")
        subprocess.run(["git", "-C", str(tmp_path), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "scaffold"], capture_output=True)

        ctx = _make_ctx(tmp_path)
        result = _promote_plan_next_inline(ctx)

        assert result["PROMOTED"] == "yes"
        assert plan.exists()
        assert not plan_next.exists()
        assert "test/repo#2" in plan.read_text()

    def test_promotes_handoff_next(self, tmp_path):
        _init_git_repo(tmp_path)
        handoff = tmp_path / "HANDOFF.md"
        handoff.write_text("# Old Handoff\n")
        handoff_next = tmp_path / "HANDOFF-next.md"
        handoff_next.write_text("# New Handoff\n")
        subprocess.run(["git", "-C", str(tmp_path), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "scaffold"], capture_output=True)

        ctx = _make_ctx(tmp_path)
        result = _promote_plan_next_inline(ctx)

        assert handoff.exists()
        assert not handoff_next.exists()
        assert "New Handoff" in handoff.read_text()

    def test_noop_when_no_next_files(self, tmp_path):
        _init_git_repo(tmp_path)
        ctx = _make_ctx(tmp_path)
        result = _promote_plan_next_inline(ctx)

        assert result["PROMOTED"] == "no"
        assert result["REASON"] == "no_next_files"

    def test_commits_to_git(self, tmp_path):
        _init_git_repo(tmp_path)
        plan_next = tmp_path / ".plan-next"
        plan_next.write_text("# Work Plan\n\n## State\nstate: active\n\n## Queue\n- [ ] test/repo#1 — Work\n")
        subprocess.run(["git", "-C", str(tmp_path), "add", ".plan-next"], capture_output=True)
        subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "add next"], capture_output=True)

        ctx = _make_ctx(tmp_path)
        _promote_plan_next_inline(ctx)

        log = subprocess.run(
            ["git", "-C", str(tmp_path), "log", "--oneline", "-1"],
            capture_output=True, text=True,
        )
        assert "promote" in log.stdout.lower()

    def test_dry_run_does_not_modify(self, tmp_path):
        _init_git_repo(tmp_path)
        plan_next = tmp_path / ".plan-next"
        plan_next.write_text("# Next\n")
        subprocess.run(["git", "-C", str(tmp_path), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "add"], capture_output=True)

        ctx = _make_ctx(tmp_path, dry_run=True)
        result = _promote_plan_next_inline(ctx)

        assert plan_next.exists()
        assert result["PROMOTED"] == "yes"


class TestPromotePlanNextStep:
    def test_step_exists_in_steps(self):
        names = [s.name for s in STEPS]
        assert "promote_plan_next" in names

    def test_step_is_mechanical(self):
        step = next(s for s in STEPS if s.name == "promote_plan_next")
        assert step.step_type == "mechanical"

    def test_step_has_postcondition(self):
        step = next(s for s in STEPS if s.name == "promote_plan_next")
        assert step.postcondition_fn is not None

    def test_step_after_sync_pass(self):
        names = [s.name for s in STEPS]
        sync_idx = names.index("sync_pass")
        promote_idx = names.index("promote_plan_next")
        assert promote_idx > sync_idx
