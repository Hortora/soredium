"""Tests for work-end/upstream_push.py"""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "work-end"))
sys.path.insert(0, str(Path(__file__).parent.parent / "work-slot"))
from slot_test_helpers import init_repo_with_remote


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", "-C", str(repo)] + list(args),
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"git {' '.join(args)} failed: {r.stderr}"
    return r.stdout.strip()


class TestUpstreamPush:
    def test_skipped_when_no_upstream(self, tmp_path, capsys):
        from upstream_push import run
        repo = init_repo_with_remote(tmp_path / "repo")
        result = run(str(repo), "main")
        assert result == 0
        assert "SKIPPED=no_upstream" in capsys.readouterr().out

    def test_skipped_when_no_drift(self, tmp_path, capsys):
        from upstream_push import run
        repo = init_repo_with_remote(tmp_path / "repo")
        bare = tmp_path / ".repo-bare.git"
        _git(repo, "remote", "add", "upstream", str(bare))
        _git(repo, "fetch", "upstream")
        result = run(str(repo), "main")
        assert result == 0
        out = capsys.readouterr().out
        assert "SKIPPED" in out

    def test_pushes_when_fork_ahead(self, tmp_path, capsys):
        from upstream_push import run
        repo = init_repo_with_remote(tmp_path / "repo")
        bare = tmp_path / ".repo-bare.git"

        upstream_bare = tmp_path / "upstream-bare.git"
        upstream_bare.mkdir(parents=True)
        subprocess.run(["git", "init", "--bare", str(upstream_bare)],
                       capture_output=True, check=True)
        subprocess.run(["git", "-C", str(bare), "remote", "add", "upstream", str(upstream_bare)],
                       capture_output=True)
        _git(repo, "push", str(bare), "main")

        _git(repo, "remote", "add", "upstream", str(upstream_bare))
        _git(repo, "push", "upstream", "main")
        _git(repo, "fetch", "upstream")

        (repo / "new.txt").write_text("new\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "feat: new")
        _git(repo, "push", "origin", "main")
        _git(repo, "fetch", "origin")

        result = run(str(repo), "main")
        assert result == 0
        out = capsys.readouterr().out
        assert "FORK_AHEAD=1" in out
        assert "PUSHED=" in out or "PR_CREATED=" in out or "WARN=" in out
