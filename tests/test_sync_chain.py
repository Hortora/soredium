"""Tests for sync command evaluation in work_chain.py."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "project"))

from work_chain import evaluate


class TestSyncEvaluation:
    def test_sync_proceeds_when_active_with_work(self):
        ctx = {
            "META_STATE": "active",
            "HAS_PLAN": "yes",
            "ACTIVE_ISSUE": "test/repo#1",
            "PLAN_POSITION": "0/3",
            "ON_MAIN": "no",
        }
        result = evaluate("sync", ctx, issue_state="OPEN")
        assert result["DIRECTIVE"] == "proceed"

    def test_sync_blocked_on_main(self):
        ctx = {
            "META_STATE": "active",
            "HAS_PLAN": "yes",
            "ACTIVE_ISSUE": "test/repo#1",
            "PLAN_POSITION": "0/1",
            "ON_MAIN": "yes",
        }
        result = evaluate("sync", ctx)
        assert result["DIRECTIVE"] != "proceed"

    def test_sync_blocked_when_no_active_issue(self):
        ctx = {
            "META_STATE": "active",
            "HAS_PLAN": "no",
            "ACTIVE_ISSUE": "",
            "PLAN_POSITION": "",
            "ON_MAIN": "no",
        }
        result = evaluate("sync", ctx)
        assert result["DIRECTIVE"] != "proceed"

    def test_sync_blocked_when_drained(self):
        ctx = {
            "META_STATE": "drained",
            "HAS_PLAN": "yes",
            "ACTIVE_ISSUE": "",
            "PLAN_POSITION": "",
            "ON_MAIN": "no",
        }
        result = evaluate("sync", ctx)
        assert result["DIRECTIVE"] != "proceed"

    def test_sync_blocked_when_paused(self):
        ctx = {
            "META_STATE": "paused",
            "HAS_PLAN": "yes",
            "ACTIVE_ISSUE": "test/repo#1",
            "PLAN_POSITION": "0/1",
            "ON_MAIN": "no",
        }
        result = evaluate("sync", ctx)
        assert result["DIRECTIVE"] != "proceed"

    def test_sync_includes_base_fields(self):
        ctx = {
            "META_STATE": "active",
            "HAS_PLAN": "yes",
            "ACTIVE_ISSUE": "test/repo#1",
            "PLAN_POSITION": "0/3",
            "ON_MAIN": "no",
        }
        result = evaluate("sync", ctx, issue_state="OPEN")
        assert "ACTIVE_ISSUE" in result
        assert "ON_MAIN" in result
        assert "QUEUE_REMAINING" in result
