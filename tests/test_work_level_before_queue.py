"""A start brings the workspace clone level with canonical before touching the queue (#567)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "project"))
sys.path.insert(0, str(ROOT / "work-slot"))

import canonical_sync as cs  # noqa: E402
import work  # noqa: E402
from queue_io import Queue, QueueItem, QueueState, read_queue, write_queue  # noqa: E402


def g(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    assert r.returncode == 0, f"git {' '.join(args)}: {r.stderr}"
    return r.stdout.strip()


def queue(repo: Path, closed: list[str], message: str) -> None:
    write_queue(repo, Queue(
        items=[QueueItem(ref=ref, title="t", completed=True, active=False) for ref in closed],
        state=QueueState(branch="", issue_repo="O/r", status="drained")))
    g(repo, "add", ".queue")
    g(repo, "commit", "-q", "-m", message)


@pytest.fixture
def world(tmp_path):
    """Canonical workspace and its clone in a permanent slot; canonical then moves on."""
    canonical = tmp_path / "family-ws"
    canonical.mkdir()
    g(canonical, "init", "-q", "-b", "main")
    queue(canonical, ["o/r#1"], "queue at clone time")
    slot = tmp_path / "family" / "clone" / "P"
    slot.mkdir(parents=True)
    (slot / ".slot").write_text("# Clone P\n")
    (slot / ".permanent").touch()
    clone = slot / "wsp"
    subprocess.run(["git", "clone", "-q", "--shared", str(canonical), str(clone)], check=True)
    g(clone, "remote", "rename", "origin", "local")
    queue(canonical, ["o/r#1", "o/r#2"], "canonical closes another item")
    return canonical, clone


def args(clone: Path, **extra: str) -> dict[str, str]:
    return {"command": "start", "workspace": str(clone), "project": str(clone),
            "branch": "main", "base_branch": "main", "on_main": "yes", **extra}


class TestFollowReportsBlocked:

    def test_behind_and_clean_fast_forwards(self, world):
        canonical, clone = world
        assert cs.follow(clone) == "fast-forward"
        assert g(clone, "rev-parse", "main") == g(canonical, "rev-parse", "main")

    def test_behind_with_a_conflicting_uncommitted_change_is_blocked_not_current(self, world):
        canonical, clone = world
        (clone / ".queue").write_text("local edit\n")
        before = g(clone, "rev-parse", "main")
        assert cs.follow(clone) == "blocked"
        assert g(clone, "rev-parse", "main") == before
        assert (clone / ".queue").read_text() == "local edit\n"

    def test_level_is_current(self, world):
        canonical, clone = world
        cs.follow(clone)
        assert cs.follow(clone) == "current"


class TestNamedStartLevelsFirst:

    def test_the_observed_failure_queue_is_written_on_top_of_canonicals(self, world):
        canonical, clone = world

        routed, lines, stop = work.apply_route(args(clone, issue_n="9"))

        assert not stop
        assert lines[0] == "WORKSPACE_FOLLOWED=fast-forward"
        assert g(clone, "rev-parse", "main") == g(canonical, "rev-parse", "main")
        refs = [i.ref for i in read_queue(clone).items]
        assert "o/r#2" in refs, "the item canonical closed must still be in the queue"
        assert read_queue(clone).active_item().ref == "o/r#9"
        assert g(clone, "merge-base", "HEAD", "local/main") == g(canonical, "rev-parse", "main")

    def test_a_clone_that_cannot_catch_up_stops_the_start_and_changes_nothing(self, world):
        canonical, clone = world
        (clone / ".queue").write_text("local edit\n")

        routed, lines, stop = work.apply_route(args(clone, issue_n="9"))

        assert stop
        assert "ACTION=decision" in lines and "DECISION=workspace_not_level" in lines
        assert (clone / ".queue").read_text() == "local edit\n"

    def test_a_diverged_clone_stops_the_start(self, world):
        canonical, clone = world
        (clone / "note.md").write_text("x")
        g(clone, "add", "note.md")
        g(clone, "commit", "-q", "-m", "local commit on main")

        routed, lines, stop = work.apply_route(args(clone, issue_n="9"))

        assert stop and "DECISION=workspace_not_level" in lines

    def test_routed_start_levels_first_too(self, world):
        canonical, clone = world
        routed, lines, stop = work.apply_route(args(clone, command="continue"))
        assert lines and lines[0] == "WORKSPACE_FOLLOWED=fast-forward"
        assert g(clone, "rev-parse", "main") == g(canonical, "rev-parse", "main")

    def test_work_already_on_a_branch_is_never_stopped_by_it(self, world):
        canonical, clone = world
        g(clone, "checkout", "-q", "-b", "issue-5-x")
        (clone / "note.md").write_text("x")
        g(clone, "add", "note.md")
        g(clone, "commit", "-q", "-m", "work")
        g(clone, "branch", "-f", "main", "HEAD")      # main diverges from canonical
        a = args(clone, command="continue", branch="issue-5-x", on_main="no")
        routed, lines, stop = work.apply_route(a)
        assert "DECISION=workspace_not_level" not in lines

    def test_a_canonical_workspace_is_left_alone(self, tmp_path):
        repo = tmp_path / "ws"
        repo.mkdir()
        g(repo, "init", "-q", "-b", "main")
        queue(repo, ["o/r#1"], "q")
        assert work.level_before_queue_write(args(repo)) == ([], False)

    def test_a_follow_up_call_does_not_level(self, world):
        canonical, clone = world
        before = g(clone, "rev-parse", "main")
        work.apply_route(args(clone, issue_n="9", step_done="branch_name"))
        assert g(clone, "rev-parse", "main") == before
