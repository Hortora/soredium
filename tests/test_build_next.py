"""Tests for plan_manager build-next command."""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "work-slot"))
sys.path.insert(0, str(Path(__file__).parent.parent / "project"))


class TestBuildNext:
    def _run(self, plan_path: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable,
             str(Path(__file__).parent.parent / "work-slot" / "plan_manager.py"),
             "build-next", str(plan_path)],
            capture_output=True, text=True,
        )

    def test_creates_plan_next(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(
            "# Work Plan — test-branch\n\n## State\n"
            "branch: test-branch\nstate: active\ncovers: 1,2,3\n\n"
            "## Queue\n"
            "- [x] test/repo#1 — First issue\n"
            "- [ ] test/repo#2 — Second issue ← active\n"
            "- [ ] test/repo#3 — Third issue\n"
        )
        result = self._run(plan)
        assert result.returncode == 0

        plan_next = tmp_path / ".plan-next"
        assert plan_next.exists()
        content = plan_next.read_text()
        assert "test/repo#2" in content
        assert "test/repo#3" in content
        assert "test/repo#1" not in content

    def test_plan_next_has_active_state(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(
            "# Work Plan — test-branch\n\n## State\n"
            "branch: test-branch\nstate: active\ncovers: 1,2\n\n"
            "## Queue\n"
            "- [x] test/repo#1 — Done\n"
            "- [ ] test/repo#2 — Remaining ← active\n"
        )
        self._run(plan)
        content = (tmp_path / ".plan-next").read_text()
        assert "state: active" in content

    def test_plan_next_preserves_branch(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(
            "# Work Plan — issue-382\n\n## State\n"
            "branch: issue-382\nstate: active\ncovers: 1,2\n\n"
            "## Queue\n"
            "- [x] test/repo#1 — Done\n"
            "- [ ] test/repo#2 — Remaining ← active\n"
        )
        self._run(plan)
        content = (tmp_path / ".plan-next").read_text()
        assert "branch: issue-382" in content

    def test_no_plan_next_when_all_completed(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(
            "# Work Plan — test-branch\n\n## State\n"
            "branch: test-branch\nstate: active\ncovers: 1\n\n"
            "## Queue\n"
            "- [x] test/repo#1 — All done\n"
        )
        result = self._run(plan)
        assert result.returncode == 0
        assert not (tmp_path / ".plan-next").exists()
        assert "NO_REMAINING=yes" in result.stdout

    def test_no_plan_next_when_plan_missing(self, tmp_path):
        result = self._run(tmp_path / ".plan")
        assert result.returncode != 0

    def test_first_uncompleted_is_active(self, tmp_path):
        plan = tmp_path / ".plan"
        plan.write_text(
            "# Work Plan — test-branch\n\n## State\n"
            "branch: test-branch\nstate: active\ncovers: 1,2,3\n\n"
            "## Queue\n"
            "- [x] test/repo#1 — Done\n"
            "- [ ] test/repo#2 — Second\n"
            "- [ ] test/repo#3 — Third\n"
        )
        self._run(plan)
        content = (tmp_path / ".plan-next").read_text()
        assert "← active" in content or "← active" in content
        lines = [l for l in content.splitlines() if "active" in l.lower() and "state:" not in l]
        assert len(lines) == 1
        assert "test/repo#2" in lines[0]
