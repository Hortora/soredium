"""Tests for work-start/scaffold.py library API — scaffold() function."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "work-start"))
sys.path.insert(0, str(Path(__file__).parent.parent / "work-slot"))

from scaffold import scaffold, ScaffoldResult
import plan_manager


def test_scaffold_creates_unified_plan_and_journal():
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        result = scaffold(ws, branch="issue-42-fix", project_sha="abc123",
                         issue="42", issue_repo="Hortora/soredium")
        assert isinstance(result, ScaffoldResult)
        assert result.created is True
        plan = Path(result.plan_path)
        assert plan.exists()
        content = plan.read_text()
        assert "## State" in content
        assert "state: scaffolded" in content
        assert "issue-repo: Hortora/soredium" in content
        assert "covers: 42" in content
        assert "## Queue" in content
        assert "#42" in content
        assert "← active" in content
        assert not (ws / "design" / ".meta").exists()


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
        (ws / ".plan").write_text("existing plan\n")
        (ws / "JOURNAL.md").write_text("existing journal\n")
        result = scaffold(ws, branch="issue-42", project_sha="abc123")
        assert result.created is False
        assert (ws / ".plan").read_text() == "existing plan\n"


def test_scaffold_force_overwrites():
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        (ws / "design").mkdir(parents=True)
        (ws / ".plan").write_text("old plan\n")
        (ws / "JOURNAL.md").write_text("old journal\n")
        result = scaffold(ws, branch="issue-42", project_sha="abc123", force=True)
        assert result.created is True
        content = (ws / ".plan").read_text()
        assert "state: scaffolded" in content


def test_scaffold_with_plan_content():
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        content = "# Custom Plan\n\n## State\nstate: scaffolded\nbranch: issue-42\n\n## Queue\n(empty)\n"
        result = scaffold(ws, branch="issue-42", project_sha="abc123",
                         plan_content=content)
        plan = Path(result.plan_path)
        assert plan.read_text() == content


def test_scaffold_covers_defaults_to_issue():
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        result = scaffold(ws, branch="issue-42", project_sha="abc123",
                         issue="42", issue_repo="test/repo")
        content = Path(result.plan_path).read_text()
        assert "covers: 42" in content


def test_scaffold_explicit_covers():
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        result = scaffold(ws, branch="issue-42", project_sha="abc123",
                         issue="42", issue_repo="test/repo", covers="42,43,44")
        content = Path(result.plan_path).read_text()
        assert "covers: 42,43,44" in content


def test_scaffold_without_issue_creates_empty_queue():
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        result = scaffold(ws, branch="spike-explore", project_sha="abc123",
                         today="2026-08-14")
        plan = Path(result.plan_path)
        content = plan.read_text()
        assert "## State" in content
        assert "branch: spike-explore" in content
        assert "(empty" in content


def test_scaffold_plan_is_parseable():
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        result = scaffold(ws, branch="issue-42-fix", project_sha="abc123",
                         issue="42", issue_repo="Hortora/soredium",
                         today="2026-08-14")
        tree = plan_manager.parse_plan(Path(result.plan_path))
        assert tree.state["branch"] == "issue-42-fix"
        assert tree.state["state"] == "scaffolded"
        assert len(tree.queue) == 1
        assert tree.queue[0].issue_number == 42
        assert tree.queue[0].active is True


def test_scaffold_result_has_no_meta_path():
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        result = scaffold(ws, branch="issue-42", project_sha="abc123")
        assert not hasattr(result, 'meta_path')
        assert result.plan_path is not None


class TestBypassClosure:
    """scaffold must route .plan writes through plan_io."""

    def test_new_plan_uses_plan_io_write_plan(self, monkeypatch):
        import scaffold as _scaffold
        calls = []
        original_write_plan = _scaffold.write_plan

        def tracking(path, content):
            calls.append(str(path))
            return original_write_plan(path, content)

        monkeypatch.setattr(_scaffold, "write_plan", tracking)

        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            scaffold(ws, branch="issue-42", project_sha="abc123",
                     issue="42", issue_repo="org/repo")
            assert len(calls) == 1

    def test_raw_content_uses_plan_io_write_plan(self, monkeypatch):
        import scaffold as _scaffold
        calls = []
        original_write_plan = _scaffold.write_plan

        def tracking(path, content):
            calls.append(str(path))
            return original_write_plan(path, content)

        monkeypatch.setattr(_scaffold, "write_plan", tracking)

        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            scaffold(ws, branch="issue-42", project_sha="abc123",
                     plan_content="## State\nstate: scaffolded\n\n## Queue\n")
            assert len(calls) == 1

    def test_state_patch_uses_plan_io_write_field(self, monkeypatch):
        import scaffold as _scaffold
        calls = []
        original_write_field = _scaffold.write_field

        def tracking(path, field, value):
            calls.append((field, value))
            return original_write_field(path, field, value)

        monkeypatch.setattr(_scaffold, "write_field", tracking)

        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / ".plan").write_text("## State\nbranch: test\n\n## Queue\n")
            (ws / "JOURNAL.md").write_text("# Journal\n")
            scaffold(ws, branch="test", project_sha="abc123")
            assert ("state", "active") in calls
