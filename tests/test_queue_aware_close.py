"""Tests for queue-aware close-issues — only close completed queue items (#453)."""
import sys
from pathlib import Path

import pytest

_project_dir = str(Path(__file__).resolve().parent.parent / "project")
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)
_workend_dir = str(Path(__file__).resolve().parent.parent / "work-end")
if _workend_dir not in sys.path:
    sys.path.insert(0, _workend_dir)
_slot_dir = str(Path(__file__).resolve().parent.parent / "work-slot")
if _slot_dir not in sys.path:
    sys.path.insert(0, _slot_dir)


def _write_plan(ws, items):
    """Write a .plan with queue items. items: list of (number, title, completed, active)."""
    lines = ["# Work Plan — test\n", "## State",
             "branch: issue-test", "state: closing:review",
             "issue-repo: Hortora/soredium", f"covers: {','.join(str(i[0]) for i in items)}",
             "", "## Queue"]
    for num, title, completed, active in items:
        check = "x" if completed else " "
        marker = " ← active" if active else ""
        lines.append(f"- [{check}] hortora/soredium#{num} — {title}{marker}")
    (ws / ".plan").write_text("\n".join(lines) + "\n")


def test_close_issues_only_completed(tmp_path):
    """Only issues marked [x] in the queue should be closed."""
    from work_end_orchestrator import _close_issues_script, OrchestratorContext
    from progress import Progress

    _write_plan(tmp_path, [
        (449, "Phase 1", True, False),
        (450, "Phase 2", False, True),
        (451, "Phase 3", False, False),
    ])

    ctx = OrchestratorContext(
        workspace=tmp_path, project=tmp_path,
        branch="issue-test", base_branch="main",
        meta_state="closing:stamped", on_main=False,
        in_slot=False, covers="449,450,451",
        issue_repo="Hortora/soredium",
        progress=Progress(),
        plan_path=tmp_path / ".plan",
    )

    cmd = _close_issues_script(ctx)
    covers_arg = [a for a in cmd if a.startswith("covers=")][0]
    covers_value = covers_arg.split("=", 1)[1]
    issue_nums = {int(n) for n in covers_value.split(",") if n.strip()}

    assert 449 in issue_nums, "Completed issue #449 should be closed"
    assert 450 in issue_nums, "Active issue #450 should be closed (being completed now)"
    assert 451 not in issue_nums, "Uncompleted issue #451 should NOT be closed"


def test_close_issues_all_completed(tmp_path):
    """When all issues are completed, close all."""
    from work_end_orchestrator import _close_issues_script, OrchestratorContext
    from progress import Progress

    _write_plan(tmp_path, [
        (449, "Phase 1", True, False),
        (450, "Phase 2", True, True),
    ])

    ctx = OrchestratorContext(
        workspace=tmp_path, project=tmp_path,
        branch="issue-test", base_branch="main",
        meta_state="closing:stamped", on_main=False,
        in_slot=False, covers="449,450",
        issue_repo="Hortora/soredium",
        progress=Progress(),
        plan_path=tmp_path / ".plan",
    )

    cmd = _close_issues_script(ctx)
    covers_arg = [a for a in cmd if a.startswith("covers=")][0]
    covers_value = covers_arg.split("=", 1)[1]
    issue_nums = {int(n) for n in covers_value.split(",") if n.strip()}

    assert 449 in issue_nums
    assert 450 in issue_nums


def test_close_issues_no_plan_closes_all(tmp_path):
    """Without a .plan, fall back to closing all covers (backward compat)."""
    from work_end_orchestrator import _close_issues_script, OrchestratorContext
    from progress import Progress

    ctx = OrchestratorContext(
        workspace=tmp_path, project=tmp_path,
        branch="issue-test", base_branch="main",
        meta_state="closing:stamped", on_main=False,
        in_slot=False, covers="449,450,451",
        issue_repo="Hortora/soredium",
        progress=Progress(),
        plan_path=tmp_path / ".plan",
    )

    cmd = _close_issues_script(ctx)
    covers_arg = [a for a in cmd if a.startswith("covers=")][0]
    covers_value = covers_arg.split("=", 1)[1]
    issue_nums = {int(n) for n in covers_value.split(",") if n.strip()}

    assert issue_nums == {449, 450, 451}
