"""Typed event dataclasses — the contract between command and UI layers."""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "work-slot"))
from plan_manager import IssueRef


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

@dataclass
class StateChanged:
    old_state: str
    new_state: str
    available_actions: list[str]
    suggested_action: str | None


# ---------------------------------------------------------------------------
# Informational command results
# ---------------------------------------------------------------------------

@dataclass
class HealthCheck:
    check: str
    status: str
    detail: str | None


@dataclass
class BriefReady:
    issue: IssueRef | None
    branch: str
    state: str
    queue_position: str | None
    health: list[HealthCheck]
    is_epic: bool
    epic_batch: str | None
    epic_active_issue: IssueRef | None


@dataclass
class StatusReady:
    branch: str
    state: str
    on_main: bool
    in_slot: bool
    has_plan: bool
    plan_position: str | None
    stack_depth: int
    owner_repo: str | None
    base_branch: str


@dataclass
class ContinueReady:
    issue: IssueRef | None
    branch: str
    state: str
    handoff_summary: str | None
    done_detected: bool
    suggest_next: bool
    suggest_end: bool


@dataclass
class Recommendation:
    issue: IssueRef
    title: str
    strategic_role: str | None
    readiness: str | None
    reason: str | None


@dataclass
class WhatNextReady:
    recommendations: list[Recommendation]


# ---------------------------------------------------------------------------
# State-changing command results
# ---------------------------------------------------------------------------

@dataclass
class BranchCreated:
    branch: str
    issues: list[IssueRef]
    plan_path: str | None


@dataclass
class PlanAdvanced:
    completed_issue: IssueRef
    next_issue: IssueRef | None
    next_title: str | None
    position: str
    queue_complete: bool


@dataclass
class WorkEnded:
    branch: str
    issues_closed: list[IssueRef]


@dataclass
class WipCommitted:
    repo: str
    message: str


@dataclass
class Paused:
    branch: str
    stack_depth: int


@dataclass
class Resumed:
    branch: str
    rebased: bool


@dataclass
class QuickFixLanded:
    branch: str
    message: str


# ---------------------------------------------------------------------------
# Error and progress
# ---------------------------------------------------------------------------

@dataclass
class CommandFailed:
    command: str
    step: str | None
    error: str
    detail: str
    recoverable: bool


@dataclass
class StepProgress:
    command: str
    step: str
    detail: str | None


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------

@dataclass
class IssueContext:
    issue: IssueRef
    title: str
    branch: str
    plan_position: str | None
    project_path: str
    workspace_path: str | None


@dataclass
class SessionStarted:
    provider: str
    issue: IssueRef | None


@dataclass
class SessionEnded:
    provider: str


# ---------------------------------------------------------------------------
# Home view
# ---------------------------------------------------------------------------

@dataclass
class RepoSlotInfo:
    repo: str
    slot: str | None
    branch: str
    state: str
    issue: IssueRef | None
    plan_position: str | None
    tmux_session: str | None
    project_path: str
    workspace_path: str | None


@dataclass
class HomeReady:
    repos: list[RepoSlotInfo]


@dataclass
class ContextSwitched:
    repo: str
    slot: str | None
    project_path: str
    workspace_path: str | None
