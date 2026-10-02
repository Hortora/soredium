"""Tests for work-end/loose_ends_sweep.py"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "work-end"))

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


class TestExtractIssueRefs:
    def test_standard_refs(self):
        from loose_ends_sweep import _extract_issue_refs
        assert _extract_issue_refs("feat(#100): something") == {100}

    def test_refs_keyword(self):
        from loose_ends_sweep import _extract_issue_refs
        assert _extract_issue_refs("Refs #42") == {42}

    def test_closes_keyword(self):
        from loose_ends_sweep import _extract_issue_refs
        assert _extract_issue_refs("Closes #55 and Refs #56") == {55, 56}

    def test_parenthesized(self):
        from loose_ends_sweep import _extract_issue_refs
        assert _extract_issue_refs("add feature (#77)") == {77}

    def test_multiple_in_one_message(self):
        from loose_ends_sweep import _extract_issue_refs
        refs = _extract_issue_refs("feat(#100): also refs #200 and closes #300")
        assert refs == {100, 200, 300}

    def test_no_refs(self):
        from loose_ends_sweep import _extract_issue_refs
        assert _extract_issue_refs("chore: update deps") == set()


class TestScanCommitCoverage:
    def _init_git(self, path):
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", str(path)], capture_output=True)
        subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], capture_output=True)
        subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t.com"], capture_output=True)
        subprocess.run(["git", "-C", str(path), "checkout", "-b", "main"], capture_output=True)
        subprocess.run(["git", "-C", str(path), "commit", "--allow-empty", "-m", "init"], capture_output=True)

    def test_flags_commits_outside_covers(self, tmp_path):
        from loose_ends_sweep import scan_commit_coverage
        project = tmp_path / "project"
        self._init_git(project)
        subprocess.run(["git", "-C", str(project), "checkout", "-b", "issue-100-feat"], capture_output=True)
        subprocess.run(["git", "-C", str(project), "commit", "--allow-empty", "-m", "feat(#100): tracked work"], capture_output=True)
        subprocess.run(["git", "-C", str(project), "commit", "--allow-empty", "-m", "feat(#200): orphaned work"], capture_output=True)
        subprocess.run(["git", "-C", str(project), "commit", "--allow-empty", "-m", "feat(#300): also orphaned"], capture_output=True)

        findings = scan_commit_coverage(str(project), "issue-100-feat", "100")
        orphaned_issues = {f["issue_num"] for f in findings}
        assert orphaned_issues == {200, 300}

    def test_no_findings_when_all_covered(self, tmp_path):
        from loose_ends_sweep import scan_commit_coverage
        project = tmp_path / "project"
        self._init_git(project)
        subprocess.run(["git", "-C", str(project), "checkout", "-b", "issue-100-feat"], capture_output=True)
        subprocess.run(["git", "-C", str(project), "commit", "--allow-empty", "-m", "feat(#100): work A"], capture_output=True)
        subprocess.run(["git", "-C", str(project), "commit", "--allow-empty", "-m", "feat(#101): work B"], capture_output=True)

        findings = scan_commit_coverage(str(project), "issue-100-feat", "100,101")
        assert findings == []

    def test_ignores_ceremony_commits(self, tmp_path):
        from loose_ends_sweep import scan_commit_coverage
        project = tmp_path / "project"
        self._init_git(project)
        subprocess.run(["git", "-C", str(project), "checkout", "-b", "issue-100-feat"], capture_output=True)
        subprocess.run(["git", "-C", str(project), "commit", "--allow-empty", "-m", "feat(#100): real work"], capture_output=True)
        subprocess.run(["git", "-C", str(project), "commit", "--allow-empty", "-m", "chore: branch closed — landed as abc on main"], capture_output=True)

        findings = scan_commit_coverage(str(project), "issue-100-feat", "100")
        assert findings == []

    def test_empty_covers_returns_empty(self, tmp_path):
        from loose_ends_sweep import scan_commit_coverage
        findings = scan_commit_coverage(str(tmp_path), "branch", "")
        assert findings == []

    def test_multi_issue_commit(self, tmp_path):
        """A commit referencing both a covered and uncovered issue flags only the uncovered one."""
        from loose_ends_sweep import scan_commit_coverage
        project = tmp_path / "project"
        self._init_git(project)
        subprocess.run(["git", "-C", str(project), "checkout", "-b", "issue-100-feat"], capture_output=True)
        subprocess.run(["git", "-C", str(project), "commit", "--allow-empty", "-m", "feat(#100): also refs #999"], capture_output=True)

        findings = scan_commit_coverage(str(project), "issue-100-feat", "100")
        assert len(findings) == 1
        assert findings[0]["issue_num"] == 999

    def test_integration_via_script(self, tmp_path):
        """Full integration test: script surfaces commit-outside-covers findings."""
        project = tmp_path / "project"
        self._init_git(project)
        subprocess.run(["git", "-C", str(project), "checkout", "-b", "issue-100-feat"], capture_output=True)
        subprocess.run(["git", "-C", str(project), "commit", "--allow-empty", "-m", "feat(#100): tracked"], capture_output=True)
        subprocess.run(["git", "-C", str(project), "commit", "--allow-empty", "-m", "feat(#500): orphaned"], capture_output=True)

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        result = subprocess.run(
            [sys.executable, str(SCRIPT),
             f"workspace={workspace}", f"project={project}",
             "branch=issue-100-feat", "covers=100", "base_branch=main"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["new_findings"] >= 1

        findings_path = workspace / ".audit" / "findings.jsonl"
        assert findings_path.exists()
        lines = [json.loads(l) for l in findings_path.read_text().strip().split("\n") if l]
        coverage_findings = [f for f in lines if f.get("check") == "commit-outside-covers"]
        assert len(coverage_findings) == 1
        assert coverage_findings[0]["issue_num"] == 500


class TestClassifyFile:
    def test_src(self):
        from loose_ends_sweep import _classify_file
        assert _classify_file("src/main/java/Foo.java") == "src"

    def test_test(self):
        from loose_ends_sweep import _classify_file
        assert _classify_file("src/test/java/FooTest.java") == "test"

    def test_config(self):
        from loose_ends_sweep import _classify_file
        assert _classify_file("application.yaml") == "config"

    def test_spec(self):
        from loose_ends_sweep import _classify_file
        assert _classify_file("handler.spec.ts") == "test"


class TestScanOrphanedContent:
    def _init_git(self, path):
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", str(path)], capture_output=True)
        subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], capture_output=True)
        subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t.com"], capture_output=True)
        subprocess.run(["git", "-C", str(path), "checkout", "-b", "main"], capture_output=True)

    def test_detects_orphaned_added_files(self, tmp_path):
        from loose_ends_sweep import scan_orphaned_content
        project = tmp_path / "project"
        self._init_git(project)
        (project / "base.py").write_text("base\n")
        subprocess.run(["git", "-C", str(project), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(project), "commit", "-m", "init"], capture_output=True)

        subprocess.run(["git", "-C", str(project), "checkout", "-b", "feat-branch"], capture_output=True)
        (project / "orphan.py").write_text("orphan code\n")
        (project / "landed.py").write_text("will land\n")
        subprocess.run(["git", "-C", str(project), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(project), "commit", "-m", "feat(#42): add files"], capture_output=True)

        subprocess.run(["git", "-C", str(project), "checkout", "main"], capture_output=True)
        (project / "landed.py").write_text("will land\n")
        subprocess.run(["git", "-C", str(project), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(project), "commit", "-m", "land landed.py"], capture_output=True)

        subprocess.run(["git", "-C", str(project), "checkout", "feat-branch"], capture_output=True)

        findings = scan_orphaned_content(str(project), "feat-branch")
        orphaned_files = {f["location"] for f in findings}
        assert "orphan.py" in orphaned_files
        assert "landed.py" not in orphaned_files

    def test_no_findings_when_all_landed(self, tmp_path):
        from loose_ends_sweep import scan_orphaned_content
        project = tmp_path / "project"
        self._init_git(project)
        (project / "base.py").write_text("base\n")
        subprocess.run(["git", "-C", str(project), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(project), "commit", "-m", "init"], capture_output=True)

        subprocess.run(["git", "-C", str(project), "checkout", "-b", "feat-branch"], capture_output=True)
        (project / "new.py").write_text("new code\n")
        subprocess.run(["git", "-C", str(project), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(project), "commit", "-m", "add new.py"], capture_output=True)

        subprocess.run(["git", "-C", str(project), "checkout", "main"], capture_output=True)
        (project / "new.py").write_text("new code\n")
        subprocess.run(["git", "-C", str(project), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(project), "commit", "-m", "land new.py"], capture_output=True)

        subprocess.run(["git", "-C", str(project), "checkout", "feat-branch"], capture_output=True)

        findings = scan_orphaned_content(str(project), "feat-branch")
        assert findings == []

    def test_includes_file_type_and_commit(self, tmp_path):
        from loose_ends_sweep import scan_orphaned_content
        project = tmp_path / "project"
        self._init_git(project)
        subprocess.run(["git", "-C", str(project), "commit", "--allow-empty", "-m", "init"], capture_output=True)

        subprocess.run(["git", "-C", str(project), "checkout", "-b", "feat-branch"], capture_output=True)
        (project / "SomeTest.java").write_text("test\n")
        subprocess.run(["git", "-C", str(project), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(project), "commit", "-m", "feat(#99): add test"], capture_output=True)

        findings = scan_orphaned_content(str(project), "feat-branch")
        assert len(findings) == 1
        assert findings[0]["file_type"] == "test"
        assert findings[0]["introducing_commit"] != ""
        assert 99 in findings[0]["issue_refs"]

    def test_survives_squash(self, tmp_path):
        """Content check works after squash — doesn't depend on individual commit messages."""
        from loose_ends_sweep import scan_orphaned_content
        project = tmp_path / "project"
        self._init_git(project)
        subprocess.run(["git", "-C", str(project), "commit", "--allow-empty", "-m", "init"], capture_output=True)

        subprocess.run(["git", "-C", str(project), "checkout", "-b", "feat-branch"], capture_output=True)
        (project / "a.py").write_text("a\n")
        subprocess.run(["git", "-C", str(project), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(project), "commit", "-m", "feat(#1): add a"], capture_output=True)
        (project / "b.py").write_text("b\n")
        subprocess.run(["git", "-C", str(project), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(project), "commit", "-m", "feat(#2): add b"], capture_output=True)

        subprocess.run(["git", "-C", str(project), "reset", "--soft", "HEAD~2"], capture_output=True)
        subprocess.run(["git", "-C", str(project), "commit", "-m", "squashed: add a and b"], capture_output=True)

        findings = scan_orphaned_content(str(project), "feat-branch")
        orphaned_files = {f["location"] for f in findings}
        assert "a.py" in orphaned_files
        assert "b.py" in orphaned_files

    def test_integration_via_script(self, tmp_path):
        """Full integration: script surfaces orphaned-content findings."""
        project = tmp_path / "project"
        self._init_git(project)
        subprocess.run(["git", "-C", str(project), "commit", "--allow-empty", "-m", "init"], capture_output=True)

        subprocess.run(["git", "-C", str(project), "checkout", "-b", "feat-branch"], capture_output=True)
        (project / "orphan.py").write_text("orphan\n")
        subprocess.run(["git", "-C", str(project), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(project), "commit", "-m", "feat(#42): add orphan"], capture_output=True)

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        result = subprocess.run(
            [sys.executable, str(SCRIPT),
             f"workspace={workspace}", f"project={project}",
             "branch=feat-branch", "covers=42", "base_branch=main"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["new_findings"] >= 1

        findings_path = workspace / ".audit" / "findings.jsonl"
        lines = [json.loads(l) for l in findings_path.read_text().strip().split("\n") if l]
        content_findings = [f for f in lines if f.get("check") == "orphaned-content"]
        assert len(content_findings) == 1
        assert content_findings[0]["location"] == "orphan.py"
