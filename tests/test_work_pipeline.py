#!/usr/bin/env python3
"""Tests for project/work.py — unified lifecycle pipeline."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "project"))


class TestParseArgs:
    def test_parses_command_and_kv_args(self):
        from work import parse_args
        result = parse_args(["work.py", "pause",
                             "workspace=/tmp/ws", "project=/tmp/proj",
                             "branch=issue-42-foo", "base_branch=main"])
        assert result["command"] == "pause"
        assert result["workspace"] == "/tmp/ws"
        assert result["project"] == "/tmp/proj"
        assert result["branch"] == "issue-42-foo"

    def test_unknown_command_returns_error(self):
        from work import parse_args
        result = parse_args(["work.py", "bogus"])
        assert "error" in result

    def test_missing_command_returns_error(self):
        from work import parse_args
        result = parse_args(["work.py"])
        assert "error" in result

    def test_all_valid_commands_accepted(self):
        from work import parse_args, VALID_COMMANDS
        for cmd in VALID_COMMANDS:
            result = parse_args(["work.py", cmd])
            assert result["command"] == cmd


class TestBuildContext:
    def test_builds_from_args(self, tmp_path):
        from work import build_context
        ws = tmp_path / "ws"
        ws.mkdir()
        proj = tmp_path / "proj"
        proj.mkdir()
        args = {
            "command": "pause",
            "workspace": str(ws),
            "project": str(proj),
            "branch": "issue-42-foo",
            "base_branch": "main",
            "on_main": "no",
            "in_slot": "no",
            "covers": "42",
            "issue_repo": "Org/repo",
            "meta_state": "active",
            "owner_repo": "Org/repo",
            "issue_n": "42",
        }
        ctx = build_context(args)
        assert ctx.command == "pause"
        assert ctx.workspace == ws
        assert ctx.project == proj
        assert ctx.branch == "issue-42-foo"
        assert ctx.covers == "42"
        assert ctx.issue_n == "42"
        assert ctx.on_main is False
        assert ctx.in_slot is False

    def test_defaults_for_missing_fields(self, tmp_path):
        from work import build_context
        ws = tmp_path / "ws"
        ws.mkdir()
        proj = tmp_path / "proj"
        proj.mkdir()
        args = {"command": "pause", "workspace": str(ws), "project": str(proj)}
        ctx = build_context(args)
        assert ctx.branch == ""
        assert ctx.base_branch == "main"
        assert ctx.meta_state == ""
        assert ctx.flyway_next_v == "none"


class TestPausePipeline:
    def test_pause_pipeline_exists(self):
        from work import PIPELINES
        assert "pause" in PIPELINES
        steps = PIPELINES["pause"]
        names = [s.name for s in steps]
        assert "wip_commit_project" in names
        assert "wip_commit_workspace" in names
        assert "push_and_stack" in names

    def test_pause_all_mechanical(self):
        from work import PIPELINES
        for step in PIPELINES["pause"]:
            assert step.step_type == "mechanical", f"{step.name} should be mechanical"

    def test_pause_dry_run_completes(self, tmp_path):
        from work import build_context, PIPELINES
        from orchestrator_engine import run_loop
        ws = tmp_path / "ws"
        ws.mkdir()
        proj = tmp_path / "proj"
        proj.mkdir()
        ctx = build_context({
            "command": "pause",
            "workspace": str(ws), "project": str(proj),
            "branch": "issue-42-foo", "base_branch": "main",
            "on_main": "no", "in_slot": "no",
            "covers": "42", "issue_repo": "Org/repo",
            "issue_n": "42", "owner_repo": "Org/repo",
            "meta_state": "active",
        })
        ctx.dry_run = True
        result = run_loop(PIPELINES["pause"], ctx)
        assert result["ACTION"] == "complete"


class TestResumePipeline:
    def test_resume_pipeline_exists(self):
        from work import PIPELINES
        assert "resume" in PIPELINES
        steps = PIPELINES["resume"]
        names = [s.name for s in steps]
        assert "stack_pick" in names
        assert "pop_stack" in names
        assert "checkout_branches" in names
        assert "rebase" in names
        assert "reset_wip" in names
        assert "context_resume" in names

    def test_resume_has_judgment_steps(self):
        from work import PIPELINES
        steps = PIPELINES["resume"]
        judgment = [s for s in steps if s.step_type == "judgment"]
        names = [s.name for s in judgment]
        assert "stack_pick" in names
        assert "context_resume" in names

    def test_resume_dry_run_yields_stack_pick(self, tmp_path):
        from work import build_context, PIPELINES
        from orchestrator_engine import run_loop
        ws = tmp_path / "ws"
        ws.mkdir()
        proj = tmp_path / "proj"
        proj.mkdir()
        ctx = build_context({
            "command": "resume",
            "workspace": str(ws), "project": str(proj),
            "branch": "", "base_branch": "main",
            "on_main": "yes", "in_slot": "no",
            "covers": "", "issue_repo": "Org/repo",
            "meta_state": "", "owner_repo": "Org/repo",
        })
        ctx.dry_run = True
        ctx.progress["stack_depth"] = "2"
        result = run_loop(PIPELINES["resume"], ctx)
        assert result["ACTION"] == "stack_pick"

    def test_resume_skips_stack_pick_for_single_entry(self, tmp_path):
        from work import build_context, PIPELINES
        from orchestrator_engine import run_loop
        ws = tmp_path / "ws"
        ws.mkdir()
        proj = tmp_path / "proj"
        proj.mkdir()
        ctx = build_context({
            "command": "resume",
            "workspace": str(ws), "project": str(proj),
            "branch": "", "base_branch": "main",
            "on_main": "yes", "in_slot": "no",
            "covers": "", "issue_repo": "Org/repo",
            "meta_state": "", "owner_repo": "Org/repo",
        })
        ctx.dry_run = True
        ctx.progress["stack_depth"] = "1"
        result = run_loop(PIPELINES["resume"], ctx)
        assert result["ACTION"] != "stack_pick"


class TestStartPipeline:
    def test_start_pipeline_exists(self):
        from work import PIPELINES
        assert "start" in PIPELINES

    def test_start_has_expected_steps(self):
        from work import PIPELINES
        names = [s.name for s in PIPELINES["start"]]
        assert "sync_main" in names
        assert "create_branches" in names
        assert "scaffold" in names
        assert "commit_scaffold" in names
        assert "brainstorm_offer" in names

    def test_start_judgment_steps(self):
        from work import PIPELINES
        judgment = [s.name for s in PIPELINES["start"] if s.step_type == "judgment"]
        assert "resolve_issue" in judgment
        assert "branch_name" in judgment
        assert "brainstorm_offer" in judgment

    def test_start_skips_resolve_issue_when_provided(self, tmp_path):
        from work import build_context, PIPELINES
        from orchestrator_engine import run_loop
        ws = tmp_path / "ws"
        ws.mkdir()
        proj = tmp_path / "proj"
        proj.mkdir()
        ctx = build_context({
            "command": "start",
            "workspace": str(ws), "project": str(proj),
            "branch": "", "base_branch": "main",
            "on_main": "yes", "in_slot": "no",
            "covers": "42", "issue_repo": "Org/repo",
            "meta_state": "", "owner_repo": "Org/repo",
            "issue_n": "42", "issue_title": "Fix bug",
        })
        ctx.dry_run = True
        result = run_loop(PIPELINES["start"], ctx)
        assert result["ACTION"] != "resolve_issue"

    def test_start_yields_resolve_issue_when_missing(self, tmp_path):
        from work import build_context, PIPELINES
        from orchestrator_engine import run_loop
        ws = tmp_path / "ws"
        ws.mkdir()
        proj = tmp_path / "proj"
        proj.mkdir()
        ctx = build_context({
            "command": "start",
            "workspace": str(ws), "project": str(proj),
            "branch": "", "base_branch": "main",
            "on_main": "yes", "in_slot": "no",
            "covers": "", "issue_repo": "Org/repo",
            "meta_state": "", "owner_repo": "Org/repo",
        })
        ctx.dry_run = True
        result = run_loop(PIPELINES["start"], ctx)
        assert result["ACTION"] == "resolve_issue"


class TestContinuePipeline:
    def test_continue_pipeline_exists(self):
        from work import PIPELINES
        assert "continue" in PIPELINES
        names = [s.name for s in PIPELINES["continue"]]
        assert "auto_resolve_transient" in names
        assert "health_check" in names
        assert "load_context" in names

    def test_continue_yields_load_context(self, tmp_path):
        from work import build_context, PIPELINES
        from orchestrator_engine import run_loop
        ws = tmp_path / "ws"
        ws.mkdir()
        proj = tmp_path / "proj"
        proj.mkdir()
        ctx = build_context({
            "command": "continue",
            "workspace": str(ws), "project": str(proj),
            "branch": "issue-42-foo", "base_branch": "main",
            "on_main": "no", "in_slot": "no",
            "covers": "42", "issue_repo": "Org/repo",
            "meta_state": "active", "owner_repo": "Org/repo",
        })
        ctx.dry_run = True
        result = run_loop(PIPELINES["continue"], ctx)
        assert result["ACTION"] == "load_context"


class TestNextPipeline:
    def test_next_pipeline_exists(self):
        from work import PIPELINES
        assert "next" in PIPELINES
        names = [s.name for s in PIPELINES["next"]]
        assert "advance_issue" in names
        assert "context_refresh" in names


class TestFindPipeline:
    def test_find_pipeline_exists(self):
        from work import PIPELINES
        assert "find" in PIPELINES
        names = [s.name for s in PIPELINES["find"]]
        assert "refresh_cache" in names
        assert "present_candidates" in names

    def test_find_yields_present_candidates(self, tmp_path):
        from work import build_context, PIPELINES
        from orchestrator_engine import run_loop
        ws = tmp_path / "ws"
        ws.mkdir()
        proj = tmp_path / "proj"
        proj.mkdir()
        ctx = build_context({
            "command": "find",
            "workspace": str(ws), "project": str(proj),
            "branch": "", "base_branch": "main",
            "on_main": "yes", "in_slot": "no",
            "covers": "", "issue_repo": "",
            "meta_state": "", "owner_repo": "Org/repo",
        })
        ctx.dry_run = True
        result = run_loop(PIPELINES["find"], ctx)
        assert result["ACTION"] == "present_candidates"


class TestStepDoneHandling:
    def test_step_done_marks_judgment_step_complete(self, tmp_path):
        from work import main, PIPELINES
        from work_progress import read_progress
        import sys as _sys
        ws = tmp_path / "ws"
        ws.mkdir()
        proj = tmp_path / "proj"
        proj.mkdir()
        original = _sys.argv
        _sys.argv = ["work.py", "continue",
                      f"workspace={ws}", f"project={proj}",
                      "branch=issue-42-foo", "base_branch=main",
                      "on_main=no", "in_slot=no", "covers=42",
                      "issue_repo=Org/repo", "meta_state=active",
                      "owner_repo=Org/repo",
                      "step_done=load_context"]
        try:
            main()
        finally:
            _sys.argv = original
        progress = read_progress(ws)
        assert progress.get("load_context") == "done"

    def test_step_done_rejects_mechanical_step(self, tmp_path, capsys):
        from work import main
        import sys as _sys
        ws = tmp_path / "ws"
        ws.mkdir()
        proj = tmp_path / "proj"
        proj.mkdir()
        original = _sys.argv
        _sys.argv = ["work.py", "pause",
                      f"workspace={ws}", f"project={proj}",
                      "branch=issue-42-foo", "base_branch=main",
                      "on_main=no", "in_slot=no", "covers=42",
                      "issue_repo=Org/repo", "meta_state=active",
                      "step_done=wip_commit_project"]
        try:
            code = main()
        finally:
            _sys.argv = original
        assert code == 1
        captured = capsys.readouterr()
        assert "invalid_step_done" in captured.out

    def test_skip_step_marks_step_skipped(self, tmp_path):
        from work import main
        from work_progress import update_progress, read_progress
        import sys as _sys
        ws = tmp_path / "ws"
        ws.mkdir()
        proj = tmp_path / "proj"
        proj.mkdir()
        update_progress(ws, "last_yielded", "brainstorm_offer")
        original = _sys.argv
        _sys.argv = ["work.py", "start",
                      f"workspace={ws}", f"project={proj}",
                      "branch=issue-42-foo", "base_branch=main",
                      "on_main=no", "in_slot=no", "covers=42",
                      "issue_repo=Org/repo", "meta_state=active",
                      "issue_n=42",
                      "skip_step=brainstorm_offer"]
        try:
            main()
        finally:
            _sys.argv = original
        progress = read_progress(ws)
        assert progress.get("brainstorm_offer") == "skipped"


class TestSlotOccupantPid:
    def test_write_occupant_pid_on_slot_start(self, tmp_path):
        """work.py writes .occupant-pid when starting in slot context."""
        from work import _write_slot_occupant
        slot = tmp_path / "slot"
        slot.mkdir()
        _write_slot_occupant(slot)
        pid_file = slot / ".occupant-pid"
        assert pid_file.exists()
        assert int(pid_file.read_text().strip()) > 0

    def test_no_occupant_pid_outside_slot(self, tmp_path):
        """work.py does not write .occupant-pid when not in slot context."""
        from work import build_context
        ctx = build_context({
            "command": "start",
            "workspace": str(tmp_path),
            "project": str(tmp_path / "project"),
            "in_slot": "no",
        })
        assert not ctx.in_slot
        assert not (tmp_path / ".occupant-pid").exists()


class TestAllPipelinesRegistered:
    def test_all_commands_have_pipelines(self):
        from work import PIPELINES, VALID_COMMANDS
        for cmd in VALID_COMMANDS:
            assert cmd in PIPELINES, f"Missing pipeline for '{cmd}'"

    def test_all_steps_have_valid_types(self):
        from work import PIPELINES
        valid_types = {"mechanical", "judgment", "lifecycle"}
        for cmd, steps in PIPELINES.items():
            for step in steps:
                assert step.step_type in valid_types, (
                    f"{cmd}/{step.name}: invalid type '{step.step_type}'")
