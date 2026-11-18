#!/usr/bin/env python3
"""plan_manager.py activate: make an open item active when none is (#548)."""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "work-slot"))
sys.path.insert(0, str(ROOT / "project"))

import plan_manager  # noqa: E402

PLAN_MANAGER = ROOT / "work-slot" / "plan_manager.py"

NONE_ACTIVE = """# Work Plan —

## State
branch:
status: drained
issue-repo: o/r

## Queue
- [x] o/r#1 — first
- [ ] o/r#2 — second ← done on issue-2-second
- [ ] o/r#3 — third
- [ ] o/r#4 — fourth
"""

ONE_ACTIVE = NONE_ACTIVE.replace("- [ ] o/r#3 — third", "- [ ] o/r#3 — third ← active")


def write(tmp_path, text):
    (tmp_path / ".queue").write_text(text)
    return tmp_path / ".queue"


def run(*args):
    return subprocess.run([sys.executable, str(PLAN_MANAGER), *args],
                          capture_output=True, text=True)


def leaves(queue):
    return {str(l.ref): l for l in plan_manager.flatten_leaves(plan_manager.parse_plan(queue))}


class TestActivate:
    def test_no_ref_activates_first_open_item(self, tmp_path):
        q = write(tmp_path, NONE_ACTIVE)
        r = run("activate", str(q))
        assert r.returncode == 0, r.stdout + r.stderr
        assert "ACTIVATED=o/r#3" in r.stdout
        assert "ALREADY_ACTIVE=no" in r.stdout
        found = leaves(q)
        assert found["o/r#3"].active
        assert not found["o/r#4"].active

    def test_ref_activates_that_item_not_the_first(self, tmp_path):
        q = write(tmp_path, NONE_ACTIVE)
        r = run("activate", str(q), "ref=o/r#4")
        assert r.returncode == 0, r.stdout + r.stderr
        found = leaves(q)
        assert found["o/r#4"].active
        assert not found["o/r#3"].active

    def test_state_follows_the_activated_item(self, tmp_path):
        q = write(tmp_path, NONE_ACTIVE)
        run("activate", str(q), "ref=o/r#4")
        state = plan_manager.parse_plan(q).state
        assert state["covers"] == "o/r#4"
        assert state["status"] == "active"

    def test_done_and_closed_items_survive(self, tmp_path):
        q = write(tmp_path, NONE_ACTIVE)
        run("activate", str(q))
        found = leaves(q)
        assert found["o/r#1"].completed
        assert found["o/r#2"].done_branch == "issue-2-second"
        assert not found["o/r#2"].active

    def test_closed_item_is_refused(self, tmp_path):
        q = write(tmp_path, NONE_ACTIVE)
        before = q.read_text()
        r = run("activate", str(q), "ref=o/r#1")
        assert r.returncode == 1
        assert "ERROR=not_open" in r.stdout
        assert q.read_text() == before

    def test_done_item_is_refused(self, tmp_path):
        q = write(tmp_path, NONE_ACTIVE)
        before = q.read_text()
        r = run("activate", str(q), "ref=o/r#2")
        assert r.returncode == 1
        assert "ERROR=not_open" in r.stdout
        assert q.read_text() == before

    def test_unknown_item_is_refused(self, tmp_path):
        q = write(tmp_path, NONE_ACTIVE)
        r = run("activate", str(q), "ref=o/r#99")
        assert r.returncode == 1
        assert "ERROR=not_in_queue" in r.stdout

    def test_never_displaces_an_active_item(self, tmp_path):
        q = write(tmp_path, ONE_ACTIVE)
        before = q.read_text()
        r = run("activate", str(q), "ref=o/r#4")
        assert r.returncode == 1
        assert "ERROR=another_item_active" in r.stdout
        assert q.read_text() == before

    def test_activating_the_active_item_changes_nothing(self, tmp_path):
        q = write(tmp_path, ONE_ACTIVE)
        before = q.read_text()
        r = run("activate", str(q), "ref=o/r#3")
        assert r.returncode == 0
        assert "ALREADY_ACTIVE=yes" in r.stdout
        assert q.read_text() == before

    def test_nothing_open_is_refused(self, tmp_path):
        q = write(tmp_path, NONE_ACTIVE.replace("- [ ] o/r#3", "- [x] o/r#3")
                  .replace("- [ ] o/r#4", "- [x] o/r#4"))
        r = run("activate", str(q))
        assert r.returncode == 1
        assert "ERROR=no_open_item" in r.stdout

    def test_malformed_ref_is_refused(self, tmp_path):
        q = write(tmp_path, NONE_ACTIVE)
        r = run("activate", str(q), "ref=289")
        assert r.returncode == 1
        assert "ERROR=invalid_ref" in r.stdout
