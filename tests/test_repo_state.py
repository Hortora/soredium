"""Tests for project/repo_state.py"""

import subprocess
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "project"))


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "commit", "--allow-empty", "-m", "init"],
                   capture_output=True, check=True)


def _make_branch_with_commits(repo: Path, branch: str, n: int = 1) -> None:
    subprocess.run(["git", "-C", str(repo), "checkout", "-b", branch],
                   capture_output=True, check=True)
    for i in range(n):
        (repo / f"file{i}.txt").write_text(f"content {i}")
        subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", f"commit {i}"],
                       capture_output=True, check=True)


class TestClassifyRepoDisposition:
    def test_has_work(self, tmp_path):
        repo = tmp_path / "project"
        repo.mkdir()
        _init_repo(repo)
        _make_branch_with_commits(repo, "feature", n=2)

        from repo_state import classify_repo, RepoType, RepoDisposition
        state = classify_repo(repo, "feature", "main", RepoType.PROJECT)

        assert state.disposition == RepoDisposition.HAS_WORK
        assert state.commits_ahead == 2
        assert state.branch == "feature"

    def test_empty_branch_is_already_landed(self, tmp_path):
        """A freshly created branch with no commits is ALREADY_LANDED —
        its tip is an ancestor of base, so there's nothing to land."""
        repo = tmp_path / "project"
        repo.mkdir()
        _init_repo(repo)
        subprocess.run(["git", "-C", str(repo), "checkout", "-b", "feature"],
                       capture_output=True, check=True)

        from repo_state import classify_repo, RepoType, RepoDisposition
        state = classify_repo(repo, "feature", "main", RepoType.PROJECT)

        assert state.disposition == RepoDisposition.ALREADY_LANDED
        assert state.commits_ahead == 0
        assert state.branch == "feature"

    def test_no_branch(self, tmp_path):
        repo = tmp_path / "project"
        repo.mkdir()
        _init_repo(repo)

        from repo_state import classify_repo, RepoType, RepoDisposition
        state = classify_repo(repo, "feature", "main", RepoType.PROJECT)

        assert state.disposition == RepoDisposition.NO_BRANCH
        assert state.commits_ahead == 0
        assert state.branch is None

    def test_already_landed_after_merge(self, tmp_path):
        """Branch with commits merged to main — ALREADY_LANDED."""
        repo = tmp_path / "project"
        repo.mkdir()
        _init_repo(repo)
        _make_branch_with_commits(repo, "feature", n=1)
        subprocess.run(["git", "-C", str(repo), "checkout", "main"],
                       capture_output=True, check=True)
        subprocess.run(["git", "-C", str(repo), "merge", "--no-ff", "feature"],
                       capture_output=True, check=True)

        from repo_state import classify_repo, RepoType, RepoDisposition
        state = classify_repo(repo, "feature", "main", RepoType.PROJECT)

        assert state.disposition == RepoDisposition.ALREADY_LANDED
        assert state.branch == "feature"


