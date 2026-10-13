"""Tests for StepDef disposition filtering in the engine."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_project_dir = str(Path(__file__).resolve().parent.parent / "project")
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)

from repo_state import RepoDisposition, RepoType, RepoState, RepoContext
from shared_steps import (
    StepDef, ALL_MODES, ALL_DISPOSITIONS, ALL_REPO_TYPES, PipelineMode,
)
from progress import Progress


def _make_context(state):
    return RepoContext(
        state=state, tree_sha="abc123", main_tree_sha="def456",
        remote_synced=False, lifecycle_state=None,
    )


def _make_state(disposition, repo_type=RepoType.PROJECT, name="test"):
    return RepoState(
        path=Path(f"/tmp/{name}"), name=name, repo_type=repo_type,
        disposition=disposition, branch="feature", commits_ahead=1,
        is_dirty=False, has_remote=False, remote_branch_exists=False,
        landing_sha=None, has_upstream=False, push_remote="origin",
        canonical_path=None, is_slot_clone=False,
    )


def test_default_dispositions_includes_all():
    step = StepDef("test", "phase", "mechanical")
    assert step.dispositions == ALL_DISPOSITIONS
    assert step.disposition_repo_types == ALL_REPO_TYPES


def test_step_with_restricted_dispositions():
    step = StepDef(
        "review", "review", "judgment",
        dispositions=frozenset({RepoDisposition.HAS_WORK}),
        disposition_repo_types=frozenset({RepoType.PROJECT}),
    )
    assert RepoDisposition.HAS_WORK in step.dispositions
    assert RepoDisposition.EMPTY_BRANCH not in step.dispositions


def test_engine_skips_step_when_no_matching_repos(tmp_path):
    from orchestrator_engine import run_loop

    step = StepDef(
        "review", "review", "judgment",
        dispositions=frozenset({RepoDisposition.HAS_WORK}),
        disposition_repo_types=frozenset({RepoType.PROJECT}),
    )

    empty_ctx = _make_context(_make_state(RepoDisposition.EMPTY_BRANCH))

    ctx = MagicMock()
    ctx.workspace = tmp_path
    ctx.pipeline_mode = PipelineMode.BRANCH
    ctx.progress = Progress()
    ctx.repos = [empty_ctx]
    ctx.steps_executed = []
    ctx.done = lambda s: False
    ctx.last_output = {}

    result = run_loop([step], ctx)
    assert result.get("ACTION") == "complete"


def test_engine_runs_step_when_matching_repos(tmp_path):
    from orchestrator_engine import run_loop

    step = StepDef(
        "review", "review", "judgment",
        dispositions=frozenset({RepoDisposition.HAS_WORK}),
        disposition_repo_types=frozenset({RepoType.PROJECT}),
    )

    work_ctx = _make_context(_make_state(RepoDisposition.HAS_WORK))

    ctx = MagicMock()
    ctx.workspace = tmp_path
    ctx.pipeline_mode = PipelineMode.BRANCH
    ctx.progress = Progress()
    ctx.repos = [work_ctx]
    ctx.steps_executed = []
    ctx.done = lambda s: False
    ctx.last_output = {}

    result = run_loop([step], ctx)
    assert result.get("ACTION") == "review"


def test_engine_filters_by_repo_type(tmp_path):
    from orchestrator_engine import run_loop

    step = StepDef(
        "review", "review", "judgment",
        dispositions=frozenset({RepoDisposition.HAS_WORK}),
        disposition_repo_types=frozenset({RepoType.PROJECT}),
    )

    ws_ctx = _make_context(
        _make_state(RepoDisposition.HAS_WORK, RepoType.WORKSPACE, "ws")
    )

    ctx = MagicMock()
    ctx.workspace = tmp_path
    ctx.pipeline_mode = PipelineMode.BRANCH
    ctx.progress = Progress()
    ctx.repos = [ws_ctx]
    ctx.steps_executed = []
    ctx.done = lambda s: False
    ctx.last_output = {}

    result = run_loop([step], ctx)
    assert result.get("ACTION") == "complete"


def test_default_dispositions_never_filter(tmp_path):
    from orchestrator_engine import run_loop

    step = StepDef("promote", "promote", "judgment")

    empty_ctx = _make_context(_make_state(RepoDisposition.EMPTY_BRANCH))

    ctx = MagicMock()
    ctx.workspace = tmp_path
    ctx.pipeline_mode = PipelineMode.BRANCH
    ctx.progress = Progress()
    ctx.repos = [empty_ctx]
    ctx.steps_executed = []
    ctx.done = lambda s: False
    ctx.last_output = {}

    result = run_loop([step], ctx)
    assert result.get("ACTION") == "promote"
