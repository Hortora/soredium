"""Tests for work-end/land_branch.py"""

import subprocess
import sys
from pathlib import Path

import pytest

script_dir = Path(__file__).parent.parent / "work-end"
sys.path.insert(0, str(script_dir))

from land_branch import detect_topology, cmd_rebase, cmd_push, cmd_stamp


def _init_git(path, branch="main"):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", str(path)], capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t.com"], capture_output=True)
    subprocess.run(["git", "-C", str(path), "checkout", "-b", branch], capture_output=True)
    subprocess.run(["git", "-C", str(path), "commit", "--allow-empty", "-m", "init"], capture_output=True)


def _make_bare_remote(path):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--bare", str(path)], capture_output=True)


class TestDetectTopology:
    def test_single_remote(self, tmp_path):
        _init_git(tmp_path)
        remote = tmp_path / "remote.git"
        _make_bare_remote(remote)
        subprocess.run(["git", "-C", str(tmp_path), "remote", "add", "origin", str(remote)], capture_output=True)

        fork, blessed = detect_topology(str(tmp_path))
        assert fork == "origin"
        assert blessed == ""

    def test_fork_model(self, tmp_path):
        _init_git(tmp_path)
        fork_remote = tmp_path / "fork.git"
        blessed_remote = tmp_path / "blessed.git"
        _make_bare_remote(fork_remote)
        _make_bare_remote(blessed_remote)
        subprocess.run(["git", "-C", str(tmp_path), "remote", "add", "origin", str(fork_remote)], capture_output=True)
        subprocess.run(["git", "-C", str(tmp_path), "remote", "add", "upstream", str(blessed_remote)], capture_output=True)

        fork, blessed = detect_topology(str(tmp_path))
        assert fork == "origin"
        assert blessed == "upstream"

    def test_no_remotes(self, tmp_path):
        _init_git(tmp_path)
        fork, blessed = detect_topology(str(tmp_path))
        assert fork == ""
        assert blessed == ""


class TestCmdRebase:
    def test_successful_rebase(self, tmp_path):
        project = tmp_path / "project"
        _init_git(project)

        remote = tmp_path / "remote.git"
        _make_bare_remote(remote)
        subprocess.run(["git", "-C", str(project), "remote", "add", "origin", str(remote)], capture_output=True)
        subprocess.run(["git", "-C", str(project), "push", "origin", "main"], capture_output=True)

        subprocess.run(["git", "-C", str(project), "checkout", "-b", "feature"], capture_output=True)
        (project / "feature.txt").write_text("feature work")
        subprocess.run(["git", "-C", str(project), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(project), "commit", "-m", "feat: add feature"], capture_output=True)

        result = cmd_rebase(str(project), {"branch": "feature", "base_branch": "main"})
        assert result == 0

    def test_missing_branch_arg(self, tmp_path, capsys):
        _init_git(tmp_path)
        result = cmd_rebase(str(tmp_path), {"base_branch": "main"})
        assert result == 1
        captured = capsys.readouterr()
        assert "ERROR=MISSING_ARGS" in captured.out


