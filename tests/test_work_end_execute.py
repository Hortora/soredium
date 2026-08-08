"""Tests for work-end/work_end_execute.py"""

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "work-end" / "work_end_execute.py"


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


def _run_execute(
    subcommand: str, *extra_args: str,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), subcommand, *extra_args],
        capture_output=True, text=True, timeout=30,
    )


class TestPromoteSingleRepo:
    def test_promote_writes_progress(self, tmp_path: Path) -> None:
        workspace = _init_repo(tmp_path / "workspace")
        project = _init_repo(tmp_path / "project")
        branch = "issue-99-test"

        _git(workspace, "checkout", "-b", branch)
        design = workspace / "design"
        design.mkdir(exist_ok=True)
        (design / ".meta").write_text(f"branch: {branch}\nstate: active\n")
        _git(workspace, "add", ".")
        _git(workspace, "commit", "-m", "scaffold")

        _git(project, "checkout", "-b", branch)

        result = _run_execute(
            "promote",
            f"workspace={workspace}",
            f"project={project}",
            f"branch={branch}",
        )
        assert result.returncode == 0
        assert "PROMOTED=yes" in result.stdout

        progress_path = design / ".execute-progress"
        assert progress_path.exists()
        content = progress_path.read_text()
        assert "promoted" in content

    def test_promote_skips_already_promoted(self, tmp_path: Path) -> None:
        workspace = _init_repo(tmp_path / "workspace")
        project = _init_repo(tmp_path / "project")
        branch = "issue-100-test"

        _git(workspace, "checkout", "-b", branch)
        design = workspace / "design"
        design.mkdir(exist_ok=True)
        (design / ".meta").write_text(f"branch: {branch}\nstate: active\n")
        (design / ".execute-progress").write_text("default=promoted\n")
        _git(workspace, "add", ".")
        _git(workspace, "commit", "-m", "scaffold")

        _git(project, "checkout", "-b", branch)

        result = _run_execute(
            "promote",
            f"workspace={workspace}",
            f"project={project}",
            f"branch={branch}",
        )
        assert result.returncode == 0
        assert "SKIPPED" in result.stdout or "already" in result.stdout.lower()


class TestRebaseSingleRepo:
    def test_rebase_onto_base(self, tmp_path: Path) -> None:
        remote = _init_bare(tmp_path / "remote.git")
        project = _init_repo(tmp_path / "project")
        _git(project, "remote", "add", "origin", str(remote))
        _git(project, "push", "origin", "main")

        _git(project, "checkout", "-b", "issue-101-test")
        (project / "feature.txt").write_text("feature\n")
        _git(project, "add", "feature.txt")
        _git(project, "commit", "-m", "feat: feature")

        result = _run_execute(
            "rebase",
            f"project={project}",
            "branch=issue-101-test",
            "base_branch=main",
        )
        assert result.returncode == 0
        assert "REBASED=yes" in result.stdout

    def test_rebase_conflict_reports_error(self, tmp_path: Path) -> None:
        remote = _init_bare(tmp_path / "remote.git")
        project = _init_repo(tmp_path / "project")
        _git(project, "remote", "add", "origin", str(remote))
        _git(project, "push", "origin", "main")

        _git(project, "checkout", "-b", "issue-102-test")
        (project / "README.md").write_text("branch version\n")
        _git(project, "add", "README.md")
        _git(project, "commit", "-m", "feat: branch change")

        _git(project, "checkout", "main")
        (project / "README.md").write_text("main version\n")
        _git(project, "add", "README.md")
        _git(project, "commit", "-m", "fix: main change")

        _git(project, "checkout", "issue-102-test")

        result = _run_execute(
            "rebase",
            f"project={project}",
            "branch=issue-102-test",
            "base_branch=main",
        )
        assert "ERROR=REBASE_CONFLICT" in result.stdout


