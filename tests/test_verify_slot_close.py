"""Tests for work-end/verify_slot_close.py"""

import subprocess
import sys
import textwrap
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "work-end" / "verify_slot_close.py"


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", "-C", str(repo)] + list(args),
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"git {' '.join(args)} failed: {r.stderr}"
    return r.stdout.strip()


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init")
    _git(path, "config", "user.email", "test@test.com")
    _git(path, "config", "user.name", "Test")
    (path / "README.md").write_text("init\n")
    _git(path, "add", "README.md")
    _git(path, "commit", "-m", "initial commit")
    return path


def _init_bare(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--bare", str(path)], capture_output=True, check=True)
    return path


def _create_clean_single_repo(tmp_path: Path, branch: str = "issue-99-test") -> tuple[Path, Path]:
    """Create a project repo with branch merged, stamped, and pushed."""
    remote = _init_bare(tmp_path / "remote.git")
    project = _init_repo(tmp_path / "project")
    _git(project, "remote", "add", "origin", str(remote))
    _git(project, "push", "origin", "main")

    _git(project, "checkout", "-b", branch)
    (project / "feature.txt").write_text("feature\n")
    _git(project, "add", "feature.txt")
    _git(project, "commit", "-m", "feat: add feature")
    _git(project, "push", "origin", branch)

    _git(project, "checkout", "main")
    _git(project, "merge", "--ff-only", branch)
    _git(project, "push", "origin", "main")

    sha = _git(project, "rev-parse", "main")
    _git(project, "checkout", branch)
    _git(project, "commit", "--allow-empty", "-m",
         f"chore: branch closed — landed as {sha} on main")
    _git(project, "push", "origin", branch, "--force-with-lease")
    _git(project, "checkout", "main")

    workspace = _init_repo(tmp_path / "workspace")
    _git(workspace, "checkout", "-b", branch)
    _git(workspace, "commit", "--allow-empty", "-m",
         f"chore: branch closed — landed as {sha} on main")
    _git(workspace, "checkout", "main")

    return project, workspace


def _run_verify(
    project: Path, workspace: Path, branch: str = "issue-99-test",
    **extra_args: str,
) -> subprocess.CompletedProcess:
    args = [
        sys.executable, str(SCRIPT),
        str(project), f"branch={branch}", f"workspace={workspace}",
    ]
    for k, v in extra_args.items():
        args.append(f"{k}={v}")
    return subprocess.run(args, capture_output=True, text=True)


class TestVerifyAllPass:
    def test_single_repo_clean_state(self, tmp_path: Path) -> None:
        project, workspace = _create_clean_single_repo(tmp_path)
        result = _run_verify(project, workspace)
        assert result.returncode == 0
        assert "VERIFIED=yes" in result.stdout


class TestVerifyMissingStamp:
    def test_unstamped_branch(self, tmp_path: Path) -> None:
        branch = "issue-100-test"
        remote = _init_bare(tmp_path / "remote.git")
        project = _init_repo(tmp_path / "project")
        _git(project, "remote", "add", "origin", str(remote))
        _git(project, "push", "origin", "main")

        _git(project, "checkout", "-b", branch)
        (project / "f.txt").write_text("work\n")
        _git(project, "add", "f.txt")
        _git(project, "commit", "-m", "feat: work")
        _git(project, "push", "origin", branch)

        _git(project, "checkout", "main")
        _git(project, "merge", "--ff-only", branch)
        _git(project, "push", "origin", "main")

        workspace = _init_repo(tmp_path / "workspace")

        result = _run_verify(project, workspace, branch=branch)
        assert "VERIFIED=no" in result.stdout
        assert "UNSTAMPED" in result.stdout


class TestVerifyUnpushedMain:
    def test_local_ahead_of_origin(self, tmp_path: Path) -> None:
        branch = "issue-101-test"
        remote = _init_bare(tmp_path / "remote.git")
        project = _init_repo(tmp_path / "project")
        _git(project, "remote", "add", "origin", str(remote))
        _git(project, "push", "origin", "main")

        _git(project, "checkout", "-b", branch)
        (project / "f.txt").write_text("work\n")
        _git(project, "add", "f.txt")
        _git(project, "commit", "-m", "feat: work")
        _git(project, "push", "origin", branch)

        _git(project, "checkout", "main")
        _git(project, "merge", "--ff-only", branch)
        # Deliberately do NOT push main

        sha = _git(project, "rev-parse", "main")
        _git(project, "checkout", branch)
        _git(project, "commit", "--allow-empty", "-m",
             f"chore: branch closed — landed as {sha} on main")
        _git(project, "checkout", "main")

        workspace = _init_repo(tmp_path / "workspace")

        result = _run_verify(project, workspace, branch=branch)
        assert "VERIFIED=no" in result.stdout
        assert "UNPUSHED" in result.stdout


class TestVerifyBadArgs:
    def test_missing_args(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            capture_output=True, text=True,
        )
        assert result.returncode == 1


work_end_dir = Path(__file__).parent.parent / "work-end"
sys.path.insert(0, str(work_end_dir))
import verify_slot_close


class TestCheckLandedMarker:
    def test_landed_marker_present(self, tmp_path: Path) -> None:
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        (slot_dir / ".landed").write_text(
            "branch=issue-42\nrepos=engine,work\n"
            "landed_shas=engine:abc123,work:def456\n"
            "timestamp=2026-08-12T00:00:00Z\n"
        )
        result = verify_slot_close.check_landed_marker(str(slot_dir))
        assert result["status"] == "pass"

    def test_landed_marker_absent(self, tmp_path: Path) -> None:
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        result = verify_slot_close.check_landed_marker(str(slot_dir))
        assert result["status"] == "fail"
        assert "no .landed marker" in result["detail"]

    def test_landed_marker_no_shas(self, tmp_path: Path) -> None:
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        (slot_dir / ".landed").write_text("branch=issue-42\n")
        result = verify_slot_close.check_landed_marker(str(slot_dir))
        assert result["status"] == "fail"
        assert "no landed_shas" in result["detail"]


class TestCheckOriginalSync:
    def test_original_in_sync(self, tmp_path: Path) -> None:
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        original = _init_repo(tmp_path / "original")
        clone = _init_repo(slot_dir / "engine")
        orig_sha = _git(original, "rev-parse", "HEAD")
        (slot_dir / ".landed").write_text(f"landed_shas=engine:{orig_sha}\n")
        result = verify_slot_close.check_original_sync(
            str(slot_dir), "engine", str(original),
        )
        assert result["status"] == "pass"

    def test_original_behind(self, tmp_path: Path) -> None:
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        original = _init_repo(tmp_path / "original")
        clone = _init_repo(slot_dir / "engine")
        (clone / "extra.txt").write_text("new\n")
        _git(clone, "add", "extra.txt")
        _git(clone, "commit", "-m", "extra")
        clone_sha = _git(clone, "rev-parse", "HEAD")
        (slot_dir / ".landed").write_text(f"landed_shas=engine:{clone_sha}\n")
        result = verify_slot_close.check_original_sync(
            str(slot_dir), "engine", str(original),
        )
        assert result["status"] == "fail"
        assert "not reachable" in result["detail"]

    def test_no_landed_marker(self, tmp_path: Path) -> None:
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        result = verify_slot_close.check_original_sync(
            str(slot_dir), "engine", str(tmp_path / "original"),
        )
        assert result["status"] == "fail"
        assert "no .landed" in result["detail"]


class TestCheckSlotArchiveStatus:
    def test_archived(self, tmp_path: Path) -> None:
        attic_dir = tmp_path / "slots" / "attic" / "1"
        attic_dir.mkdir(parents=True)
        result = verify_slot_close.check_slot_archive_status(
            str(tmp_path / "slots" / "1"), str(attic_dir),
        )
        assert result["status"] == "pass"
        assert "archived" in result["detail"]

    def test_landed_not_archived(self, tmp_path: Path) -> None:
        slot_dir = tmp_path / "slots" / "1"
        slot_dir.mkdir(parents=True)
        (slot_dir / ".landed").write_text("landed\n")
        result = verify_slot_close.check_slot_archive_status(
            str(slot_dir), str(tmp_path / "slots" / "attic" / "1"),
        )
        assert result["status"] == "warn"
        assert "landed but not archived" in result["detail"]

    def test_active(self, tmp_path: Path) -> None:
        slot_dir = tmp_path / "slots" / "1"
        slot_dir.mkdir(parents=True)
        result = verify_slot_close.check_slot_archive_status(
            str(slot_dir), str(tmp_path / "slots" / "attic" / "1"),
        )
        assert result["status"] == "warn"
        assert "active" in result["detail"]


class TestCheckIssuesClosed:
    def test_all_closed(self, tmp_path: Path, monkeypatch) -> None:
        def fake_run(cmd, **kwargs):
            if "gh" in cmd and "issue" in cmd and "view" in cmd:
                return subprocess.CompletedProcess(cmd, 0, "CLOSED\n", "")
            return subprocess.run(cmd, **kwargs)

        monkeypatch.setattr(verify_slot_close.subprocess, "run", fake_run)
        result = verify_slot_close.check_issues_closed("owner/repo", [42, 43])
        assert result["status"] == "pass"
        assert "2/2" in result["detail"]

    def test_one_open(self, tmp_path: Path, monkeypatch) -> None:
        call_count = {"n": 0}

        def fake_run(cmd, **kwargs):
            if "gh" in cmd and "issue" in cmd and "view" in cmd:
                call_count["n"] += 1
                state = "CLOSED" if call_count["n"] == 1 else "OPEN"
                return subprocess.CompletedProcess(cmd, 0, f"{state}\n", "")
            return subprocess.run(cmd, **kwargs)

        monkeypatch.setattr(verify_slot_close.subprocess, "run", fake_run)
        result = verify_slot_close.check_issues_closed("owner/repo", [42, 43])
        assert result["status"] == "fail"
        assert "#43" in result["detail"]

    def test_gh_failure_is_fail(self, tmp_path: Path, monkeypatch) -> None:
        def fake_run(cmd, **kwargs):
            if "gh" in cmd and "issue" in cmd and "view" in cmd:
                return subprocess.CompletedProcess(cmd, 1, "", "network error")
            return subprocess.run(cmd, **kwargs)

        monkeypatch.setattr(verify_slot_close.subprocess, "run", fake_run)
        result = verify_slot_close.check_issues_closed("owner/repo", [42])
        assert result["status"] == "fail"

    def test_empty_covers_is_pass(self) -> None:
        result = verify_slot_close.check_issues_closed("owner/repo", [])
        assert result["status"] == "pass"

    def test_none_covers_is_pass(self) -> None:
        result = verify_slot_close.check_issues_closed("owner/repo", None)
        assert result["status"] == "pass"


class TestVerifySlotModeCLI:
    def test_slot_dir_enables_slot_checks(self, tmp_path: Path) -> None:
        project, workspace = _create_clean_single_repo(tmp_path)
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        (slot_dir / ".landed").write_text(
            "branch=issue-99-test\nrepos=project\n"
            "landed_shas=project:abc123\ntimestamp=2026-08-12\n"
        )
        result = _run_verify(project, workspace, slot_dir=str(slot_dir))
        assert result.returncode == 0
        assert "landed_marker" in result.stdout
