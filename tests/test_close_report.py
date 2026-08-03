"""Tests for work-end/close_report.py"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "work-end" / "close_report.py"


def run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        capture_output=True, text=True,
    )


class TestInit:
    def test_creates_empty_report(self, tmp_path):
        rp = tmp_path / "report.json"
        result = run(["init", str(rp)])
        assert result.returncode == 0
        assert "INIT=yes" in result.stdout
        data = json.loads(rp.read_text())
        assert data == {"steps": {}}


class TestRecord:
    def test_records_step(self, tmp_path):
        rp = tmp_path / "report.json"
        run(["init", str(rp)])
        result = run(["record", str(rp), "step=rebase", "result=ok", "branch=issue-1", "base=main"])
        assert result.returncode == 0
        assert "RECORDED=rebase" in result.stdout
        data = json.loads(rp.read_text())
        assert data["steps"]["rebase"]["result"] == "ok"
        assert data["steps"]["rebase"]["branch"] == "issue-1"

    def test_records_multiple_steps(self, tmp_path):
        rp = tmp_path / "report.json"
        run(["init", str(rp)])
        run(["record", str(rp), "step=rebase", "result=ok"])
        run(["record", str(rp), "step=merge", "result=ok", "method=fast-forward"])
        data = json.loads(rp.read_text())
        assert "rebase" in data["steps"]
        assert "merge" in data["steps"]

    def test_auto_init_on_missing_file(self, tmp_path):
        rp = tmp_path / "report.json"
        result = run(["record", str(rp), "step=rebase", "result=ok"])
        assert result.returncode == 0
        assert rp.exists()

    def test_missing_step_errors(self, tmp_path):
        rp = tmp_path / "report.json"
        run(["init", str(rp)])
        result = run(["record", str(rp), "result=ok"])
        assert result.returncode == 1


class TestRender:
    def test_empty_report(self, tmp_path):
        rp = tmp_path / "report.json"
        run(["init", str(rp)])
        result = run(["render", str(rp)])
        assert result.returncode == 0
        assert "(no steps recorded)" in result.stdout

    def test_missing_file_errors(self, tmp_path):
        rp = tmp_path / "nonexistent.json"
        result = run(["render", str(rp)])
        assert result.returncode == 1

    def test_rebase_ok(self, tmp_path):
        rp = tmp_path / "report.json"
        run(["init", str(rp)])
        run(["record", str(rp), "step=rebase", "result=ok", "branch=issue-5-fix", "base=main"])
        result = run(["render", str(rp)])
        assert "✅ Rebased issue-5-fix onto main" in result.stdout

    def test_rebase_with_conflicts(self, tmp_path):
        rp = tmp_path / "report.json"
        run(["init", str(rp)])
        run(["record", str(rp), "step=rebase", "result=ok", "branch=issue-5", "base=main", "conflicts=yes"])
        result = run(["render", str(rp)])
        assert "(resolved conflicts)" in result.stdout

    def test_squash_rendering(self, tmp_path):
        rp = tmp_path / "report.json"
        run(["init", str(rp)])
        run(["record", str(rp), "step=squash", "result=ok", "before=8", "after=3", "strategy=B"])
        result = run(["render", str(rp)])
        assert "✅ Squashed 8 → 3 commits, strategy B" in result.stdout

    def test_merge_rendering(self, tmp_path):
        rp = tmp_path / "report.json"
        run(["init", str(rp)])
        run(["record", str(rp), "step=merge", "result=ok", "method=fast-forward", "files=5", "insertions=42"])
        result = run(["render", str(rp)])
        assert "✅ Merged to main via fast-forward (5 files, 42 insertions)" in result.stdout

    def test_push_fork_rendering(self, tmp_path):
        rp = tmp_path / "report.json"
        run(["init", str(rp)])
        run(["record", str(rp), "step=push-fork", "result=ok", "remote=origin", "branch=main"])
        result = run(["render", str(rp)])
        assert "✅ Pushed to origin (main)" in result.stdout

    def test_push_failed(self, tmp_path):
        rp = tmp_path / "report.json"
        run(["init", str(rp)])
        run(["record", str(rp), "step=push-fork", "result=failed", "remote=origin"])
        result = run(["render", str(rp)])
        assert "❌ Pushed to origin" in result.stdout

    def test_artifacts_rendering(self, tmp_path):
        rp = tmp_path / "report.json"
        run(["init", str(rp)])
        run(["record", str(rp), "step=artifacts", "result=ok",
             "workspace_promoted=2", "project_promoted=1",
             "specs_cleaned=1", "issues_closed=3",
             "blog_published=1", "blog_dest=/path/blog",
             "plans_archived=0"])
        result = run(["render", str(rp)])
        assert "2 to workspace, 1 to project" in result.stdout
        assert "3 issues closed" in result.stdout
        assert "1 blog entries → /path/blog" in result.stdout

    def test_journal_merge_rendering(self, tmp_path):
        rp = tmp_path / "report.json"
        run(["init", str(rp)])
        run(["record", str(rp), "step=journal-merge", "result=ok", "sections=4", "target=ARC42STORIES.MD"])
        result = run(["render", str(rp)])
        assert "✅ Journal merged → ARC42STORIES.MD (4 sections)" in result.stdout

    def test_stamp_rendering(self, tmp_path):
        rp = tmp_path / "report.json"
        run(["init", str(rp)])
        run(["record", str(rp), "step=stamp-project", "result=ok", "branch=issue-5", "landed_sha=abc1234567890"])
        result = run(["render", str(rp)])
        assert "✅ Stamped project branch (issue-5) — landed as abc12345" in result.stdout

    def test_hygiene_clean(self, tmp_path):
        rp = tmp_path / "report.json"
        run(["init", str(rp)])
        run(["record", str(rp), "step=hygiene", "result=ok", "findings=0"])
        result = run(["render", str(rp)])
        assert "✅ Hygiene scan (clean)" in result.stdout

    def test_hygiene_findings(self, tmp_path):
        rp = tmp_path / "report.json"
        run(["init", str(rp)])
        run(["record", str(rp), "step=hygiene", "result=ok", "findings=3"])
        result = run(["render", str(rp)])
        assert "✅ Hygiene scan (3 findings)" in result.stdout

    def test_worktree_remove_rendering(self, tmp_path):
        rp = tmp_path / "report.json"
        run(["init", str(rp)])
        run(["record", str(rp), "step=worktree-remove", "result=ok", "count=3", "names=devtown,engine,workspace"])
        result = run(["render", str(rp)])
        assert "3 worktrees (devtown,engine,workspace)" in result.stdout

    def test_archive_rendering(self, tmp_path):
        rp = tmp_path / "report.json"
        run(["init", str(rp)])
        run(["record", str(rp), "step=archive", "result=ok", "slot=11", "dest=worktrees/attic/11"])
        result = run(["render", str(rp)])
        assert "✅ Slot archived slot 11 → worktrees/attic/11" in result.stdout

    def test_step_ordering(self, tmp_path):
        """Steps render in canonical order regardless of record order."""
        rp = tmp_path / "report.json"
        run(["init", str(rp)])
        run(["record", str(rp), "step=stamp-project", "result=ok", "branch=b"])
        run(["record", str(rp), "step=rebase", "result=ok", "branch=b", "base=main"])
        run(["record", str(rp), "step=merge", "result=ok", "method=ff"])
        result = run(["render", str(rp)])
        lines = [l for l in result.stdout.splitlines() if l.strip()]
        assert "Rebased" in lines[0]
        assert "Merged" in lines[1]
        assert "Stamped" in lines[2]

    def test_unknown_step_renders(self, tmp_path):
        """Unknown steps appear at the end with kv summary."""
        rp = tmp_path / "report.json"
        run(["init", str(rp)])
        run(["record", str(rp), "step=custom-step", "result=ok", "detail=something"])
        result = run(["render", str(rp)])
        assert "custom-step" in result.stdout
        assert "detail=something" in result.stdout

    def test_full_normal_workflow(self, tmp_path):
        """Simulates a complete normal (non-slot) work-end close-out."""
        rp = tmp_path / "report.json"
        run(["init", str(rp)])
        run(["record", str(rp), "step=rebase", "result=ok", "branch=issue-42-auth", "base=main"])
        run(["record", str(rp), "step=squash", "result=ok", "before=6", "after=2", "strategy=E"])
        run(["record", str(rp), "step=merge", "result=ok", "method=fast-forward", "files=4", "insertions=120"])
        run(["record", str(rp), "step=push-fork", "result=ok", "remote=origin", "branch=main"])
        run(["record", str(rp), "step=push-blessed", "result=ok", "remote=upstream", "branch=main"])
        run(["record", str(rp), "step=artifacts", "result=ok",
             "workspace_promoted=1", "project_promoted=0",
             "specs_cleaned=1", "issues_closed=1",
             "blog_published=0", "plans_archived=0"])
        run(["record", str(rp), "step=journal-merge", "result=ok", "sections=2", "target=ARC42STORIES.MD"])
        run(["record", str(rp), "step=stamp-project", "result=ok", "branch=issue-42-auth", "landed_sha=deadbeef123"])
        run(["record", str(rp), "step=stamp-workspace", "result=ok", "branch=issue-42-auth", "landed_sha=cafebabe456"])
        run(["record", str(rp), "step=hygiene", "result=ok", "findings=0"])

        result = run(["render", str(rp)])
        lines = [l for l in result.stdout.splitlines() if l.strip()]
        assert len(lines) == 10
        assert all(l.startswith("✅") for l in lines)

    def test_full_slot_workflow(self, tmp_path):
        """Simulates a complete slot-mode work-end close-out."""
        rp = tmp_path / "report.json"
        run(["init", str(rp)])
        run(["record", str(rp), "step=rebase", "result=ok", "branch=issue-42", "base=main", "conflicts=yes"])
        run(["record", str(rp), "step=merge", "result=ok", "method=fast-forward", "files=2", "insertions=8"])
        run(["record", str(rp), "step=push-fork", "result=ok", "remote=origin", "branch=main"])
        run(["record", str(rp), "step=artifacts", "result=ok",
             "workspace_promoted=0", "project_promoted=0",
             "specs_cleaned=0", "issues_closed=1",
             "blog_published=0", "plans_archived=0"])
        run(["record", str(rp), "step=stamp-project", "result=ok", "branch=issue-42"])
        run(["record", str(rp), "step=stamp-workspace", "result=ok", "branch=issue-42"])
        run(["record", str(rp), "step=worktree-remove", "result=ok", "count=3", "names=devtown,engine,workspace"])
        run(["record", str(rp), "step=archive", "result=ok", "slot=11", "dest=worktrees/attic/11"])

        result = run(["render", str(rp)])
        lines = [l for l in result.stdout.splitlines() if l.strip()]
        assert any("Worktrees removed" in l for l in lines)
        assert any("Slot archived" in l for l in lines)