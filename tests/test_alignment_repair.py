"""project/alignment_repair.py against real git repos (#548)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "project"))

from alignment import detect  # noqa: E402
from alignment_repair import adoptable_base, repair  # noqa: E402
from branch_base import base_of, parent_of, record  # noqa: E402

GIT_ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t"}


def g(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                       env={**os.environ, **GIT_ENV})
    assert r.returncode == 0, f"git {' '.join(args)}: {r.stderr}"
    return r.stdout.strip()


def commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name)
    g(repo, "add", name)
    g(repo, "commit", "-q", "-m", name)
    return g(repo, "rev-parse", "HEAD")


def snapshot(repo: Path) -> tuple[str, str, str]:
    return g(repo, "status", "--porcelain"), g(repo, "rev-parse", "HEAD"), g(repo, "for-each-ref")


@pytest.fixture
def repos(tmp_path):
    out = []
    for name in ("project", "workspace"):
        repo = tmp_path / name
        repo.mkdir()
        g(repo, "init", "-q", "-b", "main")
        commit(repo, "base.txt")
        out.append(repo)
    return out


def hand_made(project: Path, branch: str = "issue-289-url") -> str:
    """A branch made with plain git, as a session that skipped work start does."""
    fork = g(project, "rev-parse", "HEAD")
    g(project, "checkout", "-q", "-b", branch)
    commit(project, "work.txt")
    return fork


class TestWorkspaceBehind:
    def test_branch_missing_in_workspace_is_created_and_recorded(self, repos):
        project, workspace = repos
        fork = hand_made(project)
        ws_main = g(workspace, "rev-parse", "main")
        found = detect(project, workspace)
        assert found.state == "workspace_behind"

        result = repair(found, project, workspace)

        assert result.ok, result.detail
        assert g(workspace, "branch", "--show-current") == "issue-289-url"
        assert base_of(workspace, "issue-289-url") == ws_main
        assert base_of(project, "issue-289-url") == fork
        assert detect(project, workspace).state == "aligned"

    def test_the_observed_failure_ends_aligned_with_nothing_lost(self, repos):
        """Project branch made by hand, workspace left on main with queue commits."""
        project, workspace = repos
        hand_made(project)
        queue_commit = commit(workspace, ".queue")
        project_tip = g(project, "rev-parse", "HEAD")

        assert repair(detect(project, workspace), project, workspace).ok

        assert g(project, "rev-parse", "HEAD") == project_tip
        assert g(workspace, "rev-parse", "HEAD") == queue_commit
        assert g(workspace, "rev-parse", "main") == queue_commit
        assert (workspace / ".queue").exists()

    def test_existing_workspace_branch_is_checked_out_not_recreated(self, repos):
        project, workspace = repos
        hand_made(project)
        g(workspace, "checkout", "-q", "-b", "issue-289-url")
        ws_tip = commit(workspace, "notes.md")
        g(workspace, "checkout", "-q", "main")

        assert repair(detect(project, workspace), project, workspace).ok

        assert g(workspace, "branch", "--show-current") == "issue-289-url"
        assert g(workspace, "rev-parse", "HEAD") == ws_tip
        assert detect(project, workspace).state == "aligned"

    def test_recorded_base_is_never_overwritten(self, repos):
        project, workspace = repos
        fork = hand_made(project)
        record(project, "issue-289-url", fork, parent="")
        before = g(project, "for-each-ref", "refs/soredium")
        assert repair(detect(project, workspace), project, workspace).ok
        assert g(project, "for-each-ref", "refs/soredium") == before

    def test_repaired_branch_is_not_marked_stacked(self, repos):
        project, workspace = repos
        hand_made(project)
        repair(detect(project, workspace), project, workspace)
        assert parent_of(project, "issue-289-url") == ""
        assert parent_of(workspace, "issue-289-url") == ""


class TestUnrecordedBranch:
    def test_base_is_recorded_in_both_repos(self, repos):
        project, workspace = repos
        fork = hand_made(project)
        ws_fork = g(workspace, "rev-parse", "HEAD")
        g(workspace, "checkout", "-q", "-b", "issue-289-url")
        found = detect(project, workspace)
        assert found.state == "unrecorded_branch"

        result = repair(found, project, workspace)

        assert result.ok
        assert base_of(project, "issue-289-url") == fork
        assert base_of(workspace, "issue-289-url") == ws_fork
        assert detect(project, workspace).state == "aligned"

    def test_base_branch_that_moved_on_still_gives_the_fork_point(self, repos):
        project, workspace = repos
        fork = hand_made(project)
        g(project, "checkout", "-q", "main")
        commit(project, "later.txt")
        g(project, "checkout", "-q", "issue-289-url")
        g(workspace, "checkout", "-q", "-b", "issue-289-url")
        assert repair(detect(project, workspace), project, workspace).ok
        assert base_of(project, "issue-289-url") == fork

    def test_only_branch_refs_change(self, repos):
        project, workspace = repos
        hand_made(project)
        g(workspace, "checkout", "-q", "-b", "issue-289-url")
        before = [(s[0], s[1]) for s in (snapshot(project), snapshot(workspace))]
        repair(detect(project, workspace), project, workspace)
        assert [(s[0], s[1]) for s in (snapshot(project), snapshot(workspace))] == before


class TestRefusals:
    def test_branch_stacked_by_hand_is_not_adopted(self, repos):
        """Recording main as its base would land the parent's commits as its own."""
        project, workspace = repos
        g(project, "checkout", "-q", "-b", "issue-1-parent")
        commit(project, "parent.txt")
        g(project, "checkout", "-q", "-b", "issue-2-child")
        commit(project, "child.txt")
        g(workspace, "checkout", "-q", "-b", "issue-2-child")
        before = snapshot(project), snapshot(workspace)

        result = repair(detect(project, workspace), project, workspace)

        assert not result.ok
        assert result.reason == "origin_unclear"
        assert "issue-1-parent" in result.detail
        assert (snapshot(project), snapshot(workspace)) == before

    def test_stacked_project_branch_leaves_a_behind_workspace_untouched(self, repos):
        project, workspace = repos
        g(project, "checkout", "-q", "-b", "issue-1-parent")
        commit(project, "parent.txt")
        g(project, "checkout", "-q", "-b", "issue-2-child")
        commit(project, "child.txt")
        before = snapshot(workspace)
        result = repair(detect(project, workspace), project, workspace)
        assert not result.ok
        assert snapshot(workspace) == before

    def test_a_landed_sibling_branch_does_not_block_adoption(self, repos):
        project, workspace = repos
        g(project, "checkout", "-q", "-b", "issue-1-landed")
        commit(project, "landed.txt")
        g(project, "checkout", "-q", "main")
        g(project, "merge", "-q", "--ff-only", "issue-1-landed")
        fork = hand_made(project)
        g(workspace, "checkout", "-q", "-b", "issue-289-url")
        assert repair(detect(project, workspace), project, workspace).ok
        assert base_of(project, "issue-289-url") == fork

    @pytest.mark.parametrize("state", ["on_base", "aligned", "workspace_dirty",
                                       "workspace_other", "detached"])
    def test_other_states_are_never_touched(self, repos, state):
        project, workspace = repos
        if state == "aligned":
            fork = hand_made(project)
            record(project, "issue-289-url", fork)
            ws = g(workspace, "rev-parse", "HEAD")
            g(workspace, "checkout", "-q", "-b", "issue-289-url")
            record(workspace, "issue-289-url", ws)
        elif state == "workspace_dirty":
            hand_made(project)
            (workspace / "loose.txt").write_text("x")
        elif state == "workspace_other":
            hand_made(project)
            g(workspace, "checkout", "-q", "-b", "issue-7-other")
        elif state == "project_behind":
            g(workspace, "checkout", "-q", "-b", "issue-289-url")
        elif state == "detached":
            g(project, "checkout", "-q", "--detach")
        found = detect(project, workspace)
        assert found.state == state
        before = snapshot(project), snapshot(workspace)
        result = repair(found, project, workspace)
        assert not result.ok and result.reason == "not_repairable"
        assert (snapshot(project), snapshot(workspace)) == before