class TestLandSingleRepo:
    def test_land_pushes_and_stamps(self, tmp_path: Path) -> None:
        remote = _init_bare(tmp_path / "remote.git")
        project = _init_repo(tmp_path / "project")
        workspace = _init_repo(tmp_path / "workspace")
        branch = "issue-103-test"

        _git(project, "remote", "add", "origin", str(remote))
        _git(project, "push", "origin", "main")

        _git(project, "checkout", "-b", branch)
        (project / "feature.txt").write_text("feature\n")
        _git(project, "add", "feature.txt")
        _git(project, "commit", "-m", "feat: add feature")
        _git(project, "push", "origin", branch)

        _git(project, "checkout", "main")
        _git(project, "merge", "--ff-only", branch)

        _git(workspace, "checkout", "-b", branch)
        design = workspace / "design"
        design.mkdir(exist_ok=True)
        (design / ".meta").write_text(f"branch: {branch}\nstate: active\n")
        _git(workspace, "add", ".")
        _git(workspace, "commit", "-m", "scaffold")

        result = _run_execute(
            "land",
            f"project={project}",
            f"branch={branch}",
            "base_branch=main",
            f"workspace={workspace}",
        )
        assert result.returncode == 0
        assert "LANDED=yes" in result.stdout

        last_msg = _git(project, "log", "-1", "--format=%s", branch)
        assert last_msg.startswith("chore: branch closed")

    def test_land_pushes_main(self, tmp_path: Path) -> None:
        remote = _init_bare(tmp_path / "remote.git")
        project = _init_repo(tmp_path / "project")
        workspace = _init_repo(tmp_path / "workspace")
        branch = "issue-104-test"

        _git(project, "remote", "add", "origin", str(remote))
        _git(project, "push", "origin", "main")

        _git(project, "checkout", "-b", branch)
        (project / "feature.txt").write_text("feature\n")
        _git(project, "add", "feature.txt")
        _git(project, "commit", "-m", "feat: add feature")
        _git(project, "push", "origin", branch)

        _git(project, "checkout", "main")
        _git(project, "merge", "--ff-only", branch)

        _git(workspace, "checkout", "-b", branch)

        result = _run_execute(
            "land",
            f"project={project}",
            f"branch={branch}",
            "base_branch=main",
            f"workspace={workspace}",
        )
        assert result.returncode == 0

        unpushed = _git(project, "log", "origin/main..main", "--oneline")
        assert not unpushed

    def test_land_stamps_workspace(self, tmp_path: Path) -> None:
        remote = _init_bare(tmp_path / "remote.git")
        project = _init_repo(tmp_path / "project")
        workspace = _init_repo(tmp_path / "workspace")
        branch = "issue-105-test"

        _git(project, "remote", "add", "origin", str(remote))
        _git(project, "push", "origin", "main")
        _git(project, "checkout", "-b", branch)
        _git(project, "commit", "--allow-empty", "-m", "feat: work")
        _git(project, "push", "origin", branch)
        _git(project, "checkout", "main")
        _git(project, "merge", "--ff-only", branch)

        _git(workspace, "checkout", "-b", branch)
        design = workspace / "design"
        design.mkdir(exist_ok=True)
        (design / ".meta").write_text(f"branch: {branch}\nstate: active\n")
        _git(workspace, "add", ".")
        _git(workspace, "commit", "-m", "scaffold")

        result = _run_execute(
            "land",
            f"project={project}",
            f"branch={branch}",
            "base_branch=main",
            f"workspace={workspace}",
        )
        assert result.returncode == 0

        ws_tip = _git(workspace, "log", "-1", "--format=%s", branch)
        assert ws_tip.startswith("chore: branch closed")


class TestLandMergesBeforePush:
    def test_land_merges_branch_into_main_before_push(self, tmp_path: Path) -> None:
        """cmd_land must ff-merge the branch into main before pushing.

        Previously, callers had to merge externally. This caused #196/#197:
        main pushed without the branch commits, leaving work unlanded.
        """
        remote = _init_bare(tmp_path / "remote.git")
        project = _init_repo(tmp_path / "project")
        workspace = _init_repo(tmp_path / "workspace")
        branch = "issue-197-test"

        _git(project, "remote", "add", "origin", str(remote))
        _git(project, "push", "origin", "main")

        _git(project, "checkout", "-b", branch)
        (project / "feature.txt").write_text("new feature\n")
        _git(project, "add", "feature.txt")
        _git(project, "commit", "-m", "feat: add feature")

        # Do NOT merge into main — cmd_land should do this itself
        _git(project, "checkout", "main")

        _git(workspace, "checkout", "-b", branch)
        design = workspace / "design"
        design.mkdir(exist_ok=True)
        (design / ".meta").write_text(f"branch: {branch}\nstate: active\n")
        _git(workspace, "add", ".")
        _git(workspace, "commit", "-m", "scaffold")

        result = _run_execute(
            "land",
            f"project={project}",
            f"branch={branch}",
            "base_branch=main",
            f"workspace={workspace}",
        )
        assert result.returncode == 0, f"land failed: {result.stdout}\n{result.stderr}"
        assert "LANDED=yes" in result.stdout

        # Main must include the branch commit
        main_log = _git(project, "log", "--oneline", "main")
        assert "feat: add feature" in main_log

        # Remote must also have it
        remote_log = subprocess.run(
            ["git", "--git-dir", str(remote), "log", "--oneline", "main"],
            capture_output=True, text=True,
        ).stdout
        assert "feat: add feature" in remote_log


class TestBadArgs:
    def test_missing_subcommand(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            capture_output=True, text=True,
        )
        assert result.returncode == 1

    def test_unknown_subcommand(self) -> None:
        result = _run_execute("unknown")
        assert result.returncode == 1
        assert "ERROR" in result.stdout
