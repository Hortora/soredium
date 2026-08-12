"""Tests for repo/slot discovery — commands/discover.py."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from commands.events import RepoSlotInfo, HomeReady


# ---------------------------------------------------------------------------
# _find_repos
# ---------------------------------------------------------------------------

class TestFindRepos:
    def test_discovers_git_and_claude_md(self, tmp_path):
        from commands.discover import _find_repos
        org = tmp_path / "org" / "project"
        org.mkdir(parents=True)
        subprocess.run(["git", "init", str(org)], capture_output=True)
        (org / "CLAUDE.md").write_text("# CLAUDE.md\n")
        found = _find_repos(tmp_path)
        assert len(found) == 1
        assert found[0].name == "project"

    def test_skips_dir_without_claude_md(self, tmp_path):
        from commands.discover import _find_repos
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", str(repo)], capture_output=True)
        found = _find_repos(tmp_path)
        assert len(found) == 0

    def test_skips_dir_without_git(self, tmp_path):
        from commands.discover import _find_repos
        d = tmp_path / "plain"
        d.mkdir()
        (d / "CLAUDE.md").write_text("# CLAUDE.md\n")
        found = _find_repos(tmp_path)
        assert len(found) == 0

    def test_discovers_nested_two_levels(self, tmp_path):
        from commands.discover import _find_repos
        deep = tmp_path / "org" / "sub"
        deep.mkdir(parents=True)
        subprocess.run(["git", "init", str(deep)], capture_output=True)
        (deep / "CLAUDE.md").write_text("# CLAUDE.md\n")
        found = _find_repos(tmp_path)
        assert len(found) == 1

    def test_ignores_dotdirs(self, tmp_path):
        from commands.discover import _find_repos
        hidden = tmp_path / ".hidden"
        hidden.mkdir()
        subprocess.run(["git", "init", str(hidden)], capture_output=True)
        (hidden / "CLAUDE.md").write_text("# CLAUDE.md\n")
        found = _find_repos(tmp_path)
        assert len(found) == 0


# ---------------------------------------------------------------------------
# _find_slots
# ---------------------------------------------------------------------------

class TestFindSlots:
    def test_discovers_slot_with_marker(self, tmp_path):
        from commands.discover import _find_slots
        slots = tmp_path / "slots"
        s1 = slots / "1"
        s1.mkdir(parents=True)
        (s1 / ".slot").write_text("slot marker\n")
        found = _find_slots(tmp_path)
        assert len(found) == 1
        assert found[0].name == "1"

    def test_skips_dir_without_marker(self, tmp_path):
        from commands.discover import _find_slots
        slots = tmp_path / "slots"
        s1 = slots / "1"
        s1.mkdir(parents=True)
        found = _find_slots(tmp_path)
        assert len(found) == 0

    def test_no_slots_dir(self, tmp_path):
        from commands.discover import _find_slots
        found = _find_slots(tmp_path)
        assert len(found) == 0


# ---------------------------------------------------------------------------
# _resolve_repo_info
# ---------------------------------------------------------------------------

class TestResolveRepoInfo:
    def test_resolves_branch_and_name(self, tmp_path):
        from commands.discover import _resolve_repo_info
        repo = tmp_path / "myrepo"
        repo.mkdir()
        subprocess.run(["git", "init", str(repo)], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "--allow-empty",
                        "-m", "init"], capture_output=True)
        info = _resolve_repo_info(repo)
        assert info is not None
        assert isinstance(info, RepoSlotInfo)
        assert info.branch in ("main", "master")
        assert "myrepo" in info.repo

    def test_feature_branch_state_active(self, tmp_path):
        from commands.discover import _resolve_repo_info
        repo = tmp_path / "myrepo"
        repo.mkdir()
        subprocess.run(["git", "init", str(repo)], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "--allow-empty",
                        "-m", "init"], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "checkout", "-b", "issue-42"],
                       capture_output=True)
        info = _resolve_repo_info(repo)
        assert info is not None
        assert info.branch == "issue-42"
        assert info.state == "active"


# ---------------------------------------------------------------------------
# discover_repos integration
# ---------------------------------------------------------------------------

class TestDiscoverRepos:
    def test_returns_home_ready(self, tmp_path):
        from commands.discover import discover_repos
        repo = tmp_path / "myrepo"
        repo.mkdir()
        subprocess.run(["git", "init", str(repo)], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "--allow-empty",
                        "-m", "init"], capture_output=True)
        (repo / "CLAUDE.md").write_text("# CLAUDE.md\n")
        result = discover_repos([str(tmp_path)])
        assert isinstance(result, HomeReady)
        assert len(result.repos) >= 1
        assert result.repos[0].project_path == str(repo)

    def test_empty_scan_paths(self, tmp_path):
        from commands.discover import discover_repos
        result = discover_repos([str(tmp_path / "nonexistent")])
        assert isinstance(result, HomeReady)
        assert len(result.repos) == 0

    def test_discovers_both_repos_and_slots(self, tmp_path):
        from commands.discover import discover_repos
        repo = tmp_path / "myrepo"
        repo.mkdir()
        subprocess.run(["git", "init", str(repo)], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "--allow-empty",
                        "-m", "init"], capture_output=True)
        (repo / "CLAUDE.md").write_text("# CLAUDE.md\n")

        slots = tmp_path / "slots" / "1"
        slots.mkdir(parents=True)
        (slots / ".slot").write_text("slot marker\n")
        slot_repo = slots / "project"
        slot_repo.mkdir()
        subprocess.run(["git", "init", str(slot_repo)], capture_output=True)
        subprocess.run(["git", "-C", str(slot_repo), "commit", "--allow-empty",
                        "-m", "init"], capture_output=True)

        result = discover_repos([str(tmp_path)])
        assert len(result.repos) >= 2
        slot_entries = [r for r in result.repos if r.slot is not None]
        assert len(slot_entries) >= 1
