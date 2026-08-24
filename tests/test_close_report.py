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
        run(["record", str(rp), "step=land", "result=ok", "landed_sha=abc123"])
        data = json.loads(rp.read_text())
        assert "rebase" in data["steps"]
        assert "land" in data["steps"]

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
        run(["record", str(rp), "step=verify", "result=ok", "verified=pass"])
        run(["record", str(rp), "step=promote", "result=ok"])
        run(["record", str(rp), "step=rebase", "result=ok", "branch=b", "base=main"])
        result = run(["render", str(rp)])
        lines = [l for l in result.stdout.splitlines() if l.strip()]
        assert "Artifacts promoted" in lines[0]
        assert "Rebased" in lines[1]
        assert "Verified" in lines[2]

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
        run(["record", str(rp), "step=promote", "result=ok",
             "promoted_files=2", "target_repos=workspace"])
        run(["record", str(rp), "step=rebase", "result=ok", "branch=issue-42-auth", "base=main"])
        run(["record", str(rp), "step=squash", "result=ok", "before=6", "after=2", "strategy=E"])
        run(["record", str(rp), "step=land", "result=ok",
             "landed_sha=deadbeef123", "pushed_repos=project,workspace"])
        run(["record", str(rp), "step=close-issues", "result=ok", "closed=1"])
        run(["record", str(rp), "step=verify", "result=ok", "verified=pass"])
        run(["record", str(rp), "step=scaffold-cleanup", "result=ok"])

        result = run(["render", str(rp)])
        lines = [l for l in result.stdout.splitlines() if l.strip()]
        assert len(lines) == 7
        assert all(l.startswith("✅") for l in lines)

    def test_full_slot_workflow(self, tmp_path):
        """Simulates a complete slot-mode work-end close-out."""
        rp = tmp_path / "report.json"
        run(["init", str(rp)])
        run(["record", str(rp), "step=promote", "result=ok"])
        run(["record", str(rp), "step=rebase", "result=ok", "branch=issue-42", "base=main", "conflicts=yes"])
        run(["record", str(rp), "step=land", "result=ok",
             "landed_sha=abc123", "pushed_repos=project"])
        run(["record", str(rp), "step=close-issues", "result=ok", "closed=1"])
        run(["record", str(rp), "step=verify", "result=ok", "verified=pass"])
        run(["record", str(rp), "step=archive", "result=ok", "slot=11", "dest=worktrees/attic/11"])
        run(["record", str(rp), "step=scaffold-cleanup", "result=ok"])

        result = run(["render", str(rp)])
        lines = [l for l in result.stdout.splitlines() if l.strip()]
        assert any("Slot archived" in l for l in lines)
        assert any("Artifacts promoted" in l for l in lines)


class TestOrchestratorStepNames:
    """Tests for orchestrator step names — must be in STEP_ORDER and STEP_LABELS."""

    def _load_module(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("close_report", str(SCRIPT))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_orchestrator_step_order(self):
        mod = self._load_module()
        expected_steps = [
            "promote", "rebase", "squash", "land",
            "close-issues", "verify", "archive", "scaffold-cleanup",
        ]
        for step in expected_steps:
            assert step in mod.STEP_ORDER, f"{step} missing from STEP_ORDER"

    def test_orchestrator_step_labels(self):
        mod = self._load_module()
        assert mod.STEP_LABELS["promote"] == "Artifacts promoted"
        assert mod.STEP_LABELS["land"] == "Landed"
        assert mod.STEP_LABELS["close-issues"] == "Issues closed"
        assert mod.STEP_LABELS["verify"] == "Verified"

    def test_promote_rendering(self, tmp_path):
        rp = tmp_path / "report.json"
        run(["init", str(rp)])
        run(["record", str(rp), "step=promote", "result=ok",
             "promoted_files=3", "target_repos=workspace,project"])
        result = run(["render", str(rp)])
        assert "Artifacts promoted: 3 files" in result.stdout
        assert "workspace,project" in result.stdout

    def test_promote_no_artifacts(self, tmp_path):
        rp = tmp_path / "report.json"
        run(["init", str(rp)])
        run(["record", str(rp), "step=promote", "result=ok"])
        result = run(["render", str(rp)])
        assert "Artifacts promoted: no artifacts" in result.stdout

    def test_land_rendering(self, tmp_path):
        rp = tmp_path / "report.json"
        run(["init", str(rp)])
        run(["record", str(rp), "step=land", "result=ok",
             "landed_sha=abc1234567890", "pushed_repos=project,workspace"])
        result = run(["render", str(rp)])
        assert "Landed project,workspace (SHA abc1234)" in result.stdout

    def test_land_no_sha(self, tmp_path):
        rp = tmp_path / "report.json"
        run(["init", str(rp)])
        run(["record", str(rp), "step=land", "result=ok"])
        result = run(["render", str(rp)])
        assert "Landed" in result.stdout

    def test_close_issues_rendering(self, tmp_path):
        rp = tmp_path / "report.json"
        run(["init", str(rp)])
        run(["record", str(rp), "step=close-issues", "result=ok", "closed=2"])
        result = run(["render", str(rp)])
        assert "Issues closed (2)" in result.stdout

    def test_verify_pass(self, tmp_path):
        rp = tmp_path / "report.json"
        run(["init", str(rp)])
        run(["record", str(rp), "step=verify", "result=ok", "verified=pass"])
        result = run(["render", str(rp)])
        assert "Verified (pass)" in result.stdout

    def test_verify_failed(self, tmp_path):
        rp = tmp_path / "report.json"
        run(["init", str(rp)])
        run(["record", str(rp), "step=verify", "result=failed", "verified=fail"])
        result = run(["render", str(rp)])
        assert "❌" in result.stdout
        assert "Verified (fail)" in result.stdout