class TestCmdPush:
    def test_successful_push(self, tmp_path):
        project = tmp_path / "project"
        _init_git(project)

        remote = tmp_path / "remote.git"
        _make_bare_remote(remote)
        subprocess.run(["git", "-C", str(project), "remote", "add", "origin", str(remote)], capture_output=True)
        subprocess.run(["git", "-C", str(project), "push", "origin", "main"], capture_output=True)

        (project / "new.txt").write_text("new")
        subprocess.run(["git", "-C", str(project), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(project), "commit", "-m", "add new"], capture_output=True)

        result = cmd_push(str(project), {"base_branch": "main"})
        assert result == 0

    def test_missing_stamp_blocks_push(self, tmp_path, capsys):
        project = tmp_path / "project"
        workspace = tmp_path / "workspace"
        _init_git(project)
        workspace.mkdir()
        (workspace / "design").mkdir()

        result = cmd_push(str(project), {
            "base_branch": "main",
            "workspace": str(workspace),
            "branch": "issue-42",
        })
        assert result == 1
        captured = capsys.readouterr()
        assert "ERROR=MISSING_STAMP" in captured.out

    def test_stamp_present_allows_push(self, tmp_path):
        project = tmp_path / "project"
        workspace = tmp_path / "workspace"
        _init_git(project)
        workspace.mkdir()
        (workspace / "design").mkdir()
        (workspace / "design" / ".artifacts-promoted").write_text("branch=issue-42\ntimestamp=2026-07-25\n")

        remote = tmp_path / "remote.git"
        _make_bare_remote(remote)
        subprocess.run(["git", "-C", str(project), "remote", "add", "origin", str(remote)], capture_output=True)
        subprocess.run(["git", "-C", str(project), "push", "origin", "main"], capture_output=True)

        (project / "work.txt").write_text("work")
        subprocess.run(["git", "-C", str(project), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(project), "commit", "-m", "work"], capture_output=True)

        result = cmd_push(str(project), {
            "base_branch": "main",
            "workspace": str(workspace),
            "branch": "issue-42",
        })
        assert result == 0


class TestCmdStamp:
    def test_successful_stamp(self, tmp_path):
        project = tmp_path / "project"
        _init_git(project)

        subprocess.run(["git", "-C", str(project), "checkout", "-b", "feature"], capture_output=True)
        (project / "code.txt").write_text("code")
        subprocess.run(["git", "-C", str(project), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(project), "commit", "-m", "feat: code"], capture_output=True)

        subprocess.run(["git", "-C", str(project), "checkout", "main"], capture_output=True)
        subprocess.run(["git", "-C", str(project), "rebase", "feature"], capture_output=True)

        result = cmd_stamp(str(project), {"branch": "feature", "base_branch": "main"})
        assert result == 0

        # Verify stamp was written
        log = subprocess.run(
            ["git", "-C", str(project), "log", "-1", "--format=%s", "feature"],
            capture_output=True, text=True,
        )
        assert log.stdout.strip().startswith("chore: branch closed")

    def test_missing_branch_arg(self, tmp_path, capsys):
        _init_git(tmp_path)
        result = cmd_stamp(str(tmp_path), {"base_branch": "main"})
        assert result == 1
        captured = capsys.readouterr()
        assert "ERROR=MISSING_ARGS" in captured.out


class TestIntegration:
    SCRIPT = Path(__file__).parent.parent / "work-end" / "land_branch.py"

    def test_rebase_subcommand(self, tmp_path):
        project = tmp_path / "project"
        _init_git(project)

        remote = tmp_path / "remote.git"
        _make_bare_remote(remote)
        subprocess.run(["git", "-C", str(project), "remote", "add", "origin", str(remote)], capture_output=True)
        subprocess.run(["git", "-C", str(project), "push", "origin", "main"], capture_output=True)

        subprocess.run(["git", "-C", str(project), "checkout", "-b", "issue-42"], capture_output=True)
        (project / "file.txt").write_text("work")
        subprocess.run(["git", "-C", str(project), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(project), "commit", "-m", "feat: work"], capture_output=True)

        result = subprocess.run(
            [sys.executable, str(self.SCRIPT), "rebase", str(project),
             "branch=issue-42", "base_branch=main"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "REBASE=ok" in result.stdout
        assert "FORK_REMOTE=origin" in result.stdout

    def test_unknown_subcommand(self, tmp_path):
        _init_git(tmp_path)
        result = subprocess.run(
            [sys.executable, str(self.SCRIPT), "unknown", str(tmp_path)],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "ERROR=UNKNOWN_COMMAND" in result.stdout

    def test_missing_args(self):
        result = subprocess.run(
            [sys.executable, str(self.SCRIPT)],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
