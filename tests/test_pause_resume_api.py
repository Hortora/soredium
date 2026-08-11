"""Tests for pause_exec.py and resume_exec.py library APIs."""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "work-pause"))
sys.path.insert(0, str(Path(__file__).parent.parent / "work-resume"))

from pause_exec import PauseWipResult, commit_wip_typed
from resume_exec import (
    ResumeCheckoutResult, ResumeRebaseResult, ResumeResetResult,
    checkout_branches_typed, rebase_typed, reset_wip_typed,
)


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "commit", "--allow-empty",
                    "-m", "init"], capture_output=True, check=True)


def test_commit_wip_clean_tree():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        repo.mkdir()
        _init_repo(repo)
        result = commit_wip_typed(str(repo), "WIP: test")
        assert isinstance(result, PauseWipResult)
        assert result.committed is False
        assert result.error is None


def test_commit_wip_dirty_tree():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        repo.mkdir()
        _init_repo(repo)
        (repo / "file.txt").write_text("dirty")
        result = commit_wip_typed(str(repo), "WIP: test pause")
        assert isinstance(result, PauseWipResult)
        assert result.committed is True
        assert result.message == "WIP: test pause"


def test_commit_wip_not_a_repo():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "not-a-repo"
        repo.mkdir()
        result = commit_wip_typed(str(repo), "WIP: test")
        assert result.committed is False
        assert result.error is not None


def test_checkout_branches_typed_success():
    with tempfile.TemporaryDirectory() as tmp:
        proj = Path(tmp) / "project"
        ws = Path(tmp) / "workspace"
        proj.mkdir()
        ws.mkdir()
        _init_repo(proj)
        _init_repo(ws)
        subprocess.run(["git", "-C", str(proj), "checkout", "-b", "issue-42"],
                       capture_output=True)
        subprocess.run(["git", "-C", str(ws), "checkout", "-b", "issue-42"],
                       capture_output=True)
        subprocess.run(["git", "-C", str(proj), "checkout", "main"],
                       capture_output=True)
        subprocess.run(["git", "-C", str(ws), "checkout", "main"],
                       capture_output=True)

        result = checkout_branches_typed(str(proj), str(ws), "issue-42")
        assert isinstance(result, ResumeCheckoutResult)
        assert result.success is True
        assert result.branch == "issue-42"


def test_checkout_branches_typed_missing_branch():
    with tempfile.TemporaryDirectory() as tmp:
        proj = Path(tmp) / "project"
        ws = Path(tmp) / "workspace"
        proj.mkdir()
        ws.mkdir()
        _init_repo(proj)
        _init_repo(ws)
        result = checkout_branches_typed(str(proj), str(ws), "nonexistent")
        assert result.success is False
        assert result.error is not None


def test_reset_wip_typed_no_wip():
    with tempfile.TemporaryDirectory() as tmp:
        proj = Path(tmp) / "project"
        ws = Path(tmp) / "workspace"
        proj.mkdir()
        ws.mkdir()
        _init_repo(proj)
        _init_repo(ws)
        result = reset_wip_typed(str(proj), str(ws))
        assert isinstance(result, ResumeResetResult)
        assert result.reset is False
        assert result.reset_count == 0


def test_reset_wip_typed_with_wip():
    with tempfile.TemporaryDirectory() as tmp:
        proj = Path(tmp) / "project"
        ws = Path(tmp) / "workspace"
        proj.mkdir()
        ws.mkdir()
        _init_repo(proj)
        _init_repo(ws)
        (proj / "file.txt").write_text("work")
        subprocess.run(["git", "-C", str(proj), "add", "file.txt"],
                       capture_output=True)
        subprocess.run(["git", "-C", str(proj), "commit", "-m", "WIP: save state"],
                       capture_output=True)
        result = reset_wip_typed(str(proj), str(ws))
        assert result.reset is True
        assert result.reset_count == 1


def test_rebase_typed_already_up_to_date():
    with tempfile.TemporaryDirectory() as tmp:
        proj = Path(tmp) / "project"
        ws = Path(tmp) / "workspace"
        proj.mkdir()
        ws.mkdir()
        _init_repo(proj)
        _init_repo(ws)
        subprocess.run(["git", "-C", str(proj), "checkout", "-b", "issue-42"],
                       capture_output=True)
        result = rebase_typed(str(proj), str(ws), "main")
        assert isinstance(result, ResumeRebaseResult)
        assert result.success is True
        assert result.skipped is True


def test_cli_commit_wip_still_works():
    """Verify existing CLI function still returns exit codes."""
    from pause_exec import commit_wip
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        repo.mkdir()
        _init_repo(repo)
        exit_code = commit_wip(str(repo), "WIP: test")
        assert exit_code == 0
