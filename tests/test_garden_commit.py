"""Tests for forage/garden_commit.py"""

import subprocess
import sys
from pathlib import Path

import pytest

skill_dir = Path(__file__).parent.parent / "forage"
sys.path.insert(0, str(skill_dir))

import garden_commit


def _init_garden(path: Path, with_remote: bool = False) -> Path:
    """Create a minimal git repo simulating a garden."""
    if with_remote:
        bare = path.parent / f".{path.name}-bare.git"
        bare.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "--bare", str(bare)], capture_output=True, check=True)
        subprocess.run(["git", "clone", str(bare), str(path)], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], capture_output=True)
        subprocess.run(["git", "-C", str(path), "config", "user.email", "test@test.com"], capture_output=True)
        subprocess.run(["git", "-C", str(path), "checkout", "-b", "main"], capture_output=True)
        (path / "GARDEN.md").write_text("# Garden\n")
        subprocess.run(["git", "-C", str(path), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(path), "commit", "-m", "init"], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(path), "push", "-u", "origin", "main"], capture_output=True)
    else:
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init"], cwd=str(path), capture_output=True, check=True)
        subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], capture_output=True)
        subprocess.run(["git", "-C", str(path), "config", "user.email", "test@test.com"], capture_output=True)
        (path / "GARDEN.md").write_text("# Garden\n")
        subprocess.run(["git", "-C", str(path), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(path), "commit", "-m", "init"], capture_output=True, check=True)
    return path


class TestCommit:
    def test_commits_single_file(self, tmp_path):
        garden = _init_garden(tmp_path / "garden")
        domain = garden / "tools"
        domain.mkdir()
        entry = domain / "GE-20260806-abc123.md"
        entry.write_text("---\ntitle: test\n---\nContent\n")

        result = garden_commit.commit(
            str(garden),
            files=["tools/GE-20260806-abc123.md"],
            message="index: integrate GE-20260806-abc123",
        )

        assert result["committed"]
        rc = subprocess.run(
            ["git", "-C", str(garden), "log", "-1", "--format=%s"],
            capture_output=True, text=True,
        )
        assert "GE-20260806-abc123" in rc.stdout

    def test_commits_multiple_files_with_index_dirs(self, tmp_path):
        garden = _init_garden(tmp_path / "garden")
        domain = garden / "tools"
        domain.mkdir()
        (domain / "GE-001.md").write_text("entry 1")
        (domain / "GE-002.md").write_text("entry 2")
        (garden / "_summaries").mkdir()
        (garden / "_summaries" / "tools.md").write_text("summary")
        (garden / "_index").mkdir()
        (garden / "_index" / "global.md").write_text("index")

        result = garden_commit.commit(
            str(garden),
            files=["tools/GE-001.md", "tools/GE-002.md"],
            message="sweep: 2 entries — test1, test2",
        )

        assert result["committed"]
        rc = subprocess.run(
            ["git", "-C", str(garden), "diff", "--name-only", "HEAD~1..HEAD"],
            capture_output=True, text=True,
        )
        changed = rc.stdout.strip().split("\n")
        assert "tools/GE-001.md" in changed
        assert "tools/GE-002.md" in changed

    def test_stages_index_directories(self, tmp_path):
        garden = _init_garden(tmp_path / "garden")
        (garden / "_summaries").mkdir()
        (garden / "_summaries" / "data.md").write_text("summary update")
        (garden / "labels").mkdir()
        (garden / "labels" / "gotcha.md").write_text("label data")

        result = garden_commit.commit(
            str(garden),
            files=[],
            message="index: update summaries",
        )

        assert result["committed"]
        rc = subprocess.run(
            ["git", "-C", str(garden), "diff", "--name-only", "HEAD~1..HEAD"],
            capture_output=True, text=True,
        )
        changed = rc.stdout.strip()
        assert "_summaries/data.md" in changed
        assert "labels/gotcha.md" in changed

    def test_no_changes_returns_not_committed(self, tmp_path):
        garden = _init_garden(tmp_path / "garden")

        result = garden_commit.commit(
            str(garden),
            files=[],
            message="nothing to commit",
        )

        assert not result["committed"]

    def test_nonexistent_garden_returns_error(self, tmp_path):
        result = garden_commit.commit(
            str(tmp_path / "nonexistent"),
            files=[],
            message="test",
        )

        assert not result["committed"]
        assert "error" in result

    def test_stages_garden_db_if_new(self, tmp_path):
        """garden.db may be untracked on first integration — commit must stage it."""
        garden = _init_garden(tmp_path / "garden")
        (garden / "garden.db").write_text("sqlite data")

        result = garden_commit.commit(
            str(garden),
            files=[],
            message="index: first integration",
        )

        assert result["committed"]
        rc = subprocess.run(
            ["git", "-C", str(garden), "diff", "--name-only", "HEAD~1..HEAD"],
            capture_output=True, text=True,
        )
        assert "garden.db" in rc.stdout


