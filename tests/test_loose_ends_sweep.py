"""Tests for work-end/loose_ends_sweep.py"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "work-end" / "loose_ends_sweep.py"


class TestDeferredPlanItems:
    def test_finds_deferred_items(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        plan = workspace / ".plan"
        plan.write_text(
            "## State\ncovers: 100\nstate: active\n\n"
            "## Queue\n"
            "- [x] #100 — done\n"
            "- [ ] #101 — pending ← active\n\n"
            "## Deferred\n"
            "- [ ] #102 — deferred: out of scope\n"
        )
        result = subprocess.run(
            [sys.executable, str(SCRIPT),
             f"workspace={workspace}", f"project={tmp_path}",
             "branch=issue-100"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["new_findings"] >= 1

    def test_no_plan_produces_zero_findings(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        result = subprocess.run(
            [sys.executable, str(SCRIPT),
             f"workspace={workspace}", f"project={tmp_path}",
             "branch=issue-100"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["new_findings"] == 0


class TestPriorFindings:
    def test_reads_prior_findings(self, tmp_path):
        workspace = tmp_path / "workspace"
        audit = workspace / ".audit"
        audit.mkdir(parents=True)
        finding = json.dumps({
            "category": "audit", "check": "missing-req",
            "location": "spec:req-3", "detail": "old finding",
            "status": "open", "branch": "issue-100",
            "severity": "warning",
            "timestamp": "2026-08-18T10:00:00Z",
        })
        (audit / "findings.jsonl").write_text(finding + "\n")
        result = subprocess.run(
            [sys.executable, str(SCRIPT),
             f"workspace={workspace}", f"project={tmp_path}",
             "branch=issue-100"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["prior_open"] >= 1

    def test_temporal_filter_excludes_current_cycle(self, tmp_path):
        workspace = tmp_path / "workspace"
        audit = workspace / ".audit"
        audit.mkdir(parents=True)
        now_finding = json.dumps({
            "category": "review", "check": "unsafe-code",
            "location": "src/x.py:42", "detail": "current session",
            "status": "open", "branch": "issue-100",
            "severity": "warning",
            "timestamp": "2026-08-19T15:00:00Z",
        })
        (audit / "findings.jsonl").write_text(now_finding + "\n")
        result = subprocess.run(
            [sys.executable, str(SCRIPT),
             f"workspace={workspace}", f"project={tmp_path}",
             "branch=issue-100",
             "cycle_start=2026-08-19T14:00:00Z"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["prior_open"] == 0


class TestTodoScan:
    def _init_git(self, path):
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", str(path)], capture_output=True)
        subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], capture_output=True)
        subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t.com"], capture_output=True)
        subprocess.run(["git", "-C", str(path), "checkout", "-b", "main"], capture_output=True)
        subprocess.run(["git", "-C", str(path), "commit", "--allow-empty", "-m", "init"], capture_output=True)

    def test_finds_todos_in_changed_files(self, tmp_path):
        project = tmp_path / "project"
        self._init_git(project)
        subprocess.run(["git", "-C", str(project), "checkout", "-b", "issue-100-feat"], capture_output=True)
        (project / "handler.py").write_text("# TODO: handle edge case for issue-100\ndef handler(): pass\n")
        subprocess.run(["git", "-C", str(project), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(project), "commit", "-m", "add handler"], capture_output=True)

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        result = subprocess.run(
            [sys.executable, str(SCRIPT),
             f"workspace={workspace}", f"project={project}",
             "branch=issue-100-feat"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["new_findings"] >= 1

    def test_no_todos_produces_zero(self, tmp_path):
        project = tmp_path / "project"
        self._init_git(project)
        subprocess.run(["git", "-C", str(project), "checkout", "-b", "issue-200-clean"], capture_output=True)
        (project / "clean.py").write_text("def clean(): pass\n")
        subprocess.run(["git", "-C", str(project), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(project), "commit", "-m", "clean"], capture_output=True)

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        result = subprocess.run(
            [sys.executable, str(SCRIPT),
             f"workspace={workspace}", f"project={project}",
             "branch=issue-100"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["new_findings"] == 0


class TestPersistence:
    def test_writes_findings_to_jsonl(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        plan = workspace / ".plan"
        plan.write_text(
            "## State\ncovers: 100\nstate: active\n\n"
            "## Deferred\n"
            "- [ ] #102 — deferred: blocked by upstream\n"
        )
        result = subprocess.run(
            [sys.executable, str(SCRIPT),
             f"workspace={workspace}", f"project={tmp_path}",
             "branch=issue-100"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        findings_path = workspace / ".audit" / "findings.jsonl"
        assert findings_path.exists()
        lines = [l for l in findings_path.read_text().strip().split("\n") if l]
        assert len(lines) >= 1
        entry = json.loads(lines[0])
        assert entry["category"] == "loose-end"
        assert entry["source"] == "loose-ends-sweep"
