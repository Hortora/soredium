"""Queue items carry scale and complexity metadata (#586, #623)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "project"))
sys.path.insert(0, str(ROOT / "work-slot"))

from queue_io import Queue, QueueItem, QueueState, read_queue, write_queue  # noqa: E402
import plan_manager  # noqa: E402
from plan_manager import IssueRef  # noqa: E402

WORK = str(ROOT / "project" / "work.py")


class TestQueueItemScaleComplexity:

    def test_parse_item_with_scale_and_complexity(self, tmp_path):
        (tmp_path / ".queue").write_text(
            "- [ ] o/r#1 — First task (S/Med)        ← active\n"
            "- [ ] o/r#2 — Second task (M/High)\n"
            "- [ ] o/r#3 — No metadata\n\n"
            "## State\nbranch: issue-1-x\nissue-repo: O/r\nstatus: active\n"
        )
        queue = read_queue(tmp_path)
        assert queue is not None
        assert queue.items[0].scale == "S"
        assert queue.items[0].complexity == "Med"
        assert queue.items[1].scale == "M"
        assert queue.items[1].complexity == "High"
        assert queue.items[2].scale == ""
        assert queue.items[2].complexity == ""

    def test_parse_preserves_title_without_scale(self, tmp_path):
        (tmp_path / ".queue").write_text(
            "- [ ] o/r#1 — First task (S/Med)        ← active\n\n"
            "## State\nbranch: x\nissue-repo: O/r\nstatus: active\n"
        )
        queue = read_queue(tmp_path)
        assert queue.items[0].title == "First task"

    def test_write_then_read_preserves_scale_complexity(self, tmp_path):
        original = Queue(
            items=[
                QueueItem(ref="o/r#1", title="First", completed=False, active=True,
                          scale="S", complexity="Med"),
                QueueItem(ref="o/r#2", title="Second", completed=False, active=False),
            ],
            state=QueueState(branch="issue-1-x", issue_repo="O/r", status="active",
                             covers="o/r#1"))
        write_queue(tmp_path, original)
        reloaded = read_queue(tmp_path)
        assert reloaded.items[0].scale == "S"
        assert reloaded.items[0].complexity == "Med"
        assert reloaded.items[0].title == "First"
        assert reloaded.items[1].scale == ""
        assert reloaded.items[1].complexity == ""

    def test_title_with_parentheses_is_not_misread_as_scale(self, tmp_path):
        (tmp_path / ".queue").write_text(
            "- [ ] o/r#1 — Implement (REST/JSON) handler        ← active\n\n"
            "## State\nbranch: x\nissue-repo: O/r\nstatus: active\n"
        )
        queue = read_queue(tmp_path)
        assert queue.items[0].scale == ""
        assert queue.items[0].title == "Implement (REST/JSON) handler"

    def test_scale_and_from_main_coexist(self, tmp_path):
        original = Queue(
            items=[
                QueueItem(ref="o/r#1", title="Task", completed=False, active=True,
                          scale="L", complexity="High", from_main=True),
            ],
            state=QueueState(branch="x", issue_repo="O/r", status="active"))
        write_queue(tmp_path, original)
        reloaded = read_queue(tmp_path)
        assert reloaded.items[0].scale == "L"
        assert reloaded.items[0].complexity == "High"
        assert reloaded.items[0].from_main is True
        assert reloaded.items[0].title == "Task"


class TestSetScale:

    def test_set_scale_updates_item(self, tmp_path):
        write_queue(tmp_path, Queue(
            items=[
                QueueItem(ref="o/r#1", title="First", completed=False, active=True),
                QueueItem(ref="o/r#2", title="Second", completed=False, active=False),
            ],
            state=QueueState(branch="x", issue_repo="O/r", status="active")))
        result = subprocess.run(
            ["python3", str(ROOT / "work-slot" / "plan_manager.py"),
             "set-scale", str(tmp_path / ".queue"),
             "ref=o/r#1", "scale=S", "complexity=Med"],
            capture_output=True, text=True)
        assert result.returncode == 0, result.stderr + result.stdout
        reloaded = read_queue(tmp_path)
        assert reloaded.items[0].scale == "S"
        assert reloaded.items[0].complexity == "Med"
        assert reloaded.items[0].title == "First"

    def test_set_scale_clears_when_empty(self, tmp_path):
        write_queue(tmp_path, Queue(
            items=[QueueItem(ref="o/r#1", title="First", completed=False, active=True,
                             scale="S", complexity="Med")],
            state=QueueState(branch="x", issue_repo="O/r", status="active")))
        subprocess.run(
            ["python3", str(ROOT / "work-slot" / "plan_manager.py"),
             "set-scale", str(tmp_path / ".queue"),
             "ref=o/r#1", "scale=", "complexity="],
            capture_output=True, text=True, check=True)
        reloaded = read_queue(tmp_path)
        assert reloaded.items[0].scale == ""
        assert reloaded.items[0].complexity == ""

    def test_set_scale_on_missing_ref_fails(self, tmp_path):
        write_queue(tmp_path, Queue(
            items=[QueueItem(ref="o/r#1", title="First", completed=False, active=True)],
            state=QueueState(branch="x", issue_repo="O/r", status="active")))
        result = subprocess.run(
            ["python3", str(ROOT / "work-slot" / "plan_manager.py"),
             "set-scale", str(tmp_path / ".queue"),
             "ref=o/r#99", "scale=S", "complexity=Med"],
            capture_output=True, text=True)
        assert result.returncode == 1


class TestPipelineNextItemOutput:

    def _init_repo(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "-C", str(path), "init", "-q", "-b", "main", "--template="],
                       capture_output=True, check=True)
        (path / ".git" / "info").mkdir(parents=True, exist_ok=True)
        (path / "seed.txt").write_text("x")
        subprocess.run(["git", "-C", str(path), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "init"],
                       capture_output=True)

    def test_offer_includes_next_item_metadata(self, tmp_path):
        """After mark_done, #1 is done on branch, #2 is active, #3 is next open.
        OFFER should carry #3's metadata."""
        self._init_repo(tmp_path / "project")
        project = tmp_path / "project"
        write_queue(project, Queue(
            items=[
                QueueItem(ref="o/r#1", title="Done task", completed=False, active=False,
                          done_branch="issue-1-x"),
                QueueItem(ref="o/r#2", title="Active task", completed=False, active=True),
                QueueItem(ref="o/r#3", title="Next task", completed=False, active=False,
                          scale="M", complexity="High"),
            ],
            state=QueueState(branch="main", issue_repo="O/r", status="active",
                             covers="o/r#2")))
        subprocess.run(["git", "-C", str(project), "add", ".queue"], capture_output=True)
        subprocess.run(["git", "-C", str(project), "commit", "-q", "-m", "queue"],
                       capture_output=True)
        result = subprocess.run(
            ["python3", WORK, "done",
             f"workspace={project}", f"project={project}",
             "branch=main", "base_branch=main", "on_main=yes",
             f"plan_path={project / '.queue'}", "issue_repo=O/r"],
            capture_output=True, text=True, cwd=str(project))
        out = dict(l.split("=", 1) for l in result.stdout.splitlines() if "=" in l)
        assert out.get("OFFER") == "wrap_or_continue", result.stdout
        assert out.get("NEXT_SCALE") == "M"
        assert out.get("NEXT_COMPLEXITY") == "High"
        assert "o/r#3" in out.get("NEXT_ITEM", "")
        assert out.get("DONE_WAITING") == "1"

    def test_offer_without_next_open_item_omits_next_lines(self, tmp_path):
        """When only the active item remains after the done one, no NEXT_ITEM."""
        self._init_repo(tmp_path / "project")
        project = tmp_path / "project"
        write_queue(project, Queue(
            items=[
                QueueItem(ref="o/r#1", title="Done task", completed=False, active=False,
                          done_branch="issue-1-x"),
                QueueItem(ref="o/r#2", title="Active task", completed=False, active=True),
            ],
            state=QueueState(branch="", issue_repo="O/r", status="active",
                             covers="o/r#2")))
        subprocess.run(["git", "-C", str(project), "add", ".queue"], capture_output=True)
        subprocess.run(["git", "-C", str(project), "commit", "-q", "-m", "queue"],
                       capture_output=True)
        result = subprocess.run(
            ["python3", WORK, "continue",
             f"workspace={project}", f"project={project}",
             "branch=main", "base_branch=main", "on_main=yes",
             f"plan_path={project / '.queue'}", "issue_repo=O/r"],
            capture_output=True, text=True, cwd=str(project))
        out = dict(l.split("=", 1) for l in result.stdout.splitlines() if "=" in l)
        assert "NEXT_ITEM" not in out
        assert out.get("DONE_WAITING") == "1"


