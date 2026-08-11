"""Tests for work-start/scaffold.py library API — scaffold() function."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "work-start"))

from scaffold import scaffold, ScaffoldResult


def test_scaffold_creates_meta_and_journal():
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        result = scaffold(ws, branch="issue-42-fix", project_sha="abc123",
                         issue="42", issue_repo="Hortora/soredium")
        assert isinstance(result, ScaffoldResult)
        assert result.created is True
        meta = Path(result.meta_path)
        assert meta.exists()
        content = meta.read_text()
        assert "state: scaffolded" in content
        assert "issue: 42" in content
        assert "issue-repo: Hortora/soredium" in content


def test_scaffold_creates_journal():
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        result = scaffold(ws, branch="issue-42-fix", project_sha="abc123")
        journal = Path(result.journal_path)
        assert journal.exists()
        assert "Design Journal" in journal.read_text()


def test_scaffold_does_not_overwrite_existing():
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        (ws / "design").mkdir(parents=True)
        (ws / "design" / ".meta").write_text("existing meta\n")
        (ws / "design" / "JOURNAL.md").write_text("existing journal\n")
        result = scaffold(ws, branch="issue-42", project_sha="abc123")
        assert result.created is False
        assert (ws / "design" / ".meta").read_text() == "existing meta\n"


def test_scaffold_force_overwrites():
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        (ws / "design").mkdir(parents=True)
        (ws / "design" / ".meta").write_text("old meta\n")
        (ws / "design" / "JOURNAL.md").write_text("old journal\n")
        result = scaffold(ws, branch="issue-42", project_sha="abc123", force=True)
        assert result.created is True
        assert "state: scaffolded" in (ws / "design" / ".meta").read_text()


def test_scaffold_with_plan():
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        result = scaffold(ws, branch="issue-42", project_sha="abc123",
                         plan=True, today="2026-08-11")
        assert result.plan_path is not None
        plan = Path(result.plan_path)
        assert plan.exists()
        assert "Work Plan" in plan.read_text()


def test_scaffold_with_plan_content():
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        result = scaffold(ws, branch="issue-42", project_sha="abc123",
                         plan=True, plan_content="# Custom Plan\n")
        plan = Path(result.plan_path)
        assert plan.read_text() == "# Custom Plan\n"


def test_scaffold_covers_defaults_to_issue():
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        result = scaffold(ws, branch="issue-42", project_sha="abc123",
                         issue="42")
        content = Path(result.meta_path).read_text()
        assert "covers: 42" in content


def test_scaffold_explicit_covers():
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        result = scaffold(ws, branch="issue-42", project_sha="abc123",
                         issue="42", covers="42 43 44")
        content = Path(result.meta_path).read_text()
        assert "covers: 42 43 44" in content


def test_scaffold_no_plan_path_when_no_plan():
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        result = scaffold(ws, branch="issue-42", project_sha="abc123")
        assert result.plan_path is None
