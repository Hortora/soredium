"""Tests for project/repo_state.py"""

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

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


def _make_repo_state(disposition, repo_type=None, has_upstream=False, name="project"):
    from repo_state import RepoState, RepoType, RepoDisposition, RepoContext
    state = RepoState(
        path=Path(f"/fake/{name}"),
        name=name,
        repo_type=repo_type or RepoType.PROJECT,
        disposition=disposition,
        branch="feature" if disposition != RepoDisposition.NO_BRANCH else None,
        commits_ahead=2 if disposition == RepoDisposition.HAS_WORK else 0,
        is_dirty=False,
        has_remote=True,
        remote_branch_exists=False,
        landing_sha=None,
        has_upstream=has_upstream,
        push_remote="upstream" if has_upstream else "origin",
        canonical_path=None,
        is_slot_clone=False,
    )
    return RepoContext(
        state=state, tree_sha="", main_tree_sha="",
        remote_synced=False, lifecycle_state=None,
    )


sys.path.insert(0, str(Path(__file__).parent.parent / "work-end"))


class TestSkipPredicates:
    def test_skip_empty_branch_with_no_branch(self):
        from repo_state import RepoDisposition
        from work_end_orchestrator import _skip_empty_branch

        ctx = MagicMock()
        ctx.on_main = False
        ctx.repos = [_make_repo_state(RepoDisposition.NO_BRANCH)]

        assert _skip_empty_branch(ctx) is True

    def test_skip_empty_branch_with_work(self):
        from repo_state import RepoDisposition
        from work_end_orchestrator import _skip_empty_branch

        ctx = MagicMock()
        ctx.on_main = False
        ctx.repos = [_make_repo_state(RepoDisposition.HAS_WORK)]

        assert _skip_empty_branch(ctx) is False

    def test_skip_empty_branch_on_main(self):
        from repo_state import RepoDisposition
        from work_end_orchestrator import _skip_empty_branch

        ctx = MagicMock()
        ctx.on_main = True
        ctx.repos = [_make_repo_state(RepoDisposition.NO_BRANCH)]

        assert _skip_empty_branch(ctx) is False

    def test_skip_no_upstream_without(self):
        from repo_state import RepoDisposition
        from work_end_orchestrator import _skip_no_upstream

        ctx = MagicMock()
        ctx.repos = [_make_repo_state(RepoDisposition.HAS_WORK, has_upstream=False)]

        assert _skip_no_upstream(ctx) is True

    def test_skip_no_upstream_with(self):
        from repo_state import RepoDisposition
        from work_end_orchestrator import _skip_no_upstream

        ctx = MagicMock()
        ctx.repos = [_make_repo_state(RepoDisposition.HAS_WORK, has_upstream=True)]

        assert _skip_no_upstream(ctx) is False

    def test_skip_partial_close_no_unlanded(self):
        from repo_state import RepoDisposition, RepoType
        from work_end_orchestrator import _skip_multi_repo_partial_close

        ctx = MagicMock()
        ctx.in_slot = True
        ctx.repos = [
            _make_repo_state(RepoDisposition.HAS_WORK, RepoType.CLONE, name="engine"),
            _make_repo_state(RepoDisposition.HAS_WORK, RepoType.CLONE, name="iot"),
        ]
        ctx.progress = {"land:engine": "done", "land:iot": "done"}

        assert _skip_multi_repo_partial_close(ctx) is False

    def test_skip_partial_close_with_unlanded(self):
        from repo_state import RepoDisposition, RepoType
        from work_end_orchestrator import _skip_multi_repo_partial_close

        ctx = MagicMock()
        ctx.in_slot = True
        ctx.repos = [
            _make_repo_state(RepoDisposition.HAS_WORK, RepoType.CLONE, name="engine"),
            _make_repo_state(RepoDisposition.HAS_WORK, RepoType.CLONE, name="iot"),
        ]
        ctx.progress = {"land:engine": "done"}

        assert _skip_multi_repo_partial_close(ctx) is True

    def test_skip_partial_close_single_repo(self):
        from repo_state import RepoDisposition, RepoType
        from work_end_orchestrator import _skip_multi_repo_partial_close

        ctx = MagicMock()
        ctx.in_slot = True
        ctx.repos = [_make_repo_state(RepoDisposition.HAS_WORK, RepoType.CLONE, name="engine")]
        ctx.progress = {}

        assert _skip_multi_repo_partial_close(ctx) is False

    def test_skip_partial_close_not_slot(self):
        from work_end_orchestrator import _skip_multi_repo_partial_close

        ctx = MagicMock()
        ctx.in_slot = False
        ctx.repos = []

        assert _skip_multi_repo_partial_close(ctx) is False


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