class TestEndSummaryNextItem:
    """Refs #639: end summary must report the active item as NEXT_ITEM,
    not skip it to show the item after it."""

    def test_active_item_reported_as_next(self):
        """When the queue has an active-but-unstarted item, the end summary
        should report it, not skip over it."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "project"))
        from queue_io import Queue, QueueItem, QueueState

        q = Queue(
            items=[
                QueueItem(ref="o/r#1", title="Done", completed=True, active=False),
                QueueItem(ref="o/r#618", title="Active unstarted", completed=False, active=True),
                QueueItem(ref="o/r#623", title="After active", completed=False, active=False),
            ],
            state=QueueState(branch="", issue_repo="O/r", status="active"))

        _active = q.active_item()
        _next = _active or next((i for i in q.items
                                 if not i.completed and not i.done_branch), None)

        assert _next is not None
        assert _next.ref == "o/r#618", f"expected active item, got {_next.ref}"


PLAN_WITH_SCALE = """\
# Work Plan —

## State
branch: issue-1-x
issue-repo: O/r
status: active
covers: o/r#1

## Queue
- [ ] o/r#1 — First task (S/Med) ← active
- [ ] o/r#2 — Second task (M/High)
- [ ] o/r#3 — No metadata
"""

PLAN_SCALE_FROM_MAIN = """\
# Work Plan —

