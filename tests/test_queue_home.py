"""Where an area of work keeps its queue, and switching a slot to its root queue (#577)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "project"))

import queue_home  # noqa: E402
from queue_io import Queue, QueueItem, QueueState, read_queue, write_queue  # noqa: E402

SCRIPT = str(ROOT / "project" / "queue_home.py")


def queue(*refs: str, branch: str = "", active: str = "") -> Queue:
    return Queue(items=[QueueItem(ref=r, title=f"T {r}", completed=False, active=(r == active))
                        for r in refs],
                 state=QueueState(branch=branch, issue_repo="O/r", status="active"))


def tree(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.fixture
def slot(tmp_path):
    """A slot with a stale root queue and two workspace clones holding different queues."""
    area = tmp_path / "slots" / "7"
    area.mkdir(parents=True)
    (area / ".slot").write_text("# Slot 7\n")
    write_queue(area, queue("o/r#1"))
    for name, refs, branch in (("wsp-a", ("o/r#1", "o/r#2", "o/r#3"), "issue-2-b"),
                               ("wsp-b", ("o/x#9",), "issue-9-z")):
        ws = area / name
        ws.mkdir()
        (ws / ".workspace").write_text("project: x\n")
        write_queue(ws, queue(*refs, branch=branch, active=refs[-1]))
    (area / "engine").mkdir()            # a project clone: no .workspace, never a candidate
    return area


class TestHome:

    def test_an_unmarked_slot_is_left_to_the_callers_existing_behaviour(self, slot):
        assert queue_home.home(slot) is None
        assert queue_home.home(slot / "wsp-a") is None

    def test_a_marked_slot_uses_its_root_from_the_root_or_any_workspace_clone(self, slot):
        queue_home.mark(slot)
        assert queue_home.home(slot) == slot.resolve()
        assert queue_home.home(slot / "wsp-a") == slot.resolve()
        assert queue_home.home(slot / "wsp-b") == slot.resolve()

    def test_a_plain_workspace_is_never_decided_here(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        write_queue(ws, queue("o/r#1"))
        assert queue_home.area_root(ws) is None and queue_home.home(ws) is None

    def test_a_marker_without_a_slot_file_means_nothing(self, tmp_path):
        (tmp_path / queue_home.MARKER).write_text("since: x\n")
        assert queue_home.home(tmp_path) is None


class TestCandidates:

    def test_lists_the_root_and_every_workspace_clone_but_no_project_clone(self, slot):
        found = queue_home.candidates(slot)
        assert [c.directory.name for c in found] == ["7", "wsp-a", "wsp-b"]
        by_name = {c.directory.name: c for c in found}
        assert by_name["wsp-a"].items == 3 and by_name["wsp-a"].active == "o/r#3"
        assert by_name["wsp-a"].branch == "issue-2-b"
        assert by_name["7"].items == 1

    def test_listing_changes_no_file(self, slot):
        (slot / "wsp-b" / ".queue").unlink()
        (slot / "wsp-b" / ".plan").write_text(
            "- [ ] O/x#9: Old\n\n## State\nbranch: issue-9-z\nstate: active\n")
        before = tree(slot)
        found = queue_home.candidates(slot)
        assert tree(slot) == before
        assert next(c for c in found if c.directory.name == "wsp-b").name == ".plan"


class TestAdopt:

    def test_several_queues_and_no_choice_is_refused_and_changes_nothing(self, slot):
        before = tree(slot)
        with pytest.raises(queue_home.AdoptError) as refused:
            queue_home.adopt(slot, apply=True)
        assert refused.value.code == "choose_one"
        assert tree(slot) == before

    def test_a_dry_run_says_what_would_happen_and_changes_nothing(self, slot):
        before = tree(slot)
        plan = queue_home.adopt(slot, source=slot / "wsp-a")
        assert plan["applied"] is False and plan["chosen"].endswith("wsp-a/.queue")
        assert plan["backup"]
        assert tree(slot) == before

    def test_apply_copies_the_chosen_queue_keeps_the_old_root_and_marks_the_slot(self, slot):
        old_root = (slot / ".queue").read_bytes()
        chosen = (slot / "wsp-a" / ".queue").read_bytes()
        other = (slot / "wsp-b" / ".queue").read_bytes()

        plan = queue_home.adopt(slot, source=slot / "wsp-a", apply=True)

        assert plan["applied"] is True
        assert (slot / ".queue").read_bytes() == chosen
        assert Path(plan["backup"]).read_bytes() == old_root
        assert (slot / "wsp-a" / ".queue").read_bytes() == chosen, "the source is kept"
        assert (slot / "wsp-b" / ".queue").read_bytes() == other, "the others are kept"
        assert queue_home.home(slot / "wsp-b") == slot.resolve()
        assert "adopted-from:" in (slot / queue_home.MARKER).read_text()
        assert read_queue(slot).active_item().ref == "o/r#3"

    def test_keeping_the_root_queue_writes_only_the_marker(self, slot):
        before = tree(slot)
        plan = queue_home.adopt(slot, source=slot, apply=True)
        after = tree(slot)
        assert plan["backup"] == ""
        assert {k: v for k, v in after.items() if k != queue_home.MARKER} == before

    def test_a_second_backup_never_overwrites_the_first(self, slot):
        queue_home.adopt(slot, source=slot / "wsp-a", apply=True)
        first = sorted(p.name for p in slot.glob(".queue.before-adopt-*"))
        (slot / queue_home.MARKER).unlink()
        queue_home.adopt(slot, source=slot / "wsp-b", apply=True)
        second = sorted(p.name for p in slot.glob(".queue.before-adopt-*"))
        assert len(first) == 1 and len(second) == 2 and first[0] in second

    def test_an_already_switched_slot_is_refused(self, slot):
        queue_home.adopt(slot, source=slot, apply=True)
        before = tree(slot)
        with pytest.raises(queue_home.AdoptError) as refused:
            queue_home.adopt(slot, source=slot / "wsp-a", apply=True)
        assert refused.value.code == "already_adopted" and tree(slot) == before

    def test_a_directory_with_no_queue_is_refused(self, slot):
        before = tree(slot)
        with pytest.raises(queue_home.AdoptError) as refused:
            queue_home.adopt(slot, source=slot / "engine", apply=True)
        assert refused.value.code == "no_queue_there" and tree(slot) == before

    def test_an_unreadable_queue_is_refused_and_changes_nothing(self, slot):
        (slot / "wsp-b" / ".queue").write_bytes(b"\xff\xfe not a queue")
        before = tree(slot)
        with pytest.raises(queue_home.AdoptError) as refused:
            queue_home.adopt(slot, source=slot / "wsp-b", apply=True)
        assert refused.value.code == "unreadable" and tree(slot) == before

    def test_an_older_plan_file_is_adopted_as_a_queue_and_the_plan_is_left_alone(self, slot):
        (slot / "wsp-b" / ".queue").unlink()
        plan_text = "- [ ] O/x#9: Old\n\n## State\nbranch: issue-9-z\nstate: active\n"
        (slot / "wsp-b" / ".plan").write_text(plan_text)
        queue_home.adopt(slot, source=slot / "wsp-b", apply=True)
        assert (slot / "wsp-b" / ".plan").read_text() == plan_text
        assert not (slot / "wsp-b" / ".queue").exists()
        assert read_queue(slot).state.branch == "issue-9-z"

    def test_a_slot_with_one_queue_needs_no_choice(self, tmp_path):
        area = tmp_path / "clone" / "repo"
        (area / "wsp").mkdir(parents=True)
        (area / ".slot").write_text("# clone\n")
        (area / "wsp" / ".workspace").write_text("project: x\n")
        write_queue(area / "wsp", queue("o/r#1", active="o/r#1", branch="issue-1-a"))
        plan = queue_home.adopt(area, apply=True)
        assert plan["applied"] and read_queue(area).active_item().ref == "o/r#1"

    def test_a_slot_with_no_queue_at_all_is_marked_and_starts_empty(self, tmp_path):
        area = tmp_path / "slots" / "8"
        area.mkdir(parents=True)
        (area / ".slot").write_text("# Slot 8\n")
        plan = queue_home.adopt(area, apply=True)
        assert plan["applied"] and queue_home.uses_root(area)
        assert not (area / ".queue").exists()

    def test_not_a_slot_is_refused(self, tmp_path):
        with pytest.raises(queue_home.AdoptError) as refused:
            queue_home.adopt(tmp_path, apply=True)
        assert refused.value.code == "not_an_area"


class TestCommandLine:

    def test_show_lists_every_queue_and_changes_nothing(self, slot):
        before = tree(slot)
        done = subprocess.run(["python3", SCRIPT, "show", str(slot)], capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
        assert "USES_ROOT_QUEUE=no" in done.stdout
        assert done.stdout.count("\nQUEUE=") == 3 and "wsp-a/.queue: 3 items" in done.stdout
        assert tree(slot) == before

    def test_adopt_is_a_dry_run_until_apply_is_given(self, slot):
        before = tree(slot)
        dry = subprocess.run(["python3", SCRIPT, "adopt", str(slot), f"from={slot / 'wsp-a'}"],
                             capture_output=True, text=True)
        assert "APPLIED=no" in dry.stdout and tree(slot) == before
        done = subprocess.run(["python3", SCRIPT, "adopt", str(slot), f"from={slot / 'wsp-a'}",
                               "--apply"], capture_output=True, text=True)
        assert "APPLIED=yes" in done.stdout, done.stdout + done.stderr
        assert queue_home.uses_root(slot)

    def test_a_refusal_exits_non_zero_with_the_reason(self, slot):
        done = subprocess.run(["python3", SCRIPT, "adopt", str(slot), "--apply"],
                              capture_output=True, text=True)
        assert done.returncode == 1 and "ERROR=choose_one" in done.stdout


class TestTheToolsFollowTheMarker:
    """read_queue and write_queue are what every tool calls (#577)."""

    def test_an_unmarked_slot_reads_each_workspace_clones_own_queue(self, slot):
        assert read_queue(slot / "wsp-a").active_item().ref == "o/r#3"
        assert read_queue(slot / "wsp-b").active_item().ref == "o/x#9"

    def test_a_marked_slot_reads_the_root_queue_from_anywhere_in_it(self, slot):
        queue_home.adopt(slot, source=slot / "wsp-a", apply=True)
        for where in (slot, slot / "wsp-a", slot / "wsp-b"):
            assert read_queue(where).active_item().ref == "o/r#3", where

    def test_a_write_from_a_workspace_clone_changes_only_the_root_queue(self, slot):
        queue_home.adopt(slot, source=slot / "wsp-a", apply=True)
        inherited = {n: (slot / n / ".queue").read_bytes() for n in ("wsp-a", "wsp-b")}
        current = read_queue(slot / "wsp-b")
        current.items.append(QueueItem(ref="o/r#50", title="New", completed=False, active=False))

        write_queue(slot / "wsp-b", current)

        assert [i.ref for i in read_queue(slot, exact=True).items][-1] == "o/r#50"
        assert {n: (slot / n / ".queue").read_bytes() for n in ("wsp-a", "wsp-b")} == inherited
        assert not list((slot / "wsp-b").glob(".queue.tmp"))

    def test_a_marked_slot_with_no_root_queue_has_no_queue(self, tmp_path):
        """The queue a workspace clone inherited from its repo is not this slot's work."""
        area = tmp_path / "slots" / "9"
        (area / "wsp").mkdir(parents=True)
        (area / ".slot").write_text("# Slot 9\n")
        (area / "wsp" / ".workspace").write_text("project: x\n")
        write_queue(area / "wsp", queue("o/r#1", active="o/r#1"))
        (area / "wsp" / ".plan").write_text("- [ ] O/r#7: Old\n\n## State\nstate: active\n")
        queue_home.mark(area)
        assert read_queue(area / "wsp") is None and read_queue(area) is None

    def test_the_first_write_in_a_marked_slot_creates_the_root_queue(self, tmp_path):
        area = tmp_path / "slots" / "9"
        (area / "wsp").mkdir(parents=True)
        (area / ".slot").write_text("# Slot 9\n")
        (area / "wsp" / ".workspace").write_text("project: x\n")
        queue_home.mark(area)
        write_queue(area / "wsp", queue("o/r#4", active="o/r#4"))
        assert (area / ".queue").is_file() and not (area / "wsp" / ".queue").exists()

    def test_show_after_the_switch_still_lists_each_clones_own_file(self, slot):
        queue_home.adopt(slot, source=slot / "wsp-a", apply=True)
        by_name = {c.directory.name: c for c in queue_home.candidates(slot)}
        assert by_name["wsp-b"].active == "o/x#9" and by_name["wsp-b"].items == 1
        assert by_name["7"].items == 3


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


class TestAWorkspaceKeepsItsQueueUntilItIsMovedOnPurpose:

    @pytest.fixture
    def workspace(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        _git(ws, "init", "-q", "-b", "main")
        (ws / "seed.txt").write_text("x")
        _git(ws, "add", ".")
        _git(ws, "commit", "-q", "-m", "init")
        return ws

    def test_a_notes_worktree_appearing_does_not_hide_an_existing_queue(self, workspace):
        from notes_store import NotesStore
        write_queue(workspace, queue("o/r#1", active="o/r#1"))
        _git(workspace, "add", ".queue")
        _git(workspace, "commit", "-q", "-m", "queue")
        NotesStore(workspace).ensure()

        assert read_queue(workspace).active_item().ref == "o/r#1"
        current = read_queue(workspace)
        current.items.append(QueueItem(ref="o/r#2", title="Two", completed=False, active=False))
        write_queue(workspace, current)

        assert not (workspace / ".notes" / ".queue").exists()
        assert len(read_queue(workspace, exact=True).items) == 2

    def test_an_older_plan_file_is_not_hidden_either(self, workspace):
        from notes_store import NotesStore
        (workspace / ".plan").write_text("- [ ] O/r#7: Old\n\n## State\nstate: active\n")
        NotesStore(workspace).ensure()
        assert read_queue(workspace) is not None

    def test_a_workspace_with_notes_and_no_queue_yet_starts_its_queue_in_notes(self, workspace):
        from notes_store import NotesStore
        NotesStore(workspace).ensure()
        write_queue(workspace, queue("o/r#1", active="o/r#1"))
        assert (workspace / ".notes" / ".queue").is_file()
        assert not (workspace / ".queue").exists()
        assert read_queue(workspace).active_item().ref == "o/r#1"

    def test_once_notes_holds_the_queue_a_stray_file_in_the_workspace_is_ignored(self, workspace):
        from notes_store import NotesStore
        NotesStore(workspace).ensure()
        write_queue(workspace, queue("o/r#1", active="o/r#1"))
        (workspace / ".queue").write_text("- [ ] O/z#99: Stray\n\n## State\nstatus: active\n")
        assert read_queue(workspace).active_item().ref == "o/r#1"
