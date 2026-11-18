"""The alignment gate at the entry to project/work.py, on real git repos (#548)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "project"))
sys.path.insert(0, str(ROOT / "work-slot"))

import work  # noqa: E402
from branch_base import base_of, record  # noqa: E402
from queue_io import Queue, QueueItem, QueueState, write_queue  # noqa: E402

GIT_ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t"}


@pytest.fixture(autouse=True)
def _git_env(monkeypatch):
    for key, value in GIT_ENV.items():
        monkeypatch.setenv(key, value)


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


def call(project: Path, workspace: Path, command: str = "continue", **extra: str):
    branch = g(workspace, "symbolic-ref", "--short", "-q", "HEAD")
    args = {"command": command, "project": str(project), "workspace": str(workspace),
            "base_branch": "main", "branch": branch,
            "on_main": "yes" if branch == "main" else "no", **extra}
    return work.apply_alignment(args)


def started(repo: Path, branch: str) -> None:
    fork = g(repo, "rev-parse", "HEAD")
    g(repo, "checkout", "-q", "-b", branch)
    record(repo, branch, fork)


def queue(workspace: Path, branch: str, active: bool) -> None:
    write_queue(workspace, Queue(
        items=[QueueItem(ref="o/r#7", title="T", completed=False, active=active)],
        state=QueueState(branch=branch, issue_repo="o/r", status="active")))
    g(workspace, "add", ".queue")
    g(workspace, "commit", "-q", "-m", "queue")


class TestNothingToDo:

    def test_both_on_base_passes_silently(self, repos):
        args, lines, stop = call(*repos)
        assert (lines, stop) == ([], False)

    def test_aligned_branch_passes_silently(self, repos):
        for repo in repos:
            started(repo, "issue-7-x")
        args, lines, stop = call(*repos)
        assert (lines, stop) == ([], False)


class TestRepairs:

    def test_workspace_left_behind_joins_the_project_branch(self, repos):
        project, workspace = repos
        g(project, "checkout", "-q", "-b", "issue-7-x")
        commit(project, "work.txt")

        args, lines, stop = call(project, workspace)

        assert not stop
        assert lines[0] == "ALIGNMENT_REPAIRED=workspace_behind"
        assert lines[1].startswith("ALIGNMENT_ACTIONS=")
        assert g(workspace, "symbolic-ref", "--short", "HEAD") == "issue-7-x"
        assert base_of(project, "issue-7-x") and base_of(workspace, "issue-7-x")
        assert args["branch"] == "issue-7-x"
        assert args["on_main"] == "no"

    def test_the_caller_s_arguments_are_not_mutated(self, repos):
        project, workspace = repos
        g(project, "checkout", "-q", "-b", "issue-7-x")
        branch = g(workspace, "symbolic-ref", "--short", "HEAD")
        given = {"command": "continue", "project": str(project), "workspace": str(workspace),
                 "base_branch": "main", "branch": branch, "on_main": "yes"}
        before = dict(given)
        work.apply_alignment(given)
        assert given == before

    def test_hand_made_branch_in_both_repos_gets_its_base_recorded(self, repos):
        for repo in repos:
            g(repo, "checkout", "-q", "-b", "issue-7-x")
            commit(repo, "work.txt")

        args, lines, stop = call(*repos)

        assert not stop
        assert lines[0] == "ALIGNMENT_REPAIRED=unrecorded_branch"
        assert all(base_of(repo, "issue-7-x") for repo in repos)

    def test_a_second_call_after_a_repair_is_silent(self, repos):
        project, workspace = repos
        g(project, "checkout", "-q", "-b", "issue-7-x")
        call(project, workspace)
        assert call(project, workspace)[1:] == ([], False)


class TestDecisions:

    def _unchanged(self, repos, act):
        before = [snapshot(r) for r in repos]
        result = act()
        assert [snapshot(r) for r in repos] == before
        return result

    def test_dirty_workspace_is_not_switched(self, repos):
        project, workspace = repos
        g(project, "checkout", "-q", "-b", "issue-7-x")
        (workspace / "notes.md").write_text("unsaved")

        args, lines, stop = self._unchanged(repos, lambda: call(project, workspace))

        assert stop
        assert lines[0] == "ALIGNMENT=workspace_dirty"
        assert "ACTION=decision" in lines
        assert "DECISION=alignment_workspace_dirty" in lines
        assert any(l.startswith("OPTIONS=commit_workspace_changes_then_retry") for l in lines)

    def test_repos_on_different_branches(self, repos):
        project, workspace = repos
        started(project, "issue-7-x")
        started(workspace, "issue-8-y")
        args, lines, stop = self._unchanged(repos, lambda: call(project, workspace))
        assert stop and "DECISION=alignment_workspace_other" in lines

    def test_project_left_on_base(self, repos):
        project, workspace = repos
        started(workspace, "issue-7-x")
        args, lines, stop = self._unchanged(repos, lambda: call(project, workspace))
        assert stop and "DECISION=alignment_project_behind" in lines

    def test_detached_project(self, repos):
        project, workspace = repos
        g(project, "checkout", "-q", "--detach")
        args, lines, stop = self._unchanged(repos, lambda: call(project, workspace))
        assert stop and "DECISION=alignment_detached" in lines

    def test_project_that_is_not_a_repository(self, repos, tmp_path):
        workspace = repos[1]
        plain = tmp_path / "plain"
        plain.mkdir()
        args, lines, stop = call(plain, workspace)
        assert stop and "DECISION=alignment_unreadable" in lines

    def test_branch_built_by_hand_on_another_working_branch_is_refused(self, repos):
        project, workspace = repos
        started(project, "issue-6-parent")
        commit(project, "parent.txt")
        g(project, "checkout", "-q", "-b", "issue-7-x")
        commit(project, "child.txt")

        args, lines, stop = self._unchanged(repos, lambda: call(project, workspace))

        assert stop
        assert "DECISION=alignment_origin_unclear" in lines
        assert any(l.startswith("OPTIONS=land_the_parent_branch_first") for l in lines)

    def test_every_decision_names_options(self, repos):
        for state in ("workspace_dirty", "workspace_other", "project_behind",
                      "queue_mismatch", "detached", "unreadable", "origin_unclear"):
            assert work.ALIGNMENT_OPTIONS[state]


class TestQueueMismatch:

    def test_stale_queue_branch_with_nothing_active_is_left_to_routing(self, repos):
        project, workspace = repos
        queue(workspace, "issue-3-old", active=False)
        for repo in repos:
            started(repo, "issue-7-x")
        assert call(project, workspace)[1:] == ([], False)

    def test_active_item_on_another_branch_is_a_decision(self, repos):
        project, workspace = repos
        queue(workspace, "issue-3-old", active=True)
        for repo in repos:
            started(repo, "issue-7-x")
        args, lines, stop = call(project, workspace)
        assert stop and "DECISION=alignment_queue_mismatch" in lines


class TestSkipped:

    def _misaligned(self, repos):
        project, workspace = repos
        g(project, "checkout", "-q", "-b", "issue-7-x")
        return project, workspace

    @pytest.mark.parametrize("extra", [
        {"step_done": "resolve_issue"},
        {"in_slot": "yes"},
    ])
    def test_gate_does_not_run(self, repos, extra):
        project, workspace = self._misaligned(repos)
        before = snapshot(workspace)
        assert call(project, workspace, **extra)[1:] == ([], False)
        assert snapshot(workspace) == before

    def test_named_start_is_not_gated(self, repos):
        project, workspace = self._misaligned(repos)
        assert call(project, workspace, command="start", issue_n="9")[1:] == ([], False)

    @pytest.mark.parametrize("command", ["pause", "resume", "find"])
    def test_other_commands_are_not_gated(self, repos, command):
        project, workspace = self._misaligned(repos)
        assert call(project, workspace, command=command)[1:] == ([], False)

    def test_one_repo_serving_as_both(self, repos):
        project = repos[0]
        g(project, "checkout", "-q", "-b", "issue-7-x")
        assert call(project, project)[1:] == ([], False)

    @pytest.mark.parametrize("command", ["start", "continue", "next", "done"])
    def test_every_routed_command_is_gated(self, repos, command):
        project, workspace = self._misaligned(repos)
        args, lines, stop = call(project, workspace, command=command)
        assert lines[0] == "ALIGNMENT_REPAIRED=workspace_behind"


class TestThroughMain:

    def test_a_decision_stops_before_routing(self, repos, monkeypatch, capsys):
        project, workspace = repos
        queue(workspace, "", active=False)
        g(project, "checkout", "-q", "-b", "issue-7-x")
        (workspace / "notes.md").write_text("unsaved")
        monkeypatch.setattr(sys, "argv", [
            "work.py", "continue", f"project={project}", f"workspace={workspace}",
            "base_branch=main", "branch=main", "on_main=yes"])

        assert work.main() == 0

        out = capsys.readouterr().out
        assert "DECISION=alignment_workspace_dirty" in out
        assert "ROUTE_REASON" not in out

    def test_a_repair_is_reported_and_routing_sees_the_branch(self, repos, monkeypatch, capsys):
        project, workspace = repos
        queue(workspace, "", active=False)
        g(project, "checkout", "-q", "-b", "issue-7-x")
        monkeypatch.setattr(work, "build_context",
                            lambda args: (_ for _ in ()).throw(SystemExit(args["branch"])))
        monkeypatch.setattr(sys, "argv", [
            "work.py", "continue", f"project={project}", f"workspace={workspace}",
            "base_branch=main", "branch=main", "on_main=yes"])

        with pytest.raises(SystemExit) as stopped:
            work.main()

        out = capsys.readouterr().out
        assert stopped.value.code == "issue-7-x"
        assert out.index("ALIGNMENT_REPAIRED=workspace_behind") < out.index("ROUTE_REASON=")
        assert "ROUTE_REASON=branch_item_activated" in out
        assert "ACTIVATED=o/r#7" in out
