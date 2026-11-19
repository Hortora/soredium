#!/usr/bin/env python3
"""Tests for project/work.py — unified lifecycle pipeline."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "project"))

from judgment import StepType


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
            assert step.step_type == StepType.MECHANICAL, f"{step.name} should be mechanical"

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
        judgment = [s for s in steps if s.step_type == StepType.JUDGMENT]
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
        judgment = [s.name for s in PIPELINES["start"] if s.step_type == StepType.JUDGMENT]
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

    def test_outcome_skipped_marks_step_skipped(self, tmp_path):
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
                      "step_done=brainstorm_offer", "outcome=skipped"]
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
        valid_types = {StepType.MECHANICAL, StepType.JUDGMENT, StepType.LIFECYCLE}
        for cmd, steps in PIPELINES.items():
            for step in steps:
                assert step.step_type in valid_types, (
                    f"{cmd}/{step.name}: invalid type '{step.step_type}'")


class TestContextFromOneCall:
    """work.py resolves its own context when the caller gives no workspace (#548)."""

    def test_args_come_from_resolved_context(self):
        from work import fill_from_context
        context = {"WORKSPACE": "/w", "PROJECT": "/p", "CURRENT_BRANCH": "issue-1-x",
                   "BASE_BRANCH": "trunk", "ON_MAIN": "no", "IN_SLOT": "yes",
                   "PLAN_PATH": "/w/.queue", "OWNER_REPO": "o/r", "ISSUE_N": "1"}
        args = fill_from_context({"command": "continue"}, resolve=lambda: context)
        assert args["command"] == "continue"
        assert args["workspace"] == "/w"
        assert args["project"] == "/p"
        assert args["branch"] == "issue-1-x"
        assert args["base_branch"] == "trunk"
        assert args["in_slot"] == "yes"
        assert args["plan_path"] == "/w/.queue"

    def test_empty_context_values_are_left_out(self):
        from work import fill_from_context
        context = {"WORKSPACE": "/w", "PROJECT": "/p", "PLAN_PATH": "",
                   "SLOT_PATH": "", "FLYWAY_NEXT_V": ""}
        args = fill_from_context({"command": "pause"}, resolve=lambda: context)
        assert "plan_path" not in args
        assert "slot_path" not in args
        assert "flyway_next_v" not in args

    def test_given_arguments_win_over_context(self):
        from work import fill_from_context
        context = {"WORKSPACE": "/w", "PROJECT": "/p", "ISSUE_N": "1"}
        args = fill_from_context({"command": "start", "issue_n": "42",
                                  "issue_title": "T"}, resolve=lambda: context)
        assert args["issue_n"] == "42"
        assert args["issue_title"] == "T"
        assert args["workspace"] == "/w"

    def test_explicit_workspace_never_resolves_context(self):
        from work import fill_from_context

        def boom():
            raise AssertionError("context must not be resolved")
        given = {"command": "pause", "workspace": "/w", "project": "/p"}
        assert fill_from_context(dict(given), resolve=boom) == given

    def test_parse_error_passes_through(self):
        from work import fill_from_context
        assert fill_from_context({"error": "missing_command"},
                                 resolve=lambda: {}) == {"error": "missing_command"}

    def test_unresolvable_context_is_an_error_not_a_crash(self):
        from work import fill_from_context

        def no_workspace():
            raise RuntimeError("no workspace here")
        args = fill_from_context({"command": "continue"}, resolve=no_workspace)
        assert args["error"].startswith("context_unresolved:")
        assert "no workspace here" in args["error"]

    def test_every_mapped_key_is_one_ctx_emits(self):
        """A renamed ctx.py key must fail here, not silently become a default."""
        from work import CONTEXT_ARGS
        source = (Path(__file__).parent.parent / "project" / "ctx.py").read_text()
        missing = [k for k in CONTEXT_ARGS.values() if f'"{k}":' not in source]
        assert missing == []

    def test_every_mapped_argument_is_one_build_context_reads(self):
        from work import CONTEXT_ARGS
        source = (Path(__file__).parent.parent / "project" / "work.py").read_text()
        unread = [a for a in CONTEXT_ARGS
                  if f'args.get("{a}"' not in source and f'args["{a}"]' not in source]
        assert unread == []

    def test_main_without_arguments_reports_unresolved_context(self, tmp_path, monkeypatch, capsys):
        """End to end: outside any workspace the script says so in one line."""
        import work
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(sys, "argv", ["work.py", "continue"])
        rc = work.main()
        out = capsys.readouterr().out
        assert rc == 1
        assert out.startswith("ERROR=")


QUEUE_TEXT = """# Work Plan —

## State
branch:
status: drained
issue-repo: o/r

## Queue
- [x] o/r#1 — first
- [ ] o/r#289 — deprecated url
- [ ] o/r#290 — put bytes
"""


class TestRoutedEntry:
    """`work continue` runs whatever the queue calls for, in one call (#548)."""

    def _args(self, tmp_path, command, branch, text=QUEUE_TEXT, **extra):
        (tmp_path / ".queue").write_text(text)
        return {"command": command, "workspace": str(tmp_path), "project": str(tmp_path),
                "branch": branch, "base_branch": "main",
                "on_main": "yes" if branch == "main" else "no", **extra}

    def _active(self, tmp_path):
        from queue_io import read_queue
        item = read_queue(tmp_path).active_item()
        return item.ref if item else None

    def test_continue_on_a_hand_made_branch_activates_its_item(self, tmp_path):
        """The observed failure: nothing active, on the branch of an open item."""
        from work import apply_route
        args, lines, stop = apply_route(self._args(tmp_path, "continue", "issue-289-url"))
        assert not stop
        assert args["command"] == "continue"
        assert "ACTIVATED=o/r#289" in lines and "COMMAND=continue" in lines
        assert self._active(tmp_path) == "o/r#289"
        assert args["covers"] == "o/r#289"

    def test_next_does_the_same_when_nothing_is_active(self, tmp_path):
        from work import apply_route
        args, lines, stop = apply_route(self._args(tmp_path, "next", "issue-289-url"))
        assert args["command"] == "continue"
        assert self._active(tmp_path) == "o/r#289"

    def test_continue_on_base_starts_the_next_open_item(self, tmp_path):
        from work import apply_route
        args, lines, stop = apply_route(self._args(tmp_path, "continue", "main"))
        assert not stop
        assert args["command"] == "start"
        assert (args["issue_n"], args["issue_title"], args["issue_repo"]) == (
            "289", "deprecated url", "o/r")
        assert "COMMAND=start" in lines
        assert self._active(tmp_path) == "o/r#289"

    def test_given_issue_arguments_are_kept(self, tmp_path):
        from work import apply_route
        args, _, _ = apply_route(self._args(tmp_path, "continue", "main", issue_title="Mine"))
        assert args["issue_title"] == "Mine"

    def test_active_item_runs_the_command_unchanged(self, tmp_path):
        from work import apply_route
        text = QUEUE_TEXT.replace("deprecated url", "deprecated url ← active")
        before = text
        args, lines, stop = apply_route(self._args(tmp_path, "continue", "issue-289-url", text))
        assert (args["command"], stop) == ("continue", False)
        assert not any(l.startswith("ACTIVATED=") for l in lines)
        assert (tmp_path / ".queue").read_text() == before

    def test_unknown_branch_stops_with_a_decision_and_changes_nothing(self, tmp_path):
        from work import apply_route
        args, lines, stop = apply_route(self._args(tmp_path, "continue", "wip-thing"))
        assert stop
        assert "ACTION=decision" in lines
        assert "DECISION=branch_matches_no_open_item" in lines
        assert (tmp_path / ".queue").read_text() == QUEUE_TEXT

    def test_only_finished_items_hands_over_to_work_end(self, tmp_path):
        from work import apply_route
        text = QUEUE_TEXT.replace("- [ ] o/r#289 — deprecated url",
                                  "- [ ] o/r#289 — deprecated url ← done on issue-289-url"
                                  ).replace("- [ ] o/r#290", "- [x] o/r#290")
        args, lines, stop = apply_route(self._args(tmp_path, "continue", "main", text))
        assert stop
        assert "ACTION=stop" in lines and "NEXT=work end" in lines
        assert "OFFER=wrap_or_continue" in lines
        assert "DONE_ITEMS=o/r#289@issue-289-url" in lines

    def test_nothing_left_names_work_find(self, tmp_path):
        from work import apply_route
        text = QUEUE_TEXT.replace("- [ ]", "- [x]")
        _, lines, stop = apply_route(self._args(tmp_path, "continue", "main", text))
        assert stop and any(l.startswith("NEXT=work find") for l in lines)

    def test_a_step_report_is_never_rerouted(self, tmp_path):
        from work import apply_route
        given = self._args(tmp_path, "continue", "main", step_done="load_context")
        args, lines, stop = apply_route(dict(given))
        assert (args, lines, stop) == (given, [], False)
        assert (tmp_path / ".queue").read_text() == QUEUE_TEXT

    def test_no_queue_file_runs_the_command_as_given(self, tmp_path):
        from work import apply_route
        given = {"command": "continue", "workspace": str(tmp_path), "branch": "issue-1-x"}
        assert apply_route(dict(given)) == (given, [], False)

    def test_other_commands_are_untouched(self, tmp_path):
        from work import apply_route
        given = self._args(tmp_path, "pause", "issue-289-url")
        assert apply_route(dict(given)) == (given, [], False)

    def test_main_prints_the_decision_and_exits_cleanly(self, tmp_path, monkeypatch, capsys):
        import work
        a = self._args(tmp_path, "continue", "wip-thing")
        monkeypatch.setattr(sys, "argv", ["work.py", "continue"] + [
            f"{k}={v}" for k, v in a.items() if k != "command"])
        rc = work.main()
        out = capsys.readouterr().out
        assert rc == 0
        assert "ACTION=decision" in out
        assert "ACTION=complete" not in out


class TestNextIsContinue:
    def _args(self, tmp_path, command):
        (tmp_path / ".queue").write_text(
            QUEUE_TEXT.replace("status: drained", "status: active")
            .replace("deprecated url", "deprecated url ← active"))
        return {"command": command, "workspace": str(tmp_path), "project": str(tmp_path),
                "branch": "issue-289-url", "base_branch": "main", "on_main": "no"}

    def test_next_on_an_active_item_continues_it(self, tmp_path):
        from work import apply_route
        args, lines, stop = apply_route(self._args(tmp_path, "next"))
        assert (args["command"], stop) == ("continue", False)
        assert "COMMAND=continue" in lines
        assert "← done on" not in (tmp_path / ".queue").read_text()

    def test_done_runs_the_mark_done_pipeline(self, tmp_path):
        from work import apply_route, PIPELINES, NEXT_STEPS
        args, lines, stop = apply_route(self._args(tmp_path, "done"))
        assert (args["command"], stop) == ("done", False)
        assert PIPELINES["done"] is NEXT_STEPS
        assert "OFFER=wrap_or_continue" in lines

    def test_done_is_a_valid_command(self):
        from work import parse_args
        assert parse_args(["work.py", "done"]) == {"command": "done"}


class TestStartIsTheSameCommand:
    def _args(self, tmp_path, **extra):
        (tmp_path / ".queue").write_text(QUEUE_TEXT)
        return {"command": "start", "workspace": str(tmp_path), "project": str(tmp_path),
                "branch": "main", "base_branch": "main", "on_main": "yes", **extra}

    def test_start_without_an_issue_takes_the_next_open_item(self, tmp_path):
        from work import apply_route
        args, lines, _ = apply_route(self._args(tmp_path))
        assert (args["command"], args["issue_n"]) == ("start", "289")
        assert "ACTIVATED=o/r#289" in lines

    def test_start_with_a_named_issue_starts_that_issue_and_no_other(self, tmp_path):
        """A named issue is never rerouted to another item; since #561 it is
        made the active item so the queue says what is being worked on."""
        from work import apply_route
        from queue_io import read_queue
        args, lines, stop = apply_route(self._args(tmp_path, issue_n="290"))
        assert not stop
        assert args["command"] == "start" and args["issue_n"] == "290"
        assert read_queue(tmp_path).active_item().ref == "o/r#290"
        assert "ACTIVATED=o/r#290" in lines and "ACTIVATED=o/r#289" not in lines

    def test_start_on_the_branch_of_an_open_item_continues_it(self, tmp_path):
        from work import apply_route
        a = self._args(tmp_path)
        a.update(branch="issue-290-put", on_main="no")
        args, lines, _ = apply_route(a)
        assert args["command"] == "continue"
        assert "ACTIVATED=o/r#290" in lines

    def test_paused_stack_routes_to_resume(self, tmp_path):
        from work import apply_route
        args, lines, stop = apply_route(self._args(tmp_path, stack_depth="1"))
        assert (args["command"], stop) == ("resume", False)
        assert (tmp_path / ".queue").read_text() == QUEUE_TEXT


class TestNamedStartRegistersTheIssue:
    """`work start #N` puts N in the queue, active, and covered, before branching (#561)."""

    DRAINED = ("- [x] o/r#553 — Earlier work\n\n## State\nbranch: issue-553-x\n"
               "issue-repo: O/r\nstatus: drained\ncovers: o/r#553\n")

    def _args(self, tmp_path, text, branch="main", **extra):
        (tmp_path / ".queue").write_text(text)
        return {"command": "start", "workspace": str(tmp_path), "project": str(tmp_path),
                "branch": branch, "base_branch": "main",
                "on_main": "yes" if branch == "main" else "no", **extra}

    def _queue(self, tmp_path):
        from queue_io import read_queue
        return read_queue(tmp_path)

    def test_the_observed_failure_issue_absent_and_covers_stale(self, tmp_path):
        from work import apply_route
        args, lines, stop = apply_route(self._args(tmp_path, self.DRAINED, issue_n="551"))

        assert not stop
        queue = self._queue(tmp_path)
        assert queue.active_item().ref == "o/r#551"
        assert queue.state.covers == "o/r#551"
        assert queue.state.status == "active"
        assert args["command"] == "start"
        assert args["covers"] == "o/r#551"
        assert args["issue_n"] == "551" and args["issue_repo"] == "O/r"
        assert "QUEUED=o/r#551" in lines and "ACTIVATED=o/r#551" in lines
        assert lines[-1] == "COMMAND=start"
        assert [i.ref for i in queue.items if i.completed] == ["o/r#553"]

    def test_title_given_by_the_caller_is_kept(self, tmp_path):
        from work import apply_route
        apply_route(self._args(tmp_path, self.DRAINED, issue_n="551", issue_title="Fix hooks"))
        assert self._queue(tmp_path).active_item().title == "Fix hooks"

    def test_hash_prefix_on_the_number_is_accepted(self, tmp_path):
        from work import apply_route
        args, lines, stop = apply_route(self._args(tmp_path, self.DRAINED, issue_n="#551"))
        assert not stop and self._queue(tmp_path).active_item().ref == "o/r#551"

    def test_an_item_added_without_a_title_reads_back_as_itself(self, tmp_path):
        from work import apply_route
        apply_route(self._args(tmp_path, self.DRAINED, issue_n="551"))
        item = self._queue(tmp_path).active_item()
        assert (item.ref, item.title) == ("o/r#551", "issue 551")

    def test_no_network_is_used(self, tmp_path, monkeypatch):
        import subprocess as sp
        from work import apply_route
        real = sp.run
        def guarded(cmd, *a, **k):
            assert "gh" not in (cmd[0] if isinstance(cmd, (list, tuple)) else cmd), cmd
            return real(cmd, *a, **k)
        monkeypatch.setattr(sp, "run", guarded)
        args, lines, stop = apply_route(self._args(tmp_path, self.DRAINED, issue_n="551"))
        assert not stop

    def test_an_open_item_already_queued_is_activated_not_duplicated(self, tmp_path):
        from work import apply_route
        text = "- [ ] o/r#551 — Queued earlier\n" + self.DRAINED
        args, lines, stop = apply_route(self._args(tmp_path, text, issue_n="551"))
        queue = self._queue(tmp_path)
        assert not stop
        assert [i.ref for i in queue.items].count("o/r#551") == 1
        assert queue.active_item().ref == "o/r#551"
        assert "QUEUED=o/r#551" not in lines
        assert args.get("issue_title") == "Queued earlier"

    def test_the_issue_repo_is_matched_whatever_its_case(self, tmp_path):
        from work import apply_route
        text = "- [ ] o/r#551 — Queued earlier\n" + self.DRAINED
        apply_route(self._args(tmp_path, text, issue_n="551", issue_repo="O/R"))
        assert [i.ref for i in self._queue(tmp_path).items].count("o/r#551") == 1

    @pytest.mark.parametrize("text, reason", [
        ("- [ ] o/r#7 — Other ← active\n\n## State\nbranch: issue-7-x\nissue-repo: O/r\n"
         "status: active\ncovers: o/r#7\n", "another_item_active"),
        ("- [x] o/r#551 — Done long ago\n\n## State\nbranch: \nissue-repo: O/r\n"
         "status: drained\n", "named_issue_already_closed"),
        ("- [ ] o/r#551 — Finished ← done on issue-551-x\n\n## State\nbranch: \n"
         "issue-repo: O/r\nstatus: active\n", "named_issue_done_awaiting_close"),
    ])
    def test_decisions_change_nothing(self, tmp_path, text, reason):
        from work import apply_route
        args, lines, stop = apply_route(self._args(tmp_path, text, issue_n="551"))
        assert stop
        assert "ACTION=decision" in lines and f"DECISION={reason}" in lines
        assert any(l.startswith("OPTIONS=") and "," in l for l in lines)
        assert (tmp_path / ".queue").read_text() == text

    def test_naming_the_item_already_in_progress_continues_it(self, tmp_path):
        from work import apply_route
        text = ("- [ ] o/r#551 — In progress ← active\n\n## State\nbranch: issue-551-x\n"
                "issue-repo: O/r\nstatus: active\ncovers: o/r#551\n")
        args, lines, stop = apply_route(self._args(tmp_path, text, branch="issue-551-x",
                                                   issue_n="551"))
        assert not stop
        assert args["command"] == "continue" and "issue_n" not in args
        assert "COMMAND=continue" in lines
        assert (tmp_path / ".queue").read_text() == text

    def test_active_but_never_started_item_is_started(self, tmp_path):
        from work import apply_route
        text = ("- [ ] o/r#551 — Not begun ← active\n\n## State\nbranch: \n"
                "issue-repo: O/r\nstatus: active\ncovers: o/r#551\n")
        args, lines, stop = apply_route(self._args(tmp_path, text, issue_n="551"))
        assert not stop and args["command"] == "start"
        assert "QUEUED=o/r#551" not in lines and "ACTIVATED=o/r#551" not in lines

    def test_without_a_queue_the_start_runs_as_given(self, tmp_path):
        from work import apply_route
        given = {"command": "start", "workspace": str(tmp_path), "project": str(tmp_path),
                 "branch": "main", "base_branch": "main", "on_main": "yes", "issue_n": "551"}
        assert apply_route(dict(given)) == (given, [], False)

    def test_a_follow_up_call_registers_nothing(self, tmp_path):
        from work import apply_route
        args = self._args(tmp_path, self.DRAINED, issue_n="551", step_done="branch_name")
        assert apply_route(args)[1:] == ([], False)
        assert (tmp_path / ".queue").read_text() == self.DRAINED
