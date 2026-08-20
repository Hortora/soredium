#!/usr/bin/env python3
"""Tests for project/work_chain.py — bidirectional chaining directives."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "project"))
from work_chain import evaluate


# --- evaluate_continue ---


class TestEvaluateContinue:
    def test_active_open_issue_proceeds(self):
        ctx = {
            "META_STATE": "active",
            "HAS_PLAN": "yes",
            "ACTIVE_ISSUE": "42",
            "PLAN_POSITION": "0/3",
            "ON_MAIN": "no",
        }
        result = evaluate("continue", ctx, issue_state="OPEN")
        assert result["DIRECTIVE"] == "proceed"

    def test_active_closed_issue_chains_to_next(self):
        ctx = {
            "META_STATE": "active",
            "HAS_PLAN": "yes",
            "ACTIVE_ISSUE": "42",
            "PLAN_POSITION": "1/3",
            "ON_MAIN": "no",
        }
        result = evaluate("continue", ctx, issue_state="CLOSED")
        assert result["DIRECTIVE"] == "chain_to_next"
        assert result["REASON"] == "active_issue_done"

    def test_no_plan_chains_to_next(self):
        ctx = {
            "META_STATE": "",
            "HAS_PLAN": "no",
            "ACTIVE_ISSUE": "",
            "PLAN_POSITION": "",
            "ON_MAIN": "yes",
        }
        result = evaluate("continue", ctx)
        assert result["DIRECTIVE"] == "chain_to_next"
        assert result["REASON"] == "no_active_work"

    def test_drained_state_chains_to_next(self):
        ctx = {
            "META_STATE": "drained",
            "HAS_PLAN": "yes",
            "ACTIVE_ISSUE": "",
            "PLAN_POSITION": "3/3",
            "ON_MAIN": "yes",
        }
        result = evaluate("continue", ctx)
        assert result["DIRECTIVE"] == "chain_to_next"
        assert result["REASON"] == "queue_drained"

    def test_no_active_issue_chains_to_next(self):
        ctx = {
            "META_STATE": "active",
            "HAS_PLAN": "yes",
            "ACTIVE_ISSUE": "",
            "PLAN_POSITION": "3/3",
            "ON_MAIN": "no",
        }
        result = evaluate("continue", ctx)
        assert result["DIRECTIVE"] == "chain_to_next"
        assert result["REASON"] == "no_active_work"

    def test_unknown_issue_state_proceeds(self):
        ctx = {
            "META_STATE": "active",
            "HAS_PLAN": "yes",
            "ACTIVE_ISSUE": "42",
            "PLAN_POSITION": "0/3",
            "ON_MAIN": "no",
        }
        result = evaluate("continue", ctx, issue_state="UNKNOWN")
        assert result["DIRECTIVE"] == "proceed"


# --- evaluate_next ---


class TestEvaluateNext:
    def test_open_issue_guards_back_to_continue(self):
        ctx = {
            "META_STATE": "active",
            "HAS_PLAN": "yes",
            "ACTIVE_ISSUE": "42",
            "PLAN_POSITION": "0/3",
            "ON_MAIN": "no",
        }
        result = evaluate("next", ctx, issue_state="OPEN")
        assert result["DIRECTIVE"] == "guard_continue"
        assert result["REASON"] == "issue_still_open"
        assert result["ACTIVE_ISSUE"] == "42"

    def test_closed_issue_proceeds(self):
        ctx = {
            "META_STATE": "active",
            "HAS_PLAN": "yes",
            "ACTIVE_ISSUE": "42",
            "PLAN_POSITION": "1/3",
            "ON_MAIN": "no",
        }
        result = evaluate("next", ctx, issue_state="CLOSED")
        assert result["DIRECTIVE"] == "proceed"

    def test_empty_queue_chains_to_end(self):
        ctx = {
            "META_STATE": "active",
            "HAS_PLAN": "yes",
            "ACTIVE_ISSUE": "",
            "PLAN_POSITION": "3/3",
            "ON_MAIN": "no",
        }
        result = evaluate("next", ctx)
        assert result["DIRECTIVE"] == "chain_to_end"
        assert result["REASON"] == "queue_empty"

    def test_no_plan_chains_to_end(self):
        ctx = {
            "META_STATE": "active",
            "HAS_PLAN": "no",
            "ACTIVE_ISSUE": "",
            "PLAN_POSITION": "",
            "ON_MAIN": "no",
        }
        result = evaluate("next", ctx)
        assert result["DIRECTIVE"] == "chain_to_end"
        assert result["REASON"] == "no_plan"


# --- evaluate_end ---


class TestEvaluateEnd:
    def test_remaining_queue_with_open_issue_guards_back(self):
        ctx = {
            "META_STATE": "active",
            "HAS_PLAN": "yes",
            "ACTIVE_ISSUE": "42",
            "PLAN_POSITION": "1/3",
            "ON_MAIN": "no",
        }
        result = evaluate("end", ctx, issue_state="OPEN")
        assert result["DIRECTIVE"] == "guard_next"
        assert result["REASON"] == "queue_not_empty"

    def test_empty_queue_proceeds(self):
        ctx = {
            "META_STATE": "active",
            "HAS_PLAN": "yes",
            "ACTIVE_ISSUE": "",
            "PLAN_POSITION": "3/3",
            "ON_MAIN": "no",
        }
        result = evaluate("end", ctx)
        assert result["DIRECTIVE"] == "proceed"

    def test_no_plan_proceeds(self):
        ctx = {
            "META_STATE": "active",
            "HAS_PLAN": "no",
            "ACTIVE_ISSUE": "",
            "PLAN_POSITION": "",
            "ON_MAIN": "no",
        }
        result = evaluate("end", ctx)
        assert result["DIRECTIVE"] == "proceed"

    def test_all_issues_closed_proceeds(self):
        ctx = {
            "META_STATE": "active",
            "HAS_PLAN": "yes",
            "ACTIVE_ISSUE": "42",
            "PLAN_POSITION": "2/3",
            "ON_MAIN": "no",
        }
        result = evaluate("end", ctx, issue_state="CLOSED")
        assert result["DIRECTIVE"] == "proceed"


# --- evaluate_find ---


class TestEvaluateFind:
    def test_active_open_work_guards_back(self):
        ctx = {
            "META_STATE": "active",
            "HAS_PLAN": "yes",
            "ACTIVE_ISSUE": "42",
            "PLAN_POSITION": "0/3",
            "ON_MAIN": "no",
        }
        result = evaluate("find", ctx, issue_state="OPEN")
        assert result["DIRECTIVE"] == "guard_next"
        assert result["REASON"] == "unfinished_work"

    def test_drained_state_proceeds(self):
        ctx = {
            "META_STATE": "drained",
            "HAS_PLAN": "yes",
            "ACTIVE_ISSUE": "",
            "PLAN_POSITION": "3/3",
            "ON_MAIN": "yes",
        }
        result = evaluate("find", ctx)
        assert result["DIRECTIVE"] == "proceed"

    def test_no_plan_proceeds(self):
        ctx = {
            "META_STATE": "",
            "HAS_PLAN": "no",
            "ACTIVE_ISSUE": "",
            "PLAN_POSITION": "",
            "ON_MAIN": "yes",
        }
        result = evaluate("find", ctx)
        assert result["DIRECTIVE"] == "proceed"

    def test_unknown_issue_state_guards_back(self):
        ctx = {
            "META_STATE": "active",
            "HAS_PLAN": "yes",
            "ACTIVE_ISSUE": "42",
            "PLAN_POSITION": "0/3",
            "ON_MAIN": "no",
        }
        result = evaluate("find", ctx, issue_state="UNKNOWN")
        assert result["DIRECTIVE"] == "guard_next"


# --- context fields in output ---


class TestOutputContext:
    def test_output_includes_context_fields(self):
        ctx = {
            "META_STATE": "active",
            "HAS_PLAN": "yes",
            "ACTIVE_ISSUE": "42",
            "PLAN_POSITION": "1/3",
            "ON_MAIN": "yes",
        }
        result = evaluate("continue", ctx, issue_state="OPEN")
        assert result["ACTIVE_ISSUE"] == "42"
        assert result["ISSUE_STATE"] == "OPEN"
        assert result["QUEUE_REMAINING"] == "2"
        assert result["ON_MAIN"] == "yes"

    def test_missing_position_gives_zero_remaining(self):
        ctx = {
            "META_STATE": "active",
            "HAS_PLAN": "no",
            "ACTIVE_ISSUE": "",
            "PLAN_POSITION": "",
            "ON_MAIN": "no",
        }
        result = evaluate("continue", ctx)
        assert result["QUEUE_REMAINING"] == "0"

    def test_unknown_command_proceeds(self):
        ctx = {
            "META_STATE": "active",
            "HAS_PLAN": "yes",
            "ACTIVE_ISSUE": "42",
            "PLAN_POSITION": "0/3",
            "ON_MAIN": "no",
        }
        result = evaluate("bogus", ctx)
        assert result["DIRECTIVE"] == "proceed"
