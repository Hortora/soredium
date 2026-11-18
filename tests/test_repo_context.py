"""Tests for RepoContext — classify-once frozen context."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

_project_dir = str(Path(__file__).resolve().parent.parent / "project")
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)

from repo_state import (
    RepoContext, RepoState, RepoType, RepoDisposition,
    build_repo_context, build_repo_contexts,
)


def _make_repo(tmp_path, name="test-repo", base_branch="main"):
    repo = tmp_path / name
    repo.mkdir()
    subprocess.run(["git", "init", "-b", base_branch, str(repo)],
                   capture_output=True, check=True)
    (repo / "file.txt").write_text("content")
    subprocess.run(["git", "-C", str(repo), "add", "."],
                   capture_output=True, check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"],
                   capture_output=True, check=True)
    return repo


def _make_state(repo_path, branch="main", disposition=RepoDisposition.HAS_WORK,
                repo_type=RepoType.PROJECT, commits_ahead=1):
    return RepoState(
        path=repo_path, name=repo_path.name, repo_type=repo_type,
        disposition=disposition, branch=branch, commits_ahead=commits_ahead,
        is_dirty=False, has_remote=False, remote_branch_exists=False,
        landing_sha=None, has_upstream=False, push_remote="origin",
        canonical_path=None, is_slot_clone=False,
    )


def test_repo_context_is_frozen(tmp_path):
    repo = _make_repo(tmp_path)
    state = _make_state(repo)
    ctx = build_repo_context(state, "main")
    with pytest.raises(AttributeError):
        ctx.tree_sha = "changed"


def test_tree_sha_computed(tmp_path):
    repo = _make_repo(tmp_path)
    state = _make_state(repo, branch="main")
    ctx = build_repo_context(state, "main")
    assert ctx.tree_sha != ""
    assert len(ctx.tree_sha) == 40


def test_main_tree_sha_computed(tmp_path):
    repo = _make_repo(tmp_path)
    state = _make_state(repo, branch="main")
    ctx = build_repo_context(state, "main")
    assert ctx.main_tree_sha != ""
    assert len(ctx.main_tree_sha) == 40


def test_no_branch_gives_empty_tree_sha(tmp_path):
    repo = _make_repo(tmp_path)
    state = _make_state(repo, branch=None, disposition=RepoDisposition.NO_BRANCH)
    ctx = build_repo_context(state, "main")
    assert ctx.tree_sha == ""


def test_remote_synced_false_without_remote(tmp_path):
    repo = _make_repo(tmp_path)
    state = _make_state(repo)
    ctx = build_repo_context(state, "main")
    assert ctx.remote_synced is False


def test_lifecycle_state_none_without_conn(tmp_path):
    repo = _make_repo(tmp_path)
    state = _make_state(repo)
    ctx = build_repo_context(state, "main")
    assert ctx.lifecycle_state is None


def test_lifecycle_state_from_db(tmp_path):
    repo = _make_repo(tmp_path)
    state = _make_state(repo)

    _lib = str(Path.home() / ".claude" / "lib")
    if _lib not in sys.path:
        sys.path.insert(0, _lib)
    import worklog
    conn = worklog.connect(":memory:")
    conn.execute("INSERT INTO repos (path) VALUES (?)", ("/tmp/test",))
    conn.execute(
        "INSERT INTO work_items (id, branch, repo_id, state, created_at) "
        "VALUES (1, 'feature', 1, 'active', datetime('now'))",
    )
    metadata = json.dumps({"from_state": "idle", "to_state": "active"})
    conn.execute(
        "INSERT INTO events (timestamp, event_type, work_item_id, metadata) "
        "VALUES (datetime('now'), 'activate', 1, ?)",
        (metadata,),
    )
    conn.commit()

    ctx = build_repo_context(state, "main", conn=conn, work_item_id=1)
    assert ctx.lifecycle_state == "active"


def test_build_repo_contexts_batch(tmp_path):
    repo1 = _make_repo(tmp_path, "repo1")
    repo2 = _make_repo(tmp_path, "repo2")
    states = [_make_state(repo1), _make_state(repo2)]
    contexts = build_repo_contexts(states, "main")
    assert len(contexts) == 2
    assert all(isinstance(c, RepoContext) for c in contexts)


def test_state_composition(tmp_path):
    repo = _make_repo(tmp_path)
    state = _make_state(repo, disposition=RepoDisposition.EMPTY_BRANCH)
    ctx = build_repo_context(state, "main")
    assert ctx.state is state
    assert ctx.state.disposition == RepoDisposition.EMPTY_BRANCH
    assert ctx.state.path == repo