class TestProjectBehind:
    """project_behind = workspace on a branch, project on main.

    Repairable when workspace is clean: checks workspace out to main.
    The branch is preserved — it may hold unmerged work.
    """

    def test_clean_workspace_checked_out_to_main(self, repos):
        project, workspace = repos
        g(workspace, "checkout", "-q", "-b", "issue-250-eigentrust")
        commit(workspace, "stale-work.txt")
        found = detect(project, workspace)
        assert found.state == "project_behind"

        result = repair(found, project, workspace)

        assert result.ok, result.detail
        assert g(workspace, "branch", "--show-current") == "main"
        assert detect(project, workspace).state == "on_base"

    def test_branch_is_preserved_after_repair(self, repos):
        project, workspace = repos
        g(workspace, "checkout", "-q", "-b", "issue-250-eigentrust")
        tip = commit(workspace, "stale-work.txt")
        found = detect(project, workspace)

        repair(found, project, workspace)

        branches = g(workspace, "branch", "--list", "issue-250-eigentrust")
        assert "issue-250-eigentrust" in branches
        assert g(workspace, "rev-parse", "issue-250-eigentrust") == tip

    def test_dirty_workspace_is_refused(self, repos):
        project, workspace = repos
        g(workspace, "checkout", "-q", "-b", "issue-250-eigentrust")
        (workspace / "uncommitted.txt").write_text("dirty")
        found = detect(project, workspace)
        assert found.state == "project_behind"
        before = snapshot(project), snapshot(workspace)

        result = repair(found, project, workspace)

        assert not result.ok
        assert result.reason == "workspace_dirty"
        assert (snapshot(project), snapshot(workspace)) == before

    def test_project_state_unchanged(self, repos):
        project, workspace = repos
        g(workspace, "checkout", "-q", "-b", "issue-250-eigentrust")
        commit(workspace, "stale-work.txt")
        before = snapshot(project)

        repair(detect(project, workspace), project, workspace)

        assert snapshot(project) == before


class TestAdoptableBase:
    def test_unrelated_history_is_refused(self, repos, tmp_path):
        project, _ = repos
        g(project, "checkout", "-q", "--orphan", "issue-9-orphan")
        commit(project, "orphan.txt")
        sha, why = adoptable_base(project, "issue-9-orphan", "main")
        assert sha == "" and "shares no history" in why
