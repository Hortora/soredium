"""Tests for work-end/hygiene_scan.py"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

script_dir = Path(__file__).parent.parent / "work-end"
sys.path.insert(0, str(script_dir))

from hygiene_scan import (
    branch_has_file,
    check_unpublished_blogs,
    check_stale_branches,
    check_unrecovered_artifacts,
    check_unstamped_branches,
    list_branch_files,
    list_branch_files_recursive,
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
        subprocess.run(
            ["git", "-C", str(tmp_path), "commit", "--allow-empty",
             "-m", "chore: branch closed — landed as abc123 on main",
             "--date", "2020-01-01T00:00:00"],
            capture_output=True,
            env={**subprocess.os.environ, "GIT_COMMITTER_DATE": "2020-01-01T00:00:00"},
        )
        subprocess.run(["git", "-C", str(tmp_path), "checkout", "main"], capture_output=True)

        stale = check_stale_branches(str(tmp_path), ["closed-branch"])
        assert stale == []


class TestCheckUnrecoveredArtifacts:
    def test_detects_unrecovered_blog(self, tmp_path):
        workspace = tmp_path / "workspace"
        project = tmp_path / "project"
        _init_git(workspace)
        _init_git(project)

        subprocess.run(["git", "-C", str(workspace), "checkout", "-b", "closed-branch"], capture_output=True)
        (workspace / "blog").mkdir(parents=True, exist_ok=True)
        (workspace / "blog" / "entry.md").write_text("blog")
        subprocess.run(["git", "-C", str(workspace), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(workspace), "commit", "-m", "add blog"], capture_output=True)
        subprocess.run(["git", "-C", str(workspace), "commit", "--allow-empty",
                         "-m", "chore: branch closed — landed as abc123 on main"], capture_output=True)
        subprocess.run(["git", "-C", str(workspace), "checkout", "main"], capture_output=True)

        routing = {"blog": "workspace", "specs": "project"}
        result = check_unrecovered_artifacts(str(workspace), str(project), ["closed-branch"], routing)
        assert len(result) == 1
        assert result[0]["type"] == "blog"
        assert result[0]["file"] == "entry.md"


class TestCheckUnstampedBranches:
    def test_detects_merged_unstamped(self, tmp_path):
        workspace = tmp_path / "workspace"
        project = tmp_path / "project"
        _init_git(workspace)
        _init_git(project)

        subprocess.run(["git", "-C", str(project), "checkout", "-b", "issue-42"], capture_output=True)
        subprocess.run(["git", "-C", str(project), "commit", "--allow-empty", "-m", "feat: work"], capture_output=True)
        subprocess.run(["git", "-C", str(project), "checkout", "main"], capture_output=True)
        subprocess.run(["git", "-C", str(project), "merge", "--ff-only", "issue-42"], capture_output=True)

        result = check_unstamped_branches(str(workspace), str(project), ["issue-42"], False)
        assert len(result) == 1
        assert result[0]["branch"] == "issue-42"
        assert result[0]["closure_state"] == "merged_unstamped"

    def test_stamped_branch_not_reported(self, tmp_path):
        workspace = tmp_path / "workspace"
        project = tmp_path / "project"
        _init_git(workspace)
        _init_git(project)

        subprocess.run(["git", "-C", str(project), "checkout", "-b", "issue-42"], capture_output=True)
        subprocess.run(["git", "-C", str(project), "commit", "--allow-empty",
                         "-m", "chore: branch closed — landed as abc123 on main"], capture_output=True)
        subprocess.run(["git", "-C", str(project), "checkout", "main"], capture_output=True)

        result = check_unstamped_branches(str(workspace), str(project), ["issue-42"], False)
        assert result == []


class TestSubdirectoryWorkspace:
    """Tree-path lookups must prepend the subdir prefix when workspace is not the repo root."""

    def _init_repo_with_subdir(self, tmp_path):
        repo = tmp_path / "repo"
        _init_git(repo)
        subdir = repo / "subdir"
        subdir.mkdir()
        return repo, subdir

    def test_branch_has_file_in_subdir(self, tmp_path):
        repo, subdir = self._init_repo_with_subdir(tmp_path)
        (subdir / "design").mkdir()
        (subdir / "design" / ".meta").write_text("branch: test\n")
        subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "add meta"],
                       capture_output=True)

        assert branch_has_file(str(subdir), "main", "design/.meta") is True

    def test_branch_has_file_false_for_missing(self, tmp_path):
        repo, subdir = self._init_repo_with_subdir(tmp_path)
        assert branch_has_file(str(subdir), "main", "design/.meta") is False

    def test_list_branch_files_in_subdir(self, tmp_path):
        repo, subdir = self._init_repo_with_subdir(tmp_path)
        (subdir / "blog").mkdir()
        (subdir / "blog" / "entry.md").write_text("# Blog\n")
        subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "add blog"],
                       capture_output=True)

        files = list_branch_files(str(subdir), "main", "blog")
        assert "entry.md" in files

    def test_list_branch_files_recursive_in_subdir(self, tmp_path):
        repo, subdir = self._init_repo_with_subdir(tmp_path)
        (subdir / "specs" / "issue-42").mkdir(parents=True)
        (subdir / "specs" / "issue-42" / "design.md").write_text("# Spec\n")
        subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "add spec"],
                       capture_output=True)

        files = list_branch_files_recursive(str(subdir), "main", "specs")
        assert "design.md" in files

    def test_at_repo_root_still_works(self, tmp_path):
        """Existing behavior: when workspace IS the repo root, prefix is empty."""
        repo = tmp_path / "repo"
        _init_git(repo)
        (repo / "blog").mkdir()
        (repo / "blog" / "entry.md").write_text("# Blog\n")
        subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "add blog"],
                       capture_output=True)

        assert branch_has_file(str(repo), "main", "blog/entry.md") is True
        files = list_branch_files(str(repo), "main", "blog")
        assert "entry.md" in files


class TestPersistFindings:
    def test_writes_jsonl_format(self, tmp_path):
        """persist_findings writes JSONL with extended format fields."""
        from hygiene_scan import persist_findings
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        result = {
            "unrecovered_artifacts": [
                {"type": "blog", "file": "entry.md", "branch": "issue-100"}
            ],
            "unstamped_branches": [
                {"branch": "issue-200", "closure_state": "merged_unstamped"}
            ],
            "stale_branches": [
                {"branch": "issue-300", "last_commit_age": "45 days"}
            ],
        }
        persist_findings(str(workspace), result)
        path = workspace / ".audit" / "findings.jsonl"
        assert path.exists(), "should write to findings.jsonl not findings.json"
        lines = [l for l in path.read_text().strip().split("\n") if l]
        assert len(lines) == 3
        for line in lines:
            entry = json.loads(line)
            assert entry["category"] == "hygiene"
            assert "location" in entry
            assert "severity" in entry
            assert entry["severity"] == "warning"
            assert entry["source"] == "hygiene-scan"

    def test_location_format(self, tmp_path):
        """Location uses artifact:file:branch or branch:name format."""
        from hygiene_scan import persist_findings
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        result = {
            "unrecovered_artifacts": [
                {"type": "blog", "file": "entry.md", "branch": "issue-100"}
            ],
            "unstamped_branches": [],
            "stale_branches": [
                {"branch": "issue-300", "last_commit_age": "45 days"}
            ],
        }
        persist_findings(str(workspace), result)
        path = workspace / ".audit" / "findings.jsonl"
        lines = [json.loads(l) for l in path.read_text().strip().split("\n") if l]
        artifact = [f for f in lines if f["check"] == "unrecovered_artifact"][0]
        assert artifact["location"] == "artifact:entry.md:issue-100"
        stale = [f for f in lines if f["check"] == "stale_branch"][0]
        assert stale["location"] == "branch:issue-300"


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
