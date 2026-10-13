"""Tests for fan-out filtering fixes (#437, #438)."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_project_dir = str(Path(__file__).resolve().parent.parent / "project")
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)
_workend_dir = str(Path(__file__).resolve().parent.parent / "work-end")
if _workend_dir not in sys.path:
    sys.path.insert(0, _workend_dir)

from repo_state import RepoContext, RepoState, RepoType, RepoDisposition
from progress import Progress


def _ctx(state):
    return RepoContext(
        state=state, tree_sha="", main_tree_sha="",
        remote_synced=False, lifecycle_state=None,
    )


def _state(name, disposition, repo_type=RepoType.CLONE):
    return RepoState(
        path=Path(f"/tmp/{name}"), name=name, repo_type=repo_type,
        disposition=disposition, branch="feature", commits_ahead=1,
        is_dirty=False, has_remote=False, remote_branch_exists=False,
        landing_sha=None, has_upstream=False, push_remote="origin",
        canonical_path=None, is_slot_clone=True,
    )


def test_sweep_fanout_skips_no_work_repos(tmp_path):
    """#437: sweep fan-out should auto-mark NO_BRANCH repos as done."""
    from work_end_orchestrator import _close_per_repo_judgment
    from shared_steps import StepDef

    active = _ctx(_state("engine", RepoDisposition.HAS_WORK))
    idle = _ctx(_state("iot", RepoDisposition.NO_BRANCH))

    ctx = MagicMock()
    ctx.in_slot = True
    ctx.slot_repos = ["engine", "iot"]
    ctx.repos = [active, idle]
    ctx.progress = Progress()
    ctx.workspace = tmp_path

    step = StepDef("protocol", "sweep", "judgment")
    result = _close_per_repo_judgment(step, ctx)

    assert ctx.progress.get("protocol:iot") in ("done", "skipped", "skipped_error")


def test_sweep_fanout_runs_for_active_repos(tmp_path):
    """#437: sweep should yield for repos with HAS_WORK."""
    from work_end_orchestrator import _close_per_repo_judgment, OrchestratorContext
    from shared_steps import StepDef

    active = _ctx(_state("engine", RepoDisposition.HAS_WORK))

    ctx = OrchestratorContext(
        workspace=tmp_path, project=Path("/tmp/proj"),
        branch="feature", base_branch="main",
        meta_state="closing:review", on_main=False,
        in_slot=True, covers="500", issue_repo="Hortora/test",
        progress=Progress(), slot_path=Path("/tmp/slot"),
        slot_repos=["engine"], repos=[active],
    )

    step = StepDef("protocol", "sweep", "judgment")
    result = _close_per_repo_judgment(step, ctx)

    assert result is not None
    assert "protocol:engine" in result.get("ACTION", "")


def test_archive_blocked_when_repo_has_work():
    """#438: archive should be skipped when any repo still has work."""
    from work_end_orchestrator import _skip_multi_repo_partial_close

    active = _ctx(_state("engine", RepoDisposition.HAS_WORK))
    landed = _ctx(_state("iot", RepoDisposition.ALREADY_LANDED))

    ctx = MagicMock()
    ctx.in_slot = True
    ctx.repos = [active, landed]
    ctx.progress = MagicMock()
    ctx.progress.get = lambda k, default="": ""
    ctx.slot_path = None

    result = _skip_multi_repo_partial_close(ctx)
    assert result is True


def test_archive_allowed_when_all_repos_landed():
    """#438: archive should proceed when all repos are landed."""
    from work_end_orchestrator import _skip_multi_repo_partial_close

    landed1 = _ctx(_state("engine", RepoDisposition.ALREADY_LANDED))
    landed2 = _ctx(_state("iot", RepoDisposition.ALREADY_LANDED))

    ctx = MagicMock()
    ctx.in_slot = True
    ctx.repos = [landed1, landed2]
    ctx.progress = MagicMock()
    ctx.progress.get = lambda k, default="": "done"
    ctx.slot_path = None

    result = _skip_multi_repo_partial_close(ctx)
    assert result is False
