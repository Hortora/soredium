#!/usr/bin/env python3
"""plan_manager defer-active and move-down commands (#596)."""
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PLAN_MANAGER = Path(__file__).resolve().parent.parent / "work-slot" / "plan_manager.py"
sys.path.insert(0, str(PLAN_MANAGER.parent))

import plan_manager  # noqa: E402


def run_pm(tmp_path, command, **opts):
    queue_file = tmp_path / ".queue"
    args = ["python3", str(PLAN_MANAGER), command, str(queue_file)]
    for k, v in opts.items():
        args.append(f"{k}={v}")
    return subprocess.run(args, capture_output=True, text=True)


def write_queue(tmp_path, content):
    (tmp_path / ".queue").write_text(textwrap.dedent(content))


class TestDeferActive:
    def test_moves_active_to_deferred_section(self, tmp_path):
        write_queue(tmp_path, """\
            ## State
            branch: issue-1-x
            issue-repo: o/r
            covers: o/r#1

            ## Queue
            - [ ] o/r#1 — first item ← active
            - [ ] o/r#2 — second item
        """)
        result = run_pm(tmp_path, "defer-active", reason="not ready yet")
        assert result.returncode == 0
        assert "DEFERRED=o/r#1" in result.stdout
        content = (tmp_path / ".queue").read_text()
        assert "not ready yet" in content
        assert "o/r#2" in content
        # item 1 should not be in the queue section as an active item
        lines = [l for l in content.splitlines() if "← active" in l]
        if lines:
            assert "o/r#2" in lines[0]

    def test_activates_next_item(self, tmp_path):
        write_queue(tmp_path, """\
            ## State
            branch: issue-1-x
            issue-repo: o/r
            covers: o/r#1

            ## Queue
            - [ ] o/r#1 — first item ← active
            - [ ] o/r#2 — second item
            - [ ] o/r#3 — third item
        """)
        result = run_pm(tmp_path, "defer-active", reason="skip")
        assert result.returncode == 0
        assert "NEXT=o/r#2" in result.stdout

    def test_clears_state_branch(self, tmp_path):
        write_queue(tmp_path, """\
            ## State
            branch: issue-1-x
            issue-repo: o/r
            covers: o/r#1

            ## Queue
            - [ ] o/r#1 — first item ← active
            - [ ] o/r#2 — second item
        """)
        run_pm(tmp_path, "defer-active", reason="skip")
        content = (tmp_path / ".queue").read_text()
        # branch should be cleared
        for line in content.splitlines():
            if line.startswith("branch:"):
                assert line.strip() == "branch:" or "issue-1-x" not in line

    def test_fails_with_no_active_item(self, tmp_path):
        write_queue(tmp_path, """\
            ## State
            issue-repo: o/r

            ## Queue
            - [ ] o/r#1 — first item
            - [ ] o/r#2 — second item
        """)
        result = run_pm(tmp_path, "defer-active", reason="skip")
        assert result.returncode != 0

    def test_last_item_deferred_leaves_empty_queue(self, tmp_path):
        write_queue(tmp_path, """\
            ## State
            branch: issue-1-x
            issue-repo: o/r
            covers: o/r#1

            ## Queue
            - [ ] o/r#1 — only item ← active
        """)
        result = run_pm(tmp_path, "defer-active", reason="skip")
        assert result.returncode == 0
        assert "NEXT=" in result.stdout  # should be empty or None


class TestMoveDown:
    def test_moves_active_to_end(self, tmp_path):
        write_queue(tmp_path, """\
            ## State
            branch: issue-1-x
            issue-repo: o/r
            covers: o/r#1

            ## Queue
            - [ ] o/r#1 — first item ← active
            - [ ] o/r#2 — second item
            - [ ] o/r#3 — third item
        """)
        result = run_pm(tmp_path, "move-down", position="end")
        assert result.returncode == 0
        assert "MOVED=o/r#1" in result.stdout
        content = (tmp_path / ".queue").read_text()
        queue_lines = [l for l in content.splitlines() if l.strip().startswith("- [ ]")]
        refs = [l.split("—")[0].strip() for l in queue_lines]
        # item 1 should be last
        assert "o/r#1" in refs[-1]
        # item 2 should be first (and active)
        assert "o/r#2" in refs[0]

    def test_activates_next_item(self, tmp_path):
        write_queue(tmp_path, """\
            ## State
            branch: issue-1-x
            issue-repo: o/r
            covers: o/r#1

            ## Queue
            - [ ] o/r#1 — first item ← active
            - [ ] o/r#2 — second item
        """)
        result = run_pm(tmp_path, "move-down", position="end")
        assert result.returncode == 0
        assert "NEXT=o/r#2" in result.stdout

    def test_clears_state_branch(self, tmp_path):
        write_queue(tmp_path, """\
            ## State
            branch: issue-1-x
            issue-repo: o/r
            covers: o/r#1

            ## Queue
            - [ ] o/r#1 — first item ← active
            - [ ] o/r#2 — second item
        """)
        run_pm(tmp_path, "move-down", position="end")
        content = (tmp_path / ".queue").read_text()
        for line in content.splitlines():
            if line.startswith("branch:"):
                assert "issue-1-x" not in line

    def test_fails_with_no_active_item(self, tmp_path):
        write_queue(tmp_path, """\
            ## State
            issue-repo: o/r

            ## Queue
            - [ ] o/r#1 — first item
            - [ ] o/r#2 — second item
        """)
        result = run_pm(tmp_path, "move-down", position="end")
        assert result.returncode != 0

    def test_single_item_stays_in_place(self, tmp_path):
        write_queue(tmp_path, """\
            ## State
            branch: issue-1-x
            issue-repo: o/r
            covers: o/r#1

            ## Queue
            - [ ] o/r#1 — only item ← active
        """)
        result = run_pm(tmp_path, "move-down", position="end")
        assert result.returncode == 0
        content = (tmp_path / ".queue").read_text()
        assert "o/r#1" in content
