"""The queue file must survive being passed between its two readers and writers (#516).

work-slot/plan_manager.py and project/queue_io.py both read and write `.queue`.
These tests hand one file back and forth and assert nothing is lost.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "project"))
sys.path.insert(0, str(ROOT / "work-slot"))
sys.path.insert(0, str(ROOT / "work-end"))

import plan_manager as pm  # noqa: E402
from queue_io import Queue, QueueItem, QueueState, read_queue, write_queue  # noqa: E402

PLAN_MANAGER = ROOT / "work-slot" / "plan_manager.py"
REPO = "Hortora/soredium"


def cli(command: str, path: Path, *opts: str) -> subprocess.CompletedProcess:
    r = subprocess.run([sys.executable, str(PLAN_MANAGER), command, str(path), *opts],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"{command} failed: {r.stdout} {r.stderr}"
    return r


def deferred_titles(path: Path) -> list[str]:
    return [d.title for d in pm.list_deferred(path)]


def new_queue(ws: Path, name: str = ".queue") -> Path:
    """A two-item queue as queue_io writes it; optionally renamed to the legacy file name."""
    write_queue(ws, Queue(
        items=[QueueItem(ref=f"{REPO}#1", title="First", completed=False, active=True),
               QueueItem(ref=f"{REPO}#2", title="Second", completed=False, active=False)],
        state=QueueState(branch="issue-1-first", issue_repo=REPO, status="active"),
    ))
    path = ws / ".queue"
    if name != ".queue":
        path = path.rename(ws / name)
    return path


def refs(items) -> list[str]:
    return [str(i.ref).lower() for i in items]


class TestDeferredSurvivesRewrites:

    @pytest.mark.parametrize("name", [".queue", ".plan"])
    def test_defer_without_repos_survives_the_next_write(self, tmp_path, name):
        path = new_queue(tmp_path, name)
        cli("defer", path, "title=tidy the hook", "scale=XS", "complexity=Low")
        assert deferred_titles(path) == ["tidy the hook"]

        cli("set-state", path, "key=covers", f"value={REPO}#1")

        assert deferred_titles(path) == ["tidy the hook"]

    def test_two_defers_without_repos_are_both_kept(self, tmp_path):
        path = new_queue(tmp_path)
        cli("defer", path, "title=first deferred", "scale=XS", "complexity=Low")
        cli("defer", path, "title=second deferred", "scale=M", "complexity=Med")

        assert deferred_titles(path) == ["first deferred", "second deferred"]

    def test_defer_with_repos_and_reason_round_trips(self, tmp_path):
        path = new_queue(tmp_path)
        cli("defer", path, "title=needs engine", "scale=M", "complexity=High",
            "repos=engine,agency", "reason=blocked on API")
        cli("set-state", path, "key=covers", f"value={REPO}#1")

        (item,) = pm.list_deferred(path)
        assert (item.title, item.scale, item.complexity) == ("needs engine", "M", "High")
        assert item.repos == ["engine", "agency"]
        assert item.reason == "blocked on API"

    def test_title_containing_parentheses(self, tmp_path):
        path = new_queue(tmp_path)
        cli("defer", path, "title=replace import (slot archival rewrite)", "scale=M", "complexity=Med")
        cli("set-state", path, "key=covers", f"value={REPO}#1")

        assert deferred_titles(path) == ["replace import (slot archival rewrite)"]

    def test_deferred_survives_advance(self, tmp_path):
        path = new_queue(tmp_path)
        cli("defer", path, "title=keep me", "scale=S", "complexity=Low")

        cli("advance", path)

        assert deferred_titles(path) == ["keep me"]

    def test_unparseable_deferred_line_is_kept_verbatim(self, tmp_path):
        path = new_queue(tmp_path)
        path.write_text(path.read_text() + "\n## Deferred\n- a hand-written note with no size\n")

        cli("set-state", path, "key=covers", f"value={REPO}#1")

        assert "- a hand-written note with no size" in path.read_text()

    def test_unknown_section_is_kept(self, tmp_path):
        path = new_queue(tmp_path)
        path.write_text(path.read_text() + "\n## Notes\nremember the fixture\n- and this bullet\n")

        cli("set-state", path, "key=covers", f"value={REPO}#1")

        text = path.read_text()
        assert "## Notes" in text
        assert "remember the fixture" in text
        assert "- and this bullet" in text


class TestHeading:

    def test_heading_with_empty_slug_is_not_doubled(self, tmp_path):
        path = new_queue(tmp_path)
        path.write_text("# Work Plan — \n\n" + path.read_text())

        cli("set-state", path, "key=covers", f"value={REPO}#1")
        cli("set-state", path, "key=covers", f"value={REPO}#2")

        headings = [l for l in path.read_text().splitlines() if l.startswith("# ")]
        assert len(headings) == 1
        assert headings[0].count("Work Plan") == 1

    def test_heading_slug_is_preserved(self, tmp_path):
        path = new_queue(tmp_path)
        path.write_text("# Work Plan — my-epic\n\n" + path.read_text())

        cli("set-state", path, "key=covers", f"value={REPO}#1")
        cli("set-state", path, "key=covers", f"value={REPO}#2")

        headings = [l for l in path.read_text().splitlines() if l.startswith("# ")]
        assert headings == ["# Work Plan — my-epic"]


class TestBothModulesReadEachOthersFile:

    def test_queue_io_reads_items_after_a_plan_manager_write(self, tmp_path):
        path = new_queue(tmp_path)

        cli("set-state", path, "key=covers", f"value={REPO}#1")

        q = read_queue(tmp_path)
        assert refs(q.items) == [f"{REPO}#1".lower(), f"{REPO}#2".lower()]
        assert q.active_item() is not None
        assert str(q.active_item().ref).lower() == f"{REPO}#1".lower()
        assert q.state.branch == "issue-1-first"
        assert q.state.status == "active"
        assert q.state.covers == f"{REPO}#1"
        assert not any("## Queue" in l for l in q.deferred_lines)

    def test_plan_manager_reads_items_after_a_queue_io_write(self, tmp_path):
        path = new_queue(tmp_path)

        tree = pm.parse_plan(path)

        assert refs(tree.queue) == [f"{REPO}#1".lower(), f"{REPO}#2".lower()]
        assert tree.queue[0].active and not tree.queue[1].active
        assert tree.state["branch"] == "issue-1-first"

    def test_full_round_trip_keeps_everything(self, tmp_path):
        path = new_queue(tmp_path)
        cli("defer", path, "title=carried through", "scale=S", "complexity=Low")
        cli("check", path, f"issues={REPO}#1")

        q = read_queue(tmp_path)
        write_queue(tmp_path, q)
        cli("set-state", path, "key=covers", f"value={REPO}#2")
        q = read_queue(tmp_path)
        write_queue(tmp_path, q)

        tree = pm.parse_plan(path)
        assert refs(tree.queue) == [f"{REPO}#1".lower(), f"{REPO}#2".lower()]
        assert tree.queue[0].completed and not tree.queue[1].completed
        assert tree.state["branch"] == "issue-1-first"
        assert tree.state["status"] == "active"
        assert tree.state["covers"] == f"{REPO}#2"
        assert deferred_titles(path) == ["carried through"]
        assert path.read_text().count("## Deferred") == 1
        assert path.read_text().count("## State") == 1

    def test_items_are_not_filed_under_deferred_when_queue_io_writes_back(self, tmp_path):
        path = new_queue(tmp_path)
        cli("set-state", path, "key=covers", f"value={REPO}#1")

        write_queue(tmp_path, read_queue(tmp_path))

        text = path.read_text()
        assert "## Deferred" not in text
        assert refs(pm.parse_plan(path).queue) == [f"{REPO}#1".lower(), f"{REPO}#2".lower()]

    def test_state_deferred_queue_section_order(self, tmp_path):
        """A queue laid out State, Deferred, Queue (as seen in a live workspace)."""
        (tmp_path / ".queue").write_text(
            "\n## State\n"
            "branch: issue-1-first\nissue-repo: Hortora/soredium\nstatus: active\n\n"
            "## Deferred\n"
            "- [ ] later thing (S / Low) []\n\n"
            "## Queue\n"
            "- [x] Hortora/soredium#1 — First\n"
            "- [ ] Hortora/soredium#2 — Second ← active\n"
        )

        q = read_queue(tmp_path)

        assert refs(q.items) == [f"{REPO}#1".lower(), f"{REPO}#2".lower()]
        assert str(q.active_item().ref).lower() == f"{REPO}#2".lower()
        assert any("later thing" in l for l in q.deferred_lines)

    def test_close_advances_a_queue_written_by_plan_manager(self, tmp_path):
        from close import advance

        path = new_queue(tmp_path)
        cli("set-state", path, "key=covers", f"value={REPO}#1")
        active = read_queue(tmp_path).active_item()
        assert active is not None, "close.py must see the active item"

        next_item = advance(tmp_path, active.ref)

        assert next_item is not None
        assert str(next_item.ref).lower() == f"{REPO}#2".lower()
        tree = pm.parse_plan(path)
        assert tree.queue[0].completed
        assert tree.queue[1].active


class TestNestedTasks:

    LAYOUT = (
        "## State\nbranch: b\nissue-repo: Hortora/soredium\nstatus: active\n\n"
        "## Queue\n"
        "- [ ] Hortora/soredium#1 — First ← active\n"
        "  - [x] Batch 1: one\n"
        "    - [x] Task 1: do a thing\n"
        "    - [ ] Task 2: do another\n"
        "- [ ] Hortora/soredium#2 — Second\n"
    )

    def test_nested_batches_and_tasks_are_not_read_as_items(self, tmp_path):
        (tmp_path / ".queue").write_text(self.LAYOUT)

        q = read_queue(tmp_path)

        assert refs(q.items) == [f"{REPO}#1".lower(), f"{REPO}#2".lower()]

    def test_nested_tasks_survive_a_queue_io_round_trip(self, tmp_path):
        path = tmp_path / ".queue"
        path.write_text(self.LAYOUT)

        write_queue(tmp_path, read_queue(tmp_path))

        tree = pm.parse_plan(path)
        assert refs(tree.queue) == [f"{REPO}#1".lower(), f"{REPO}#2".lower()]
        assert [(t.name, t.done) for t in tree.queue[0].tasks] == [
            ("do a thing", True), ("do another", False)]

    def test_advance_skips_tasks_and_activates_the_next_issue(self, tmp_path):
        from close import advance

        (tmp_path / ".queue").write_text(self.LAYOUT)
        active = read_queue(tmp_path).active_item()

        next_item = advance(tmp_path, active.ref)

        assert str(next_item.ref).lower() == f"{REPO}#2".lower()