class TestClassifyRepoTopology:
    def test_identity_fields(self, tmp_path):
        repo = tmp_path / "myrepo"
        repo.mkdir()
        _init_repo(repo)

        from repo_state import classify_repo, RepoType
        state = classify_repo(repo, "feature", "main", RepoType.PROJECT)

        assert state.path == repo
        assert state.name == "myrepo"
        assert state.repo_type == RepoType.PROJECT

    def test_no_upstream(self, tmp_path):
        repo = tmp_path / "project"
        repo.mkdir()
        _init_repo(repo)

        from repo_state import classify_repo, RepoType
        state = classify_repo(repo, "feature", "main", RepoType.PROJECT)

        assert state.has_upstream is False
        assert state.push_remote == "origin"

    def test_has_upstream(self, tmp_path):
        repo = tmp_path / "project"
        repo.mkdir()
        _init_repo(repo)
        upstream = tmp_path / "upstream"
        upstream.mkdir()
        _init_repo(upstream)
        subprocess.run(["git", "-C", str(repo), "remote", "add", "upstream", str(upstream)],
                       capture_output=True, check=True)

        from repo_state import classify_repo, RepoType
        state = classify_repo(repo, "feature", "main", RepoType.PROJECT)

        assert state.has_upstream is True
        assert state.push_remote == "upstream"

    def test_slot_clone(self, tmp_path):
        canonical = tmp_path / "canonical"
        canonical.mkdir()
        _init_repo(canonical)
        clone = tmp_path / "clone"
        clone.mkdir()
        _init_repo(clone)
        subprocess.run(["git", "-C", str(clone), "remote", "add", "local", str(canonical)],
                       capture_output=True, check=True)

        from repo_state import classify_repo, RepoType
        state = classify_repo(clone, "feature", "main", RepoType.CLONE)

        assert state.is_slot_clone is True
        assert state.canonical_path == canonical
        assert state.push_remote == "local"

    def test_is_dirty(self, tmp_path):
        repo = tmp_path / "project"
        repo.mkdir()
        _init_repo(repo)
        (repo / "uncommitted.txt").write_text("dirty")

        from repo_state import classify_repo, RepoType
        state = classify_repo(repo, "feature", "main", RepoType.PROJECT)

        assert state.is_dirty is True

    def test_frozen(self, tmp_path):
        repo = tmp_path / "project"
        repo.mkdir()
        _init_repo(repo)

        from repo_state import classify_repo, RepoType
        state = classify_repo(repo, "feature", "main", RepoType.PROJECT)

        with pytest.raises(AttributeError):
            state.disposition = "something"


class TestClassifyRepos:
    def test_non_slot_mode(self, tmp_path):
        proj = tmp_path / "project"
        proj.mkdir()
        _init_repo(proj)
        ws = tmp_path / "workspace"
        ws.mkdir()
        _init_repo(ws)

        from repo_state import classify_repos, RepoType
        repos = classify_repos(proj, ws, "feature", "main")

        assert len(repos) == 2
        assert repos[0].repo_type == RepoType.PROJECT
        assert repos[0].name == "project"
        assert repos[1].repo_type == RepoType.WORKSPACE
        assert repos[1].name == "workspace"

    def test_slot_mode(self, tmp_path):
        slot = tmp_path / "slot"
        slot.mkdir()
        (slot / ".slot").write_text(
            "# Slot 1\nslug: feature\n\n"
            "## Issue\nOrg/repo#1\nCovers: 1\n\n"
            "## Repos\n- engine (primary)\n- iot\n\n"
            "## State\nstate: active\n"
        )
        for name in ["engine", "iot"]:
            r = slot / name
            r.mkdir()
            _init_repo(r)

        from repo_state import classify_repos, RepoType
        repos = classify_repos(
            slot / "engine", slot / "workspace", "feature", "main",
            slot_path=slot,
        )

        assert len(repos) == 2
        assert repos[0].name == "engine"
        assert repos[0].repo_type == RepoType.CLONE
        assert repos[1].name == "iot"

    def test_slot_mode_missing_dir(self, tmp_path):
        slot = tmp_path / "slot"
        slot.mkdir()
        (slot / ".slot").write_text(
            "# Slot 1\nslug: feature\n\n"
            "## Issue\nOrg/repo#1\nCovers: 1\n\n"
            "## Repos\n- engine (primary)\n- ghost\n\n"
            "## State\nstate: active\n"
        )
        engine = slot / "engine"
        engine.mkdir()
        _init_repo(engine)

        from repo_state import classify_repos
        repos = classify_repos(
            engine, slot / "workspace", "feature", "main",
            slot_path=slot,
        )

        assert len(repos) == 1
        assert repos[0].name == "engine"

    def test_empty_slot(self, tmp_path):
        slot = tmp_path / "slot"
        slot.mkdir()

        from repo_state import classify_repos
        repos = classify_repos(
            tmp_path / "proj", tmp_path / "ws", "feature", "main",
            slot_path=slot,
        )

        assert repos == []


