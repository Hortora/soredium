"""Tests for work-end/hygiene_scan.py"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

script_dir = Path(__file__).parent.parent / "work-end"
sys.path.insert(0, str(script_dir))

from hygiene_scan import (
    check_unpublished_blogs,
    check_stale_branches,
    check_unrecovered_artifacts,
    check_unstamped_branches,
    list_workspace_branches,
)


def _init_git(path):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", str(path)], capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t.com"], capture_output=True)
    subprocess.run(["git", "-C", str(path), "checkout", "-b", "main"], capture_output=True)
    subprocess.run(["git", "-C", str(path), "commit", "--allow-empty", "-m", "init"], capture_output=True)


class TestCheckUnpublishedBlogs:
    def test_all_published(self, tmp_path):
        blog = tmp_path / "workspace" / "blog"
        blog.mkdir(parents=True)
        (blog / "entry.md").write_text("content")

        dest = tmp_path / "dest"
        dest.mkdir()
        (dest / "entry.md").write_text("content")

        result = check_unpublished_blogs(str(tmp_path / "workspace"), str(dest))
        assert result == []

    def test_detects_unpublished(self, tmp_path):
        blog = tmp_path / "workspace" / "blog"
        blog.mkdir(parents=True)
        (blog / "published.md").write_text("yes")
        (blog / "unpublished.md").write_text("no")
        (blog / "INDEX.md").write_text("index")

        dest = tmp_path / "dest"
        dest.mkdir()
        (dest / "published.md").write_text("yes")

        result = check_unpublished_blogs(str(tmp_path / "workspace"), str(dest))
        assert result == ["unpublished.md"]

    def test_tilde_in_blog_dest_expanded(self, tmp_path, monkeypatch):
        """blog_dest with ~ must be expanded — Path('~/...') treats ~ as literal."""
        blog = tmp_path / "workspace" / "blog"
        blog.mkdir(parents=True)
        (blog / "entry.md").write_text("content")

        fake_home = tmp_path / "fakehome"
        dest = fake_home / "dest"
        dest.mkdir(parents=True)
        (dest / "entry.md").write_text("content")

        monkeypatch.setenv("HOME", str(fake_home))
        result = check_unpublished_blogs(str(tmp_path / "workspace"), "~/dest")
        assert result == [], f"tilde not expanded — entry reported as unpublished"

    def test_no_blog_dir(self, tmp_path):
        result = check_unpublished_blogs(str(tmp_path), "/some/dest")
        assert result == []

    def test_no_blog_dest(self, tmp_path):
        blog = tmp_path / "blog"
        blog.mkdir()
        (blog / "entry.md").write_text("x")
        result = check_unpublished_blogs(str(tmp_path), "")
        assert result == []


class TestListWorkspaceBranches:
    def test_excludes_main_and_current(self, tmp_path):
        _init_git(tmp_path)
        subprocess.run(["git", "-C", str(tmp_path), "checkout", "-b", "issue-42"], capture_output=True)
        subprocess.run(["git", "-C", str(tmp_path), "commit", "--allow-empty", "-m", "work"], capture_output=True)
        subprocess.run(["git", "-C", str(tmp_path), "checkout", "-b", "issue-50"], capture_output=True)
        subprocess.run(["git", "-C", str(tmp_path), "commit", "--allow-empty", "-m", "work"], capture_output=True)
        subprocess.run(["git", "-C", str(tmp_path), "checkout", "main"], capture_output=True)

        branches = list_workspace_branches(str(tmp_path), "issue-42")
        assert "main" not in branches
        assert "issue-42" not in branches
        assert "issue-50" in branches


class TestCheckStaleBranches:
    def test_reports_stale(self, tmp_path):
        _init_git(tmp_path)
        subprocess.run(["git", "-C", str(tmp_path), "checkout", "-b", "old-branch"], capture_output=True)
        # Backdate the commit to make it stale
        subprocess.run(
            ["git", "-C", str(tmp_path), "commit", "--allow-empty",
             "-m", "old work", "--date", "2020-01-01T00:00:00"],
            capture_output=True,
            env={**subprocess.os.environ, "GIT_COMMITTER_DATE": "2020-01-01T00:00:00"},
        )
        subprocess.run(["git", "-C", str(tmp_path), "checkout", "main"], capture_output=True)

        stale = check_stale_branches(str(tmp_path), ["old-branch"])
        assert len(stale) == 1
        assert stale[0]["branch"] == "old-branch"

    def test_skips_closed_branches(self, tmp_path):
        _init_git(tmp_path)
        subprocess.run(["git", "-C", str(tmp_path), "checkout", "-b", "closed-branch"], capture_output=True)
        (tmp_path / "design").mkdir(parents=True, exist_ok=True)
        (tmp_path / "design" / "EPIC-CLOSED.md").write_text("closed")
        subprocess.run(["git", "-C", str(tmp_path), "add", "."], capture_output=True)
        subprocess.run(
            ["git", "-C", str(tmp_path), "commit", "-m", "close",
             "--date", "2020-01-01T00:00:00"],
            capture_output=True,
            env={**subprocess.os.environ, "GIT_COMMITTER_DATE": "2020-01-01T00:00:00"},
        )
        subprocess.run(["git", "-C", str(tmp_path), "checkout", "main"], capture_output=True)

        stale = check_stale_branches(str(tmp_path), ["closed-branch"])
        assert stale == []


class TestCheckUnrecoveredArtifacts:
    def test_detects_unrecovered_blog(self, tmp_path):
        _init_git(tmp_path)
        subprocess.run(["git", "-C", str(tmp_path), "checkout", "-b", "closed-branch"], capture_output=True)
        (tmp_path / "design").mkdir(parents=True, exist_ok=True)
        (tmp_path / "design" / "EPIC-CLOSED.md").write_text("closed")
        (tmp_path / "blog").mkdir(parents=True, exist_ok=True)
        (tmp_path / "blog" / "entry.md").write_text("blog")
        subprocess.run(["git", "-C", str(tmp_path), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "close"], capture_output=True)
        subprocess.run(["git", "-C", str(tmp_path), "checkout", "main"], capture_output=True)

        result = check_unrecovered_artifacts(str(tmp_path), ["closed-branch"])
        assert len(result) == 1
        assert result[0]["type"] == "blog"
        assert result[0]["file"] == "entry.md"


class TestCheckUnstampedBranches:
    def test_detects_unstamped(self, tmp_path):
        workspace = tmp_path / "workspace"
        project = tmp_path / "project"
        _init_git(workspace)
        _init_git(project)

        # Create a closed workspace branch
        subprocess.run(["git", "-C", str(workspace), "checkout", "-b", "issue-42"], capture_output=True)
        (workspace / "design").mkdir(parents=True, exist_ok=True)
        (workspace / "design" / "EPIC-CLOSED.md").write_text("closed")
        subprocess.run(["git", "-C", str(workspace), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(workspace), "commit", "-m", "close"], capture_output=True)
        subprocess.run(["git", "-C", str(workspace), "checkout", "main"], capture_output=True)

        # Create matching project branch without stamp
        subprocess.run(["git", "-C", str(project), "checkout", "-b", "issue-42"], capture_output=True)
        subprocess.run(["git", "-C", str(project), "commit", "--allow-empty", "-m", "feat: work"], capture_output=True)
        subprocess.run(["git", "-C", str(project), "checkout", "main"], capture_output=True)

        result = check_unstamped_branches(str(workspace), str(project), ["issue-42"], False)
        assert len(result) == 1
        assert result[0]["branch"] == "issue-42"
        assert result[0]["project_branch_exists"] is True

    def test_stamped_branch_not_reported(self, tmp_path):
        workspace = tmp_path / "workspace"
        project = tmp_path / "project"
        _init_git(workspace)
        _init_git(project)

        subprocess.run(["git", "-C", str(workspace), "checkout", "-b", "issue-42"], capture_output=True)
        (workspace / "design").mkdir(parents=True, exist_ok=True)
        (workspace / "design" / "EPIC-CLOSED.md").write_text("closed")
        subprocess.run(["git", "-C", str(workspace), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(workspace), "commit", "-m", "close"], capture_output=True)
        subprocess.run(["git", "-C", str(workspace), "checkout", "main"], capture_output=True)

        subprocess.run(["git", "-C", str(project), "checkout", "-b", "issue-42"], capture_output=True)
        subprocess.run(["git", "-C", str(project), "commit", "--allow-empty",
                         "-m", "chore: branch closed — landed as abc123 on main"], capture_output=True)
        subprocess.run(["git", "-C", str(project), "checkout", "main"], capture_output=True)

        result = check_unstamped_branches(str(workspace), str(project), ["issue-42"], False)
        assert result == []


class TestIntegration:
    SCRIPT = Path(__file__).parent.parent / "work-end" / "hygiene_scan.py"

    def test_produces_valid_json(self, tmp_path):
        workspace = tmp_path / "workspace"
        project = tmp_path / "project"
        _init_git(workspace)
        _init_git(project)

        result = subprocess.run(
            [sys.executable, str(self.SCRIPT),
             str(workspace), str(project),
             "branch=issue-42", "blog_dest=", "single_repo=no"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "unpublished_blogs" in data
        assert "stale_branches" in data
        assert "unrecovered_artifacts" in data
        assert "unstamped_branches" in data
        assert "flyway_conflicts" in data

    def test_missing_branch_arg(self):
        result = subprocess.run(
            [sys.executable, str(self.SCRIPT), "/tmp", "/tmp"],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
