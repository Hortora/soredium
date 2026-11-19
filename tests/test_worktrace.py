"""Every lifecycle action is recorded in the worklog (Hortora/soredium#575)."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _d in ("project", "work-slot", "work-end", "scripts"):
    sys.path.insert(0, str(ROOT / _d))

import canonical_sync  # noqa: E402
import worklog  # noqa: E402
import worktrace  # noqa: E402
from tests.test_work_wrap_end import (  # noqa: E402
    BRANCH, answer, commit, drive_to_item_finished, g, run, with_remote, world)  # noqa: F401


def events(action: str = "") -> list[dict]:
    conn = worklog.connect()
    try:
        rows = conn.execute("SELECT event_type, repo_path, work_item_id, metadata FROM events "
                            "ORDER BY id").fetchall()
    finally:
        conn.close()
    found = [{**(json.loads(r["metadata"]) if r["metadata"] else {}),
              "action": r["event_type"], "repo": r["repo_path"] or "", "item": r["work_item_id"]}
             for r in rows]
    return [e for e in found if not action or e["action"] == action]


def items() -> list[dict]:
    conn = worklog.connect()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT wi.branch, wi.state, wi.ended_at, r.path FROM work_items wi "
            "JOIN repos r ON wi.repo_id = r.id ORDER BY wi.id")]
    finally:
        conn.close()


class TestRecorder:

    def test_an_action_is_written_with_its_details(self, tmp_path):
        assert worktrace.record("publish", repo=tmp_path, branch="main", pushed=3,
                                issue="Hortora/soredium#575")
        [event] = events("publish")
        assert event["pushed"] == 3 and event["branch"] == "main"
        assert event["issue"] == "Hortora/soredium#575"
        assert event["repo"] == str(tmp_path.resolve()) or event["repo"] == str(tmp_path)

    def test_a_database_that_cannot_be_written_never_fails_the_action(
            self, tmp_path, monkeypatch, capsys):
        blocked = tmp_path / "a-file"
        blocked.write_text("not a directory")
        monkeypatch.setenv("HORTORA_WORKLOG_DB", str(blocked / "worklog.db"))
        assert worktrace.record("land", repo=tmp_path) is False
        assert worktrace.work_started(tmp_path, "b", issue="o/r#1") is False
        assert worktrace.work_ended(tmp_path, "b") is False
        assert "WARN=worklog_not_recorded" in capsys.readouterr().err

    def test_paths_and_collections_are_stored_as_plain_values(self, tmp_path):
        worktrace.record("close-ceremony", repo=tmp_path, landed={"p": "abc"},
                         closed=["o/r#1"], where=tmp_path, empty=[])
        [event] = events("close-ceremony")
        assert event["landed"] == {"p": "abc"} and event["closed"] == ["o/r#1"]
        assert event["where"] == str(tmp_path) and "empty" not in event

    def test_a_detail_named_like_the_action_does_not_break_the_call(self, tmp_path):
        assert worktrace.record("work-end-stopped", repo=tmp_path, action="stop", reason="x")
        assert events("work-end-stopped")[0]["action"] == "work-end-stopped"

    def test_a_started_item_is_created_once_and_can_be_ended(self, tmp_path):
        worktrace.work_started(tmp_path, "issue-1-x", issue="o/r#1")
        worktrace.work_started(tmp_path, "issue-1-x", issue="o/r#1")
        assert [(i["branch"], i["state"]) for i in items()] == [("issue-1-x", "active")]
        worktrace.work_ended(tmp_path, "issue-1-x", "abc123")
        [item] = items()
        assert item["state"] == "ended" and item["ended_at"]

    def test_the_command_line_records_and_shows(self, tmp_path):
        script = str(ROOT / "project" / "worktrace.py")
        done = subprocess.run(["python3", script, "record", "action=diary", f"repo={tmp_path}",
                               "branch=issue-1-x", "entry=2026-11-19-x.md"],
                              capture_output=True, text=True)
        assert "RECORDED=yes" in done.stdout, done.stdout + done.stderr
        shown = subprocess.run(["python3", script, "show", "limit=5"],
                               capture_output=True, text=True).stdout
        assert "diary" in shown and "entry=2026-11-19-x.md" in shown


class TestLandAndPublish:

    def test_landing_and_publishing_are_each_recorded_once(self, tmp_path):
        repo, bare = with_remote(tmp_path, "project")
        g(repo, "checkout", "-q", "-b", "issue-3-y")
        commit(repo, "y.txt")
        canonical_sync.land(repo, "issue-3-y")
        [landed] = events("land")
        assert landed["branch"] == "issue-3-y" and landed["sha"] == g(repo, "rev-parse", "main")
        assert landed["unpublished"] == 1

        canonical_sync.publish_base(repo)
        [published] = events("publish")
        assert published["pushed"] == 1 and published["remote"] == "origin"
        assert published["sha"] == g(bare, "rev-parse", "refs/heads/main")

    def test_landing_again_records_nothing_new(self, tmp_path):
        repo, _ = with_remote(tmp_path, "project")
        g(repo, "checkout", "-q", "-b", "issue-3-y")
        commit(repo, "y.txt")
        canonical_sync.land(repo, "issue-3-y")
        canonical_sync.land(repo, "issue-3-y")
        assert len(events("land")) == 1

    def test_a_refused_publish_is_recorded_as_failed(self, tmp_path):
        repo, bare = with_remote(tmp_path, "project")
        commit(repo, "z.txt")
        g(repo, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
        with pytest.raises(canonical_sync.SyncError):
            canonical_sync.publish_base(repo)
        assert not events("publish")
        [failed] = events("publish-failed")
        assert failed["code"]


class TestWorkEndIsTraced:

    def _finish(self, world, command="end", finished="yes"):  # noqa: F811
        drive_to_item_finished(world, command)
        result = answer(world, command, "item_finished", f"finished={finished}")
        assert result["ACTION"] == "handoff", result["_raw"]
        result = answer(world, command, "handoff")
        assert result["ACTION"] == "complete", result["_raw"]

    def test_a_whole_work_end_leaves_every_action_in_the_worklog(self, world):  # noqa: F811
        worktrace.work_started(world["project"], BRANCH, issue="o/r#1")
        self._finish(world)
        seen = [e["action"] for e in events()]
        for action in ("work-end-begin", "step", "land", "stamp", "issue-close",
                       "close-ceremony", "publish", "work-end-complete"):
            assert action in seen, f"{action} missing from {seen}"
        steps = [(e["step"], e["outcome"]) for e in events("step") if e["command"] == "end"]
        assert [s for s, _ in steps] == [
            "review", "diary", "file_issues", "item_finished", "mark_done", "commit_queue",
            "land", "promote_backlog", "publish", "publish_blog", "handoff"]
        assert all(outcome == "completed" for _, outcome in steps)
        assert next(e for e in events("step") if e["step"] == "item_finished")["finished"] == "yes"
        assert {Path(e["repo"]).name for e in events("publish")} == {"project", "workspace"}
        assert events("issue-close")[0]["issue"] == "o/r#1"
        [ceremony] = events("close-ceremony")
        assert ceremony["success"] is True and ceremony["closed"] == ["o/r#1"]

    def test_the_work_item_is_ended_when_its_branch_is_closed(self, world):  # noqa: F811
        worktrace.work_started(world["project"], BRANCH, issue="o/r#1")
        self._finish(world)
        ended = [i for i in items() if i["branch"] == BRANCH and Path(i["path"]).name == "project"]
        assert ended and all(i["state"] == "ended" and i["ended_at"] for i in ended)

    def test_a_wrap_is_recorded_and_records_no_landing_or_publish(self, world):  # noqa: F811
        self._finish(world, command="wrap")
        seen = [e["action"] for e in events()]
        assert "work-wrap-begin" in seen and "work-wrap-complete" in seen
        assert not {"land", "publish", "stamp", "issue-close", "close-ceremony"} & set(seen)

    def test_a_command_that_stops_is_recorded_with_its_reason(self, world):  # noqa: F811
        g(world["workspace"], "checkout", "-q", "main")
        g(world["project"], "checkout", "-q", "main")
        result = run(world, "end")
        assert result["ACTION"] in ("stop", "decision"), result["_raw"]
        [stopped] = events("work-end-stopped")
        assert stopped["reason"]

    def test_a_failed_landing_is_recorded(self, world):  # noqa: F811
        (world["project"] / "code.txt").write_text("uncommitted change")
        drive_to_item_finished(world, "end")
        result = answer(world, "end", "item_finished", "finished=yes")
        assert result["ACTION"] == "error", result["_raw"]
        [stopped] = events("work-end-stopped")
        assert stopped["step"] == "land" and stopped["reason"]
        [ceremony] = events("close-ceremony")
        assert ceremony["success"] is False and ceremony["errors"]
        assert not events("publish") and not events("land")
