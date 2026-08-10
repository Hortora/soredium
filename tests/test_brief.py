"""Tests for brief/brief.py"""
import subprocess
import sys
from pathlib import Path

BRIEF = Path(__file__).parent.parent / "brief" / "brief.py"
PROJECT_ROOT = Path(__file__).parent.parent


class TestBriefCLI:
    def test_outputs_state_field(self):
        result = subprocess.run(
            [sys.executable, str(BRIEF)],
            capture_output=True, text=True,
            cwd=str(PROJECT_ROOT),
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        lines = result.stdout.strip().splitlines()
        keys = [l.split("=", 1)[0] for l in lines if "=" in l]
        assert "STATE" in keys
        assert "STACK_DEPTH" in keys

    def test_state_values(self):
        result = subprocess.run(
            [sys.executable, str(BRIEF)],
            capture_output=True, text=True,
            cwd=str(PROJECT_ROOT),
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        output = dict(
            l.split("=", 1) for l in result.stdout.strip().splitlines()
            if "=" in l
            and not l.startswith("COMMIT=")
            and not l.startswith("CHECK=")
            and not l.startswith("CLOSED_BRANCH=")
        )
        assert output["STATE"] in (
            "feature_branch", "main_with_stack", "main_idle"
        )

    def test_has_plan_field(self):
        result = subprocess.run(
            [sys.executable, str(BRIEF)],
            capture_output=True, text=True,
            cwd=str(PROJECT_ROOT),
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        output = dict(
            l.split("=", 1) for l in result.stdout.strip().splitlines()
            if "=" in l
            and not l.startswith("COMMIT=")
            and not l.startswith("CHECK=")
            and not l.startswith("CLOSED_BRANCH=")
        )
        assert output["HAS_PLAN"] in ("yes", "no")

    def test_recent_commits_present_on_branch(self):
        result = subprocess.run(
            [sys.executable, str(BRIEF)],
            capture_output=True, text=True,
            cwd=str(PROJECT_ROOT),
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        lines = result.stdout.strip().splitlines()
        scalar = dict(
            l.split("=", 1) for l in lines
            if "=" in l
            and not l.startswith("COMMIT=")
            and not l.startswith("CHECK=")
            and not l.startswith("CLOSED_BRANCH=")
        )
        commit_lines = [l for l in lines if l.startswith("COMMIT=")]
        if scalar.get("STATE") == "feature_branch":
            assert int(scalar["RECENT_COMMITS"]) > 0
            assert len(commit_lines) > 0

    def test_handoff_fields(self):
        result = subprocess.run(
            [sys.executable, str(BRIEF)],
            capture_output=True, text=True,
            cwd=str(PROJECT_ROOT),
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        lines = result.stdout.strip().splitlines()
        keys = [l.split("=", 1)[0] for l in lines if "=" in l]
        assert "HAS_HANDOFF" in keys


class TestBriefResolve:
    def test_resolve_returns_dict(self):
        sys.path.insert(0, str(BRIEF.parent))
        try:
            from brief import resolve
            result = resolve(cwd=str(PROJECT_ROOT))
            assert isinstance(result, dict)
            assert "STATE" in result
            assert "STACK_DEPTH" in result
        finally:
            sys.path.pop(0)
            sys.modules.pop("brief", None)

    def test_resolve_state_is_valid(self):
        sys.path.insert(0, str(BRIEF.parent))
        try:
            from brief import resolve
            result = resolve(cwd=str(PROJECT_ROOT))
            assert result["STATE"] in (
                "feature_branch", "main_with_stack", "main_idle"
            )
        finally:
            sys.path.pop(0)
            sys.modules.pop("brief", None)