class TestPush:
    def test_pushes_to_github_remote(self, tmp_path):
        garden = _init_garden(tmp_path / "garden", with_remote=True)
        (garden / "new.md").write_text("new content")
        subprocess.run(["git", "-C", str(garden), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(garden), "commit", "-m", "add new"], capture_output=True)

        result = garden_commit.push(str(garden))

        assert result["pushed"]
        rc = subprocess.run(
            ["git", "-C", str(garden), "log", "origin/main..HEAD", "--oneline"],
            capture_output=True, text=True,
        )
        assert rc.stdout.strip() == ""

    def test_skips_push_for_local_only_garden(self, tmp_path):
        garden = _init_garden(tmp_path / "garden", with_remote=False)

        result = garden_commit.push(str(garden))

        assert not result["pushed"]
        assert result.get("reason") == "no_remote"

    def test_handles_rebase_conflict(self, tmp_path):
        garden = _init_garden(tmp_path / "garden", with_remote=True)
        bare = tmp_path / f".garden-bare.git"

        garden2 = tmp_path / "garden2"
        subprocess.run(["git", "clone", str(bare), str(garden2)], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(garden2), "config", "user.name", "Other"], capture_output=True)
        subprocess.run(["git", "-C", str(garden2), "config", "user.email", "other@test.com"], capture_output=True)
        subprocess.run(["git", "-C", str(garden2), "checkout", "main"], capture_output=True)
        (garden2 / "conflict.md").write_text("other content")
        subprocess.run(["git", "-C", str(garden2), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(garden2), "commit", "-m", "other change"], capture_output=True)
        subprocess.run(["git", "-C", str(garden2), "push", "origin", "main"], capture_output=True)

        (garden / "conflict.md").write_text("our content")
        subprocess.run(["git", "-C", str(garden), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(garden), "commit", "-m", "our change"], capture_output=True)

        result = garden_commit.push(str(garden))

        assert not result["pushed"]
        assert "conflict" in result.get("error", "").lower() or "rebase" in result.get("error", "").lower()

    def test_nonexistent_garden_returns_error(self, tmp_path):
        result = garden_commit.push(str(tmp_path / "nonexistent"))

        assert not result["pushed"]
        assert "error" in result


class TestCommitAndPush:
    def test_commits_and_pushes(self, tmp_path):
        garden = _init_garden(tmp_path / "garden", with_remote=True)
        domain = garden / "tools"
        domain.mkdir()
        entry = domain / "GE-20260806-def456.md"
        entry.write_text("---\ntitle: test\n---\n")

        result = garden_commit.commit_and_push(
            str(garden),
            files=["tools/GE-20260806-def456.md"],
            message="index: integrate GE-20260806-def456",
        )

        assert result["committed"]
        assert result["pushed"]

    def test_commit_fails_skips_push(self, tmp_path):
        garden = _init_garden(tmp_path / "garden", with_remote=True)

        result = garden_commit.commit_and_push(
            str(garden),
            files=[],
            message="nothing to commit",
        )

        assert not result["committed"]
        assert not result.get("pushed", False)

    def test_commit_succeeds_push_skipped_for_local(self, tmp_path):
        garden = _init_garden(tmp_path / "garden", with_remote=False)
        (garden / "new.md").write_text("content")

        result = garden_commit.commit_and_push(
            str(garden),
            files=["new.md"],
            message="add new",
        )

        assert result["committed"]
        assert not result["pushed"]


class TestCLI:
    def test_commit_cli(self, tmp_path, capsys):
        garden = _init_garden(tmp_path / "garden")
        (garden / "entry.md").write_text("content")
        sys.argv = [
            "garden_commit.py", "commit", str(garden),
            "files=entry.md", "message=test commit",
        ]
        garden_commit.main()
        out = capsys.readouterr().out
        assert "COMMITTED=yes" in out

    def test_push_cli_no_remote(self, tmp_path, capsys):
        garden = _init_garden(tmp_path / "garden")
        sys.argv = ["garden_commit.py", "push", str(garden)]
        garden_commit.main()
        out = capsys.readouterr().out
        assert "PUSHED=no" in out
        assert "REASON=no_remote" in out

    def test_missing_garden_path(self, capsys):
        sys.argv = ["garden_commit.py", "commit"]
        with pytest.raises(SystemExit):
            garden_commit.main()
