"""Tests for work-start/branch_create.py library API — create_branches_typed()."""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "work-start"))

from branch_create import create_branches_typed, CreateResult


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "commit", "--allow-empty",
                    "-m", "init"], capture_output=True, check=True)


def test_create_branches_success():
    with tempfile.TemporaryDirectory() as tmp:
        proj = Path(tmp) / "project"
        ws = Path(tmp) / "workspace"
        proj.mkdir()
        ws.mkdir()
        _init_repo(proj)
        _init_repo(ws)
        result = create_branches_typed(str(proj), str(ws), "issue-42")
        assert isinstance(result, CreateResult)
        assert result.branch == "issue-42"
        assert result.project_created is True
        assert result.workspace_created is True
        assert result.error is None


def test_create_branches_with_base():
    with tempfile.TemporaryDirectory() as tmp:
        proj = Path(tmp) / "project"
        ws = Path(tmp) / "workspace"
        proj.mkdir()
        ws.mkdir()
        _init_repo(proj)
        _init_repo(ws)
        result = create_branches_typed(str(proj), str(ws), "issue-42", base="main")
        assert result.project_created is True
        assert result.workspace_created is True


def test_create_branches_project_fails():
    with tempfile.TemporaryDirectory() as tmp:
        proj = Path(tmp) / "not-a-repo"
        ws = Path(tmp) / "workspace"
        proj.mkdir()
        ws.mkdir()
        _init_repo(ws)
        result = create_branches_typed(str(proj), str(ws), "issue-42")
        assert result.project_created is False
        assert result.error is not None


def test_create_branches_workspace_fails_rolls_back():
    with tempfile.TemporaryDirectory() as tmp:
        proj = Path(tmp) / "project"
        ws = Path(tmp) / "not-a-repo"
        proj.mkdir()
        ws.mkdir()
        _init_repo(proj)
        result = create_branches_typed(str(proj), str(ws), "issue-42")
        assert result.workspace_created is False
        assert result.error is not None
        # Verify rollback — project should be back on main
        branch = subprocess.run(
            ["git", "-C", str(proj), "branch", "--show-current"],
            capture_output=True, text=True,
        ).stdout.strip()
        assert branch != "issue-42"


def test_cli_create_branches_still_works():
    """Verify the CLI entry point still returns correct exit code."""
    from branch_create import create_branches
    with tempfile.TemporaryDirectory() as tmp:
        proj = Path(tmp) / "project"
        ws = Path(tmp) / "workspace"
        proj.mkdir()
        ws.mkdir()
        _init_repo(proj)
        _init_repo(ws)
        exit_code = create_branches(str(proj), str(ws), "issue-99", None)
        assert exit_code == 0
