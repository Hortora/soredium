"""Tests for commands/ — action derivation, registry, command modules."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from commands.registry import derive_actions
from commands.events import (
    StateChanged, BriefReady, StatusReady, ContinueReady,
    WhatNextReady, BranchCreated, PlanAdvanced, WorkEnded,
    CommandFailed, StepProgress, Paused, Resumed, QuickFixLanded,
)


# ---------------------------------------------------------------------------
# Action derivation tests
# ---------------------------------------------------------------------------

def test_idle_no_stack():
    actions, suggested = derive_actions("idle", stack_depth=0)
    assert "start" in actions
    assert "resume" not in actions
    assert suggested == "start"


def test_idle_with_stack():
    actions, suggested = derive_actions("idle", stack_depth=2)
    assert "resume" in actions
    assert suggested == "resume"


def test_active_with_queue():
    actions, suggested = derive_actions("active", has_queue=True)
    assert "next" in actions
    assert "continue" in actions
    assert "session" in actions
    assert suggested == "next"


def test_active_no_queue():
    actions, suggested = derive_actions("active", has_queue=False)
    assert "next" not in actions
    assert suggested == "end"


def test_paused_suggests_resume():
    actions, suggested = derive_actions("paused")
    assert suggested == "resume"
    assert "resume" in actions


def test_closing_review_has_abort():
    actions, suggested = derive_actions("closing:review")
    assert "abort" in actions


def test_closing_verified_has_abort():
    actions, suggested = derive_actions("closing:verified")
    assert "abort" in actions


def test_closing_promoted_no_abort():
    actions, suggested = derive_actions("closing:promoted")
    assert "abort" not in actions
    assert "status" in actions


def test_closing_pushed_auto_continues():
    actions, suggested = derive_actions("closing:pushed")
    assert suggested is None


def test_unknown_state_defaults_to_status():
    actions, suggested = derive_actions("unknown_state")
    assert actions == ["status"]
    assert suggested is None


# ---------------------------------------------------------------------------
# Action table completeness
# ---------------------------------------------------------------------------

def test_all_lifecycle_states_have_entries():
    from commands.registry import _ACTION_TABLE
    expected_states = {
        "idle", "active", "paused",
        "closing:review", "closing:verified", "closing:promoted",
        "closing:pushed", "closing:merged", "closing:stamped",
    }
    for state in expected_states:
        actions, _ = derive_actions(state)
        assert len(actions) > 0, f"No actions for state '{state}'"


def test_session_only_in_active():
    for state in ["idle", "paused", "closing:review", "closing:promoted"]:
        actions, _ = derive_actions(state)
        assert "session" not in actions, f"'session' should not be in '{state}'"

    actions, _ = derive_actions("active")
    assert "session" in actions


# ---------------------------------------------------------------------------
# Concurrency module
# ---------------------------------------------------------------------------

def test_file_lock():
    import tempfile
    from commands.concurrency import file_lock

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test-file"
        path.write_text("data")
        with file_lock(path):
            content = path.read_text()
            path.write_text(content + " modified")
        assert path.read_text() == "data modified"
        lock_file = Path(tmp) / ".test-file.lock"
        assert lock_file.exists()


# ---------------------------------------------------------------------------
# Command module imports
# ---------------------------------------------------------------------------

def test_all_command_modules_importable():
    """Verify all command modules can be imported."""
    import importlib
    modules = [
        "commands.brief", "commands.status", "commands.continue_",
        "commands.what_next", "commands.start", "commands.next",
        "commands.end", "commands.pause", "commands.resume",
        "commands.quick_fix",
    ]
    for mod_name in modules:
        mod = importlib.import_module(mod_name)
        assert hasattr(mod, "execute"), f"{mod_name} missing execute()"


def test_command_execute_signatures():
    """Verify all command execute() functions accept cwd keyword."""
    import importlib
    import inspect
    modules = [
        "commands.brief", "commands.status", "commands.continue_",
        "commands.what_next", "commands.start", "commands.next",
        "commands.end", "commands.pause", "commands.resume",
        "commands.quick_fix",
    ]
    for mod_name in modules:
        mod = importlib.import_module(mod_name)
        sig = inspect.signature(mod.execute)
        param_names = list(sig.parameters.keys())
        assert "cwd" in param_names or "_kwargs" in str(sig), \
            f"{mod_name}.execute() must accept cwd parameter"