class TestDifferentBranchDisposition:
    """#492: repos on a different feature branch should get DIFFERENT_BRANCH."""

    def test_repo_on_different_branch(self, tmp_path):
        repo = tmp_path / "engine"
        repo.mkdir()
        _init_repo(repo)
        _make_branch_with_commits(repo, "issue-377-topology", n=2)

        from repo_state import classify_repo, RepoType, RepoDisposition
        state = classify_repo(repo, "issue-382-budget", "main", RepoType.CLONE)

        assert state.disposition == RepoDisposition.DIFFERENT_BRANCH
        assert state.branch == "issue-377-topology"

    def test_repo_on_target_branch_still_has_work(self, tmp_path):
        repo = tmp_path / "agency"
        repo.mkdir()
        _init_repo(repo)
        _make_branch_with_commits(repo, "issue-382-budget", n=3)

        from repo_state import classify_repo, RepoType, RepoDisposition
        state = classify_repo(repo, "issue-382-budget", "main", RepoType.CLONE)

        assert state.disposition == RepoDisposition.HAS_WORK

    def test_repo_on_main_is_no_branch(self, tmp_path):
        """Repo on main with no feature branch → NO_BRANCH, not DIFFERENT_BRANCH."""
        repo = tmp_path / "docs"
        repo.mkdir()
        _init_repo(repo)

        from repo_state import classify_repo, RepoType, RepoDisposition
        state = classify_repo(repo, "issue-382-budget", "main", RepoType.CLONE)

        assert state.disposition == RepoDisposition.NO_BRANCH

    def test_slot_classify_skips_different_branch_repos(self, tmp_path):
        """classify_repos in slot mode should classify repos on other branches correctly."""
        slot = tmp_path / "slot"
        slot.mkdir()

        for name, branch in [("engine", "issue-377-topology"), ("agency", "issue-382-budget")]:
            repo = slot / name
            repo.mkdir()
            _init_repo(repo)
            _make_branch_with_commits(repo, branch, n=1)
            # Repos stay on their feature branches (not checked out to main)

        (slot / ".slot").write_text("# Slot\n## Repos\n- engine (primary)\n- agency\n## Status\nstatus: active\n")

        from repo_state import classify_repos, RepoDisposition
        repos = classify_repos(slot / "engine", slot / "engine", "issue-382-budget", "main", slot_path=slot)

        engine_state = next(r for r in repos if r.name == "engine")
        agency_state = next(r for r in repos if r.name == "agency")

        assert engine_state.disposition == RepoDisposition.DIFFERENT_BRANCH
        assert engine_state.branch == "issue-377-topology"
        assert agency_state.disposition == RepoDisposition.HAS_WORK


class TestScanSlotBranches:
    """#492: scan_slot_branches discovers all active feature branches."""

    def test_finds_multiple_branches(self, tmp_path):
        slot = tmp_path / "slot"
        slot.mkdir()

        for name, branch in [("engine", "issue-377-topology"), ("agency", "issue-382-budget")]:
            repo = slot / name
            repo.mkdir()
            _init_repo(repo)
            _make_branch_with_commits(repo, branch, n=1)

        (slot / ".slot").write_text("# Slot\n## Repos\n- engine\n- agency\n## Status\nstatus: active\n")

        from repo_state import scan_slot_branches
        branches = scan_slot_branches(slot)
        assert len(branches) == 2
        assert "issue-377-topology" in branches
        assert "issue-382-budget" in branches

    def test_repos_on_main_excluded(self, tmp_path):
        slot = tmp_path / "slot"
        slot.mkdir()

        repo1 = slot / "engine"
        repo1.mkdir()
        _init_repo(repo1)
        _make_branch_with_commits(repo1, "issue-377-topology", n=1)

        repo2 = slot / "docs"
        repo2.mkdir()
        _init_repo(repo2)

        (slot / ".slot").write_text("# Slot\n## Repos\n- engine\n- docs\n## Status\nstatus: active\n")

        from repo_state import scan_slot_branches
        branches = scan_slot_branches(slot)
        assert branches == {"issue-377-topology"}

    def test_empty_slot(self, tmp_path):
        slot = tmp_path / "slot"
        slot.mkdir()
        (slot / ".slot").write_text("# Slot\n## Repos\n## Status\nstatus: active\n")

        from repo_state import scan_slot_branches
        branches = scan_slot_branches(slot)
        assert branches == set()


