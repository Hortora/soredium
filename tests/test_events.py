"""Tests for commands/events.py — serialisation roundtrips and field validation."""
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from commands.events import (
    StateChanged, BriefReady, BranchCreated, PlanAdvanced,
    CommandFailed, StepProgress, HealthCheck, Recommendation,
    WhatNextReady, HomeReady, RepoSlotInfo, StatusReady,
    ContinueReady, IssueContext, WipCommitted, Paused, Resumed,
    QuickFixLanded, WorkEnded, SessionStarted, SessionEnded,
    ContextSwitched,
)


def test_state_changed_roundtrip():
    event = StateChanged("idle", "active", ["brief", "next", "pause"], "next")
    d = asdict(event)
    d["type"] = "StateChanged"
    json_str = json.dumps(d)
    parsed = json.loads(json_str)
    assert parsed["type"] == "StateChanged"
    assert parsed["old_state"] == "idle"
    assert parsed["suggested_action"] == "next"


def test_command_failed_fields():
    event = CommandFailed("end", "promoted", "git_push_failed",
                          "Remote rejected push", True)
    d = asdict(event)
    assert d["recoverable"] is True
    assert d["step"] == "promoted"


def test_brief_ready_with_health():
    health = [HealthCheck("meta_consistency", "ok", None),
              HealthCheck("pause_stack", "warn", "2 stale entries")]
    event = BriefReady(42, "issue-42", "active", "1/3", health,
                       False, None, None)
    d = asdict(event)
    assert len(d["health"]) == 2
    assert d["health"][1]["status"] == "warn"


def test_what_next_typed_recommendations():
    recs = [Recommendation(55, "Refactor auth", "quick-win", "ready",
                           "Low risk, high value")]
    event = WhatNextReady(recs)
    d = asdict(event)
    assert d["recommendations"][0]["strategic_role"] == "quick-win"


def test_home_ready_multiple_repos():
    repos = [
        RepoSlotInfo("casehub/engine", None, "main", "idle", None,
                     None, None, "/path/engine", None),
        RepoSlotInfo("soredium", "slot/7", "issue-222", "active", 222,
                     "1/3", "soredium-slot7-222", "/path/soredium",
                     "/path/workspace"),
    ]
    event = HomeReady(repos)
    d = asdict(event)
    assert len(d["repos"]) == 2
    assert d["repos"][1]["tmux_session"] == "soredium-slot7-222"


def test_plan_advanced_queue_complete():
    event = PlanAdvanced(42, None, None, "3/3", True)
    assert event.queue_complete is True
    assert event.next_issue is None


def test_work_ended_multiple_issues():
    event = WorkEnded("issue-42", [42, 43, 44])
    d = asdict(event)
    assert len(d["issues_closed"]) == 3


def test_continue_ready_signals():
    event = ContinueReady(42, "issue-42", "active", "Last session summary",
                          done_detected=True, suggest_next=True,
                          suggest_end=False)
    assert event.done_detected is True
    assert event.suggest_next is True


def test_issue_context_for_session():
    ctx = IssueContext(42, "Fix scoring", "issue-42", "1/3",
                       "/path/project", "/path/workspace")
    d = asdict(ctx)
    assert d["issue"] == 42
    assert d["workspace_path"] == "/path/workspace"


def test_step_progress_serialisation():
    event = StepProgress("end", "rebased", None)
    d = asdict(event)
    d["type"] = "StepProgress"
    assert json.dumps(d)  # no exception


def test_status_ready_fields():
    event = StatusReady("issue-42", "active", False, True, True,
                        "1/3", 0, "Hortora/soredium", "main")
    assert event.in_slot is True
    assert event.base_branch == "main"


def test_context_switched():
    event = ContextSwitched("soredium", "slot/7", "/path/proj", "/path/ws")
    d = asdict(event)
    assert d["slot"] == "slot/7"


def test_session_events():
    started = SessionStarted("tmux", 42)
    ended = SessionEnded("tmux")
    assert started.provider == "tmux"
    assert ended.provider == "tmux"


def test_wip_committed():
    event = WipCommitted("/path/repo", "WIP: pause work")
    assert event.repo == "/path/repo"


def test_paused_with_depth():
    event = Paused("issue-42", 2)
    assert event.stack_depth == 2


def test_resumed():
    event = Resumed("issue-42", True)
    assert event.rebased is True


def test_quick_fix_landed():
    event = QuickFixLanded("qf-abc123", "fix: typo in config")
    assert event.branch == "qf-abc123"