## State
branch: issue-1-x
issue-repo: O/r
status: active
covers: o/r#1

## Queue
- [ ] o/r#1 — Task (L/High) (from main) ← active
"""


class TestPlanManagerScaleComplexity:

    def test_parse_items_with_scale(self, tmp_path):
        plan_file = tmp_path / ".plan"
        plan_file.write_text(PLAN_WITH_SCALE)
        tree = plan_manager.parse_plan(plan_file)
        assert tree.queue[0].scale == "S"
        assert tree.queue[0].complexity == "Med"
        assert tree.queue[0].title == "First task"
        assert tree.queue[1].scale == "M"
        assert tree.queue[1].complexity == "High"
        assert tree.queue[2].scale == ""
        assert tree.queue[2].complexity == ""

    def test_write_item_renders_scale(self, tmp_path):
        plan_file = tmp_path / ".plan"
        plan_file.write_text(PLAN_WITH_SCALE)
        tree = plan_manager.parse_plan(plan_file)
        plan_manager.rewrite_plan(plan_file, tree)
        content = plan_file.read_text()
        assert "(S/Med)" in content
        assert "(M/High)" in content
        assert "No metadata" in content
        assert "No metadata (" not in content

    def test_roundtrip_preserves_scale(self, tmp_path):
        plan_file = tmp_path / ".plan"
        plan_file.write_text(PLAN_WITH_SCALE)
        tree = plan_manager.parse_plan(plan_file)
        plan_manager.rewrite_plan(plan_file, tree)
        tree2 = plan_manager.parse_plan(plan_file)
        assert tree2.queue[0].scale == "S"
        assert tree2.queue[0].complexity == "Med"
        assert tree2.queue[0].title == "First task"
        assert tree2.queue[1].scale == "M"
        assert tree2.queue[1].complexity == "High"

    def test_scale_and_from_main_coexist(self, tmp_path):
        plan_file = tmp_path / ".plan"
        plan_file.write_text(PLAN_SCALE_FROM_MAIN)
        tree = plan_manager.parse_plan(plan_file)
        item = tree.queue[0]
        assert item.scale == "L"
        assert item.complexity == "High"
        assert item.from_main is True
        assert item.title == "Task"

    def test_parentheses_in_title_not_misread(self, tmp_path):
        plan_file = tmp_path / ".plan"
        plan_file.write_text(
            "# Work Plan —\n\n## State\nbranch: x\nissue-repo: O/r\n"
            "status: active\ncovers: o/r#1\n\n## Queue\n"
            "- [ ] o/r#1 — Implement (REST/JSON) handler ← active\n"
        )
        tree = plan_manager.parse_plan(plan_file)
        assert tree.queue[0].scale == ""
        assert tree.queue[0].title == "Implement (REST/JSON) handler"

    def test_build_plan_content_includes_scale(self):
        items = [plan_manager.QueueItem(
            ref=IssueRef("o/r", 1), title="Fix login",
            active=True, scale="S", complexity="Low")]
        content = plan_manager.build_plan_content("issue-1-fix-login", items, "2026-01-01")
        assert "(S/Low)" in content

    def test_append_populates_scale_from_labels(self, tmp_path, monkeypatch):
        plan_file = tmp_path / ".plan"
        plan_file.write_text(
            "# Work Plan —\n\n## State\nbranch: x\nissue-repo: O/r\n"
            "status: active\n\n## Queue\n"
        )
        monkeypatch.setattr(
            "plan_manager._fetch_issue_scale",
            lambda repo, num: ("XS", "Low"))
        monkeypatch.setattr(
            "plan_manager._check_issue_state",
            lambda repo, num: "OPEN")
        items = [plan_manager.QueueItem(
            ref=IssueRef("o/r", 42), title="New feature")]
        plan_manager.append_to_queue(plan_file, items)
        tree = plan_manager.parse_plan(plan_file)
        assert tree.queue[0].scale == "XS"
        assert tree.queue[0].complexity == "Low"

    def test_append_does_not_overwrite_explicit_scale(self, tmp_path, monkeypatch):
        plan_file = tmp_path / ".plan"
        plan_file.write_text(
            "# Work Plan —\n\n## State\nbranch: x\nissue-repo: O/r\n"
            "status: active\n\n## Queue\n"
        )
        monkeypatch.setattr(
            "plan_manager._fetch_issue_scale",
            lambda repo, num: ("M", "High"))
        monkeypatch.setattr(
            "plan_manager._check_issue_state",
            lambda repo, num: "OPEN")
        items = [plan_manager.QueueItem(
            ref=IssueRef("o/r", 42), title="Task",
            scale="S", complexity="Low")]
        plan_manager.append_to_queue(plan_file, items)
        tree = plan_manager.parse_plan(plan_file)
        assert tree.queue[0].scale == "S"
        assert tree.queue[0].complexity == "Low"


class TestFetchIssueScale:

    def test_parses_scale_and_complexity_labels(self, monkeypatch):
        monkeypatch.setattr("subprocess.run", lambda *a, **kw: type(
            "R", (), {"returncode": 0, "stdout": "scale: S\ncomplexity: Low\nenhancement\n"})())
        assert plan_manager._fetch_issue_scale("o/r", 1) == ("S", "Low")

    def test_returns_empty_on_no_labels(self, monkeypatch):
        monkeypatch.setattr("subprocess.run", lambda *a, **kw: type(
            "R", (), {"returncode": 0, "stdout": "enhancement\nbug\n"})())
        assert plan_manager._fetch_issue_scale("o/r", 1) == ("", "")

    def test_returns_empty_on_failure(self, monkeypatch):
        monkeypatch.setattr("subprocess.run", lambda *a, **kw: type(
            "R", (), {"returncode": 1, "stdout": ""})())
        assert plan_manager._fetch_issue_scale("o/r", 1) == ("", "")

    def test_normalizes_case(self, monkeypatch):
        monkeypatch.setattr("subprocess.run", lambda *a, **kw: type(
            "R", (), {"returncode": 0, "stdout": "scale: xs\ncomplexity: high\n"})())
        assert plan_manager._fetch_issue_scale("o/r", 1) == ("XS", "High")
