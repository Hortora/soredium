"""Tests for end-path script typed results — work_end_execute, land_branch, quick_fix."""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "work-end"))
sys.path.insert(0, str(Path(__file__).parent.parent / "quick-fix"))

from work_end_execute import (
    RebaseResult, MergeResult, PushResult,
    rebase_onto_base, merge_to_main, push_to_remote,
)
from land_branch import StampResult
from quick_fix import QuickFixResult


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "commit", "--allow-empty",
                    "-m", "init"], capture_output=True, check=True)


def _init_repo_with_branch(path: Path, branch: str) -> None:
    _init_repo(path)
    subprocess.run(["git", "-C", str(path), "checkout", "-b", branch],
                   capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "commit", "--allow-empty",
                    "-m", "work on branch"], capture_output=True, check=True)


def test_rebase_success():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        repo.mkdir()
        _init_repo_with_branch(repo, "issue-42")
        result = rebase_onto_base(str(repo), "issue-42", "main")
        assert isinstance(result, RebaseResult)
        assert result.success is True
        assert result.branch == "issue-42"
        assert result.base == "main"


def test_merge_to_main_success():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        repo.mkdir()
        _init_repo_with_branch(repo, "issue-42")
        result = merge_to_main(str(repo), "issue-42", "main")
        assert isinstance(result, MergeResult)
        assert result.success is True


def test_merge_to_main_diverged():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        repo.mkdir()
        _init_repo_with_branch(repo, "issue-42")
        subprocess.run(["git", "-C", str(repo), "checkout", "main"],
                       capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "--allow-empty",
                        "-m", "diverged on main"], capture_output=True)
        result = merge_to_main(str(repo), "issue-42", "main")
        assert result.success is False
        assert result.error is not None


def test_stamp_result_dataclass():
    result = StampResult(True, landed_sha="abc123")
    assert result.success is True
    assert result.landed_sha == "abc123"
    assert result.already_stamped is False


def test_quick_fix_result_dataclass():
    result = QuickFixResult(True, branch="quick-20260811", message="fix typo",
                            mode="normal", landed_sha="def456")
    assert result.success is True
    assert result.mode == "normal"


def test_push_result_dataclass():
    result = PushResult(False, attempts=3, error="push_failed_after_3_retries")
    assert result.success is False
    assert result.attempts == 3
