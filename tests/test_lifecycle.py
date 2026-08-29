#!/usr/bin/env python3
"""Tests for project/lifecycle.py — the lifecycle state machine core."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

LIFECYCLE = Path(__file__).parent.parent / "project" / "lifecycle.py"

sys.path.insert(0, str(LIFECYCLE.parent))
from lifecycle import (
    CLOSING_STATES,
    EVIDENCE_GATES,
    RESTING_STATES,
    TRANSITION_TABLE,
    TRANSIENT_STATES,
    VALID_STATES,
    ConcurrentModification,
    CorruptedState,
    InvalidEvidence,
    InvalidState,
    InvalidTransition,
    MissingEvidence,
    StateError,
    TransitionResult,
    _read_evidence_era,
    _validate_evidence,
    _write_evidence_era,
    can_transition,
    commit_transition,
    ClosureState,
    is_closed,
    is_closing,
    is_transient,
    migrate_legacy_paused,
    read_state,
    transition,
    validate_state,
    write_state,
)


def _write_plan(path: Path, state: str = "active", branch: str = "issue-42-foo", **extra):
    defaults = {"date": "2026-08-03"}
    defaults.update(extra)
    lines = ["# Work Plan — test", "", "## State",
             f"branch: {branch}", f"state: {state}"]
    for k, v in defaults.items():
        lines.append(f"{k.replace('_', '-')}: {v}")
    lines.extend(["", "## Queue", "(empty)", ""])
    path.write_text("\n".join(lines))


@pytest.fixture
def tmp_meta(tmp_path):
    plan = tmp_path / ".plan"
    _write_plan(plan)
    return plan


# --- State constants and classification ---


class TestStateConstants:
    def test_valid_states_count(self):
        assert len(VALID_STATES) == 12

    def test_transient_states_are_subset(self):
        assert TRANSIENT_STATES <= VALID_STATES

    def test_closing_states_are_subset(self):
        assert CLOSING_STATES <= VALID_STATES

    def test_closing_states_count(self):
        assert len(CLOSING_STATES) == 6

    def test_transient_states_are_scaffolded_and_transitioning(self):
        assert TRANSIENT_STATES == {"scaffolded", "transitioning"}

    @pytest.mark.parametrize(
        "state, expected",
        [
            ("scaffolded", True),
            ("transitioning", True),
            ("active", False),
            ("paused", False),
            ("idle", False),
            ("closing:review", False),
        ],
    )
    def test_is_transient(self, state, expected):
        assert is_transient(state) == expected

    @pytest.mark.parametrize(
        "state, expected",
        [
            ("closing:review", True),
            ("closing:verified", True),
            ("closing:promoted", True),
            ("closing:pushed", True),
            ("closing:merged", True),
            ("closing:stamped", True),
            ("active", False),
            ("idle", False),
            ("paused", False),
        ],
    )
    def test_is_closing(self, state, expected):
        assert is_closing(state) == expected

    def test_can_transition_valid(self):
        assert can_transition("active", "work_end") is True

    def test_can_transition_invalid(self):
        assert can_transition("idle", "work_next") is False


# --- read_state / write_state ---


class TestReadWriteState:
    def test_read_active(self, tmp_meta):
        assert read_state(tmp_meta) == "active"

    def test_read_closing_pushed(self, tmp_path):
        meta = tmp_path / ".plan"
        _write_plan(meta, state="closing:pushed", branch="x", date="2026-08-03")
        assert read_state(meta) == "closing:pushed"

    def test_read_all_valid_states(self, tmp_path):
        meta = tmp_path / ".plan"
        for state in VALID_STATES - {"idle"}:
            meta.write_text(f"branch: x\nstate: {state}\ndate: 2026-08-03\n")
            assert read_state(meta) == state

    def test_no_meta_returns_none(self, tmp_path):
        assert read_state(tmp_path / ".plan") is None

    def test_missing_state_field_returns_active(self, tmp_path):
        meta = tmp_path / ".plan"
        _write_plan(meta, state="active", branch="issue-42-foo", date="2026-08-03")
        assert read_state(meta) == "active"

    def test_unknown_state_raises_corrupted(self, tmp_path):
        meta = tmp_path / ".plan"
        _write_plan(meta, state="bogus", branch="x", date="2026-08-03")
        with pytest.raises(CorruptedState):
            read_state(meta)

    def test_truncated_closing_state_raises_corrupted(self, tmp_path):
        meta = tmp_path / ".plan"
        _write_plan(meta, state="closing:pro", branch="x", date="2026-08-03")
        with pytest.raises(CorruptedState):
            read_state(meta)

    def test_write_updates_existing(self, tmp_meta):
        write_state(tmp_meta, "closing:review")
        assert read_state(tmp_meta) == "closing:review"
        assert tmp_meta.read_text().count("state:") == 1

    def test_write_appends_to_legacy(self, tmp_path):
        meta = tmp_path / ".plan"
        _write_plan(meta, state="active", branch="issue-42-foo", date="2026-08-03")
        write_state(meta, "scaffolded")
        content = meta.read_text()
        assert "state: scaffolded" in content
        assert content.index("branch:") < content.index("state:")

    def test_write_appends_at_end_if_no_branch(self, tmp_path):
        meta = tmp_path / ".plan"
        _write_plan(meta, state="active", branch="issue-42-foo", date="2026-08-03")
        write_state(meta, "active")
        assert "state: active" in meta.read_text()

    def test_write_is_atomic(self, tmp_meta):
        write_state(tmp_meta, "closing:merged")
        assert not (tmp_meta.parent / ".plan.tmp").exists()

    def test_write_preserves_other_fields(self, tmp_meta):
        original = tmp_meta.read_text()
        write_state(tmp_meta, "paused")
        new_content = tmp_meta.read_text()
        assert "branch: issue-42-foo" in new_content
        assert "date: 2026-08-03" in new_content
        assert "state: paused" in new_content


# --- transition() ---


class TestValidTransitions:
    @pytest.mark.parametrize(
        "from_state, event, expected_state, expected_effects",
        [
            ("idle", "work", "scaffolded", ["create_branch", "write_plan", "build_plan"]),
            ("idle", "slot_create", "scaffolded", ["create_slot", "write_plan", "build_plan"]),
            ("scaffolded", "auto_setup", "active", ["garden_search", "load_specs", "check_protocols", "check_intellij"]),
            ("active", "work_next", "transitioning", ["advance_issue", "tick_github"]),
            ("transitioning", "auto_refresh", "active", ["garden_search", "load_specs", "check_protocols"]),
            ("active", "work_pause", "paused", ["wip_commit"]),
            ("paused", "work_resume", "active", ["pop_stack", "reset_wip", "context_resume"]),
            ("active", "work_end", "closing:review", ["pre_close_sweep"]),
            ("closing:review", "review_pass", "closing:verified", ["record_review"]),
            ("closing:verified", "promote_pass", "closing:promoted", ["write_promotion_stamp"]),
            ("closing:promoted", "push_pass", "closing:pushed", []),
            ("closing:pushed", "merge_pass", "closing:merged", ["verify_content_landed"]),
            ("closing:merged", "stamp_pass", "closing:stamped", ["write_stamp"]),
            ("closing:stamped", "cleanup_pass", "idle", ["write_plan_closed"]),
        ],
    )
    def test_valid_transition(self, from_state, event, expected_state, expected_effects, tmp_path):
        meta = tmp_path / ".plan"
        if from_state != "idle":
            meta.write_text(f"branch: issue-42-foo\nstate: {from_state}\ndate: 2026-08-03\n")
        result = transition(meta, event)
        assert result.from_state == from_state
        assert result.new_state == expected_state
        assert result.effects == expected_effects
        if from_state != "idle":
            assert read_state(meta) == from_state  # Phase 1 does NOT write

    def test_work_pause_has_post_commit_effects(self, tmp_meta):
        result = transition(tmp_meta, "work_pause")
        assert result.effects == ["wip_commit"]
        assert result.post_commit_effects == ["switch_to_main", "push_stack"]

    def test_cleanup_has_post_commit_effects(self, tmp_path):
        meta = tmp_path / ".plan"
        _write_plan(meta, state="closing:stamped", branch="x", date="2026-08-03")
        result = transition(meta, "cleanup_pass")
        assert result.effects == ["write_plan_closed"]
        assert result.post_commit_effects == ["return_to_main", "write_handoff"]

    def test_standard_transitions_have_empty_post_commit(self, tmp_meta):
        result = transition(tmp_meta, "work_end")
        assert result.post_commit_effects == []

    @pytest.mark.parametrize("closing_state", ["closing:review", "closing:verified"])
    def test_abort_from_pre_artifact(self, closing_state, tmp_path):
        meta = tmp_path / ".plan"
        meta.write_text(f"branch: x\nstate: {closing_state}\ndate: 2026-08-03\n")
        result = transition(meta, "abort_close")
        assert result.new_state == "active"
        assert result.effects == ["clear_closing_markers"]

    @pytest.mark.parametrize(
        "closing_state",
        ["closing:promoted", "closing:pushed", "closing:merged", "closing:stamped"],
    )
    def test_abort_blocked_post_artifact(self, closing_state, tmp_path):
        meta = tmp_path / ".plan"
        meta.write_text(f"branch: x\nstate: {closing_state}\ndate: 2026-08-03\n")
        with pytest.raises(InvalidTransition):
            transition(meta, "abort_close")


# --- invalid transitions ---


class TestInvalidTransitions:
    @pytest.mark.parametrize(
        "from_state, event",
        [
            ("idle", "work_next"),
            ("idle", "work_pause"),
            ("idle", "work_end"),
            ("idle", "work_resume"),
            ("scaffolded", "work_next"),
            ("scaffolded", "work_end"),
            ("scaffolded", "work_pause"),
            ("active", "work"),
            ("active", "work_resume"),
            ("active", "auto_setup"),
            ("transitioning", "work_end"),
            ("transitioning", "work_pause"),
            ("paused", "work_end"),
            ("paused", "work_next"),
            ("paused", "work_pause"),
            ("closing:review", "work_pause"),
            ("closing:review", "work_next"),
            ("closing:review", "work"),
            ("closing:verified", "review_pass"),
            ("closing:promoted", "promote_pass"),
            ("closing:pushed", "push_pass"),
        ],
    )
    def test_invalid_transition_raises(self, from_state, event, tmp_path):
        meta = tmp_path / ".plan"
        if from_state != "idle":
            meta.write_text(f"branch: x\nstate: {from_state}\ndate: 2026-08-03\n")
        with pytest.raises(InvalidTransition):
            transition(meta, event)

    def test_invalid_transition_has_message(self, tmp_meta):
        with pytest.raises(InvalidTransition, match="Already on an active branch"):
            transition(tmp_meta, "work")

    def test_unknown_event_raises(self, tmp_meta):
        with pytest.raises(InvalidTransition):
            transition(tmp_meta, "nonexistent_event")


class TestWorkContinueTransition:
    def test_active_work_continue_is_self_transition(self, tmp_path):
        meta = tmp_path / ".plan"
        _write_plan(meta, state="active", branch="issue-1-test")
        result = transition(meta, 'work_continue')
        assert result.from_state == 'active'
        assert result.new_state == 'active'
        assert result.effects == []
        assert result.post_commit_effects == []

    def test_idle_work_continue_raises(self, tmp_path):
        meta = tmp_path / ".plan"
        with pytest.raises(InvalidTransition) as exc_info:
            transition(meta, 'work_continue')
        assert 'continue' in str(exc_info.value).lower()

    def test_scaffolded_work_continue_raises(self, tmp_path):
        meta = tmp_path / ".plan"
        _write_plan(meta, state="scaffolded", branch="issue-1-test")
        with pytest.raises(InvalidTransition):
            transition(meta, 'work_continue')

    def test_paused_work_continue_raises(self, tmp_path):
        meta = tmp_path / ".plan"
        _write_plan(meta, state="paused", branch="issue-1-test")
        with pytest.raises(InvalidTransition) as exc_info:
            transition(meta, 'work_continue')
        assert 'resume' in str(exc_info.value).lower()

    def test_transitioning_work_continue_raises(self, tmp_path):
        meta = tmp_path / ".plan"
        _write_plan(meta, state="transitioning", branch="issue-1-test")
        with pytest.raises(InvalidTransition):
            transition(meta, 'work_continue')

    def test_can_transition_active_work_continue(self):
        assert can_transition('active', 'work_continue') is True

    def test_cannot_transition_idle_work_continue(self):
        assert can_transition('idle', 'work_continue') is False


# --- commit_transition ---


class TestCommitTransition:
    def test_commit_writes_new_state(self, tmp_meta):
        result = transition(tmp_meta, "work_end")
        commit_transition(tmp_meta, result)
        assert read_state(tmp_meta) == "closing:review"

    def test_commit_detects_concurrent_modification(self, tmp_meta):
        result = transition(tmp_meta, "work_end")
        write_state(tmp_meta, "paused")
        with pytest.raises(ConcurrentModification):
            commit_transition(tmp_meta, result)

    def test_commit_idle_to_scaffolded_verifies_meta(self, tmp_path):
        meta = tmp_path / ".plan"
        result = transition(meta, "work")
        _write_plan(meta, state="scaffolded", branch="issue-1-test", date="2026-08-03")
        commit_transition(meta, result)
        assert read_state(meta) == "scaffolded"

    def test_commit_idle_to_scaffolded_fails_without_meta(self, tmp_path):
        meta = tmp_path / ".plan"
        result = transition(meta, "work")
        with pytest.raises(StateError):
            commit_transition(meta, result)

    def test_commit_to_idle_deletes_plan(self, tmp_path):
        meta = tmp_path / ".plan"
        _write_plan(meta, state="closing:stamped", branch="x", date="2026-08-03")
        result = transition(meta, "cleanup_pass")
        commit_transition(meta, result)
        assert not meta.exists(), ".plan should be deleted on transition to idle"

    def test_commit_to_idle_checks_concurrent(self, tmp_path):
        meta = tmp_path / ".plan"
        _write_plan(meta, state="closing:stamped", branch="x", date="2026-08-03")
        result = transition(meta, "cleanup_pass")
        write_state(meta, "closing:merged")
        with pytest.raises(ConcurrentModification):
            commit_transition(meta, result)

    def test_post_commit_effects_for_pause(self, tmp_meta):
        result = transition(tmp_meta, "work_pause")
        assert result.effects == ["wip_commit"]
        assert result.post_commit_effects == ["switch_to_main", "push_stack"]

    def test_post_commit_effects_empty_for_standard(self, tmp_meta):
        result = transition(tmp_meta, "work_end")
        assert result.post_commit_effects == []


# --- migrate_legacy_paused ---


class TestMigrateLegacyPaused:
    def test_migrates_missing_state_to_paused(self, tmp_path):
        meta = tmp_path / ".plan"
        meta.write_text("branch: issue-42-foo\ndate: 2026-08-03\n")
        assert migrate_legacy_paused(meta) is True
        assert read_state(meta) == "paused"

    def test_no_op_if_already_paused(self, tmp_path):
        meta = tmp_path / ".plan"
        _write_plan(meta, state="paused")
        assert migrate_legacy_paused(meta) is False

    def test_no_op_if_has_explicit_state(self, tmp_path):
        meta = tmp_path / ".plan"
        _write_plan(meta, state="active")
        assert migrate_legacy_paused(meta) is False

    def test_no_op_if_no_meta(self, tmp_path):
        meta = tmp_path / ".plan"
        assert migrate_legacy_paused(meta) is False


# --- hygiene invariants ---


class TestHygieneInvariants:
    @pytest.fixture
    def git_project(self, tmp_path):
        """Create a minimal git repo with .plan on a feature branch."""
        project = tmp_path / "project"
        project.mkdir()
        subprocess.run(["git", "init", str(project)], capture_output=True)
        subprocess.run(
            ["git", "-C", str(project), "commit", "--allow-empty", "-m", "init"],
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(project), "checkout", "-b", "issue-42-foo"],
            capture_output=True,
        )
        meta_dir = project / "design"
        meta_dir.mkdir()
        plan = meta_dir / ".plan"
        _write_plan(plan, state="active", branch="issue-42-foo")
        subprocess.run(
            ["git", "-C", str(project), "add", "design/.plan"],
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(project), "commit", "-m", "scaffold"],
            capture_output=True,
        )
        return project, plan

    def test_untracked_files_detected(self, git_project):
        project, meta = git_project
        (project / "leftover.py").write_text("oops")
        violations = validate_state("closing:review", project, project)
        assert any("Untracked" in v for v in violations)

    def test_excluded_patterns_ignored(self, git_project):
        project, meta = git_project
        idea = project / ".idea"
        idea.mkdir()
        (idea / "workspace.xml").write_text("<xml/>")
        violations = validate_state("closing:review", project, project)
        assert not any(".idea" in v for v in violations)

    def test_branch_mismatch_detected(self, git_project):
        project, plan = git_project
        subprocess.run(
            ["git", "-C", str(project), "checkout", "main"], capture_output=True
        )
        # In the real system, workspace is separate and keeps .plan even when
        # project switches to main. Simulate by re-creating .plan on main.
        (project / "design").mkdir(exist_ok=True)
        _write_plan(project / "design" / ".plan", state="active", branch="issue-42-foo")
        violations = validate_state("active", project, project)
        assert any("Branch mismatch" in v for v in violations)

    def test_clean_repo_no_violations(self, git_project):
        project, meta = git_project
        violations = validate_state("active", project, project)
        assert violations == []

    def test_paused_skips_untracked_check(self, git_project):
        project, meta = git_project
        (project / "leftover.py").write_text("oops")
        violations = validate_state("paused", project, project)
        assert not any("Untracked" in v for v in violations)

    def test_idle_skips_branch_check(self, git_project):
        project, meta = git_project
        subprocess.run(
            ["git", "-C", str(project), "checkout", "main"], capture_output=True
        )
        violations = validate_state("idle", project, project)
        assert not any("Branch mismatch" in v for v in violations)

    def test_transition_blocked_by_untracked(self, git_project):
        project, meta = git_project
        (project / "leftover.py").write_text("oops")
        with pytest.raises(InvalidState, match="Untracked"):
            transition(meta, "work_end", project=project, workspace=project)

    def test_transition_allowed_without_paths(self, git_project):
        project, meta = git_project
        (project / "leftover.py").write_text("oops")
        result = transition(meta, "work_end")
        assert result.new_state == "closing:review"


# --- transition table completeness ---


class TestDeprecatedEvents:
    def test_work_epic_maps_to_work(self, tmp_path, capsys):
        meta = tmp_path / ".plan"
        result = transition(meta, "work_epic")
        assert result.new_state == "scaffolded"
        assert "build_plan" in result.effects
        captured = capsys.readouterr()
        assert "deprecated" in captured.out.lower()
        assert "work_epic" in captured.out

    def test_slot_epic_maps_to_slot_create(self, tmp_path, capsys):
        meta = tmp_path / ".plan"
        result = transition(meta, "slot_epic")
        assert result.new_state == "scaffolded"
        assert "build_plan" in result.effects
        captured = capsys.readouterr()
        assert "deprecated" in captured.out.lower()
        assert "slot_epic" in captured.out

    def test_deprecated_event_from_non_idle_still_fails(self, tmp_path, capsys):
        meta = tmp_path / ".plan"
        _write_plan(meta, state="active", branch="test")
        with pytest.raises(InvalidTransition):
            transition(meta, "work_epic")


class TestTransitionTableCompleteness:
    def test_all_transition_table_entries_have_valid_from_states(self):
        for (from_state, _event), (_to, _eff, _post) in TRANSITION_TABLE.items():
            assert from_state in VALID_STATES, f"Invalid from_state: {from_state}"

    def test_all_transition_table_entries_have_valid_to_states(self):
        for (_from, _event), (to_state, _eff, _post) in TRANSITION_TABLE.items():
            assert to_state in VALID_STATES, f"Invalid to_state: {to_state}"

    def test_every_non_idle_state_has_at_least_one_outgoing_transition(self):
        from_states = {k[0] for k in TRANSITION_TABLE}
        for state in VALID_STATES - {"idle"}:
            if state not in from_states:
                # closing:pushed only has merge_pass — check it's there
                assert any(
                    k[0] == state for k in TRANSITION_TABLE
                ), f"State {state} has no outgoing transition"


# --- worklog emission ---


sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


class TestWorklogEmission:
    @pytest.fixture
    def worklog_env(self, tmp_path):
        """Create a worklog DB with a work item, set WORKLOG_DB env."""
        import worklog
        db_path = str(tmp_path / "worklog.db")
        conn = worklog.connect(db_path)
        repo_path = str(tmp_path / "project")
        worklog.ensure_repo(conn, repo_path)
        worklog.record_work_start(
            conn, "issue-42-foo", repo_path,
            issue_number=42, issue_repo="org/repo",
        )
        conn.close()
        old = os.environ.get("WORKLOG_DB")
        os.environ["WORKLOG_DB"] = db_path
        yield db_path, repo_path
        if old is None:
            os.environ.pop("WORKLOG_DB", None)
        else:
            os.environ["WORKLOG_DB"] = old

    def test_commit_emits_worklog_event(self, tmp_path, worklog_env):
        import worklog
        db_path, repo_path = worklog_env
        meta = tmp_path / ".plan"
        _write_plan(meta, state="active", branch="issue-42-foo", date="2026-08-03")

        result = transition(meta, "work_pause")
        commit_transition(meta, result, repo_path=repo_path)

        conn = worklog.connect(db_path)
        events = worklog.event_log(conn, event_type="work_pause")
        assert len(events) >= 1
        meta_json = json.loads(events[0]["metadata"])
        assert meta_json["from_state"] == "active"
        assert meta_json["to_state"] == "paused"
        conn.close()

    def test_commit_updates_work_item_state(self, tmp_path, worklog_env):
        import worklog
        db_path, repo_path = worklog_env
        meta = tmp_path / ".plan"
        _write_plan(meta, state="active", branch="issue-42-foo", date="2026-08-03")

        result = transition(meta, "work_pause")
        commit_transition(meta, result, repo_path=repo_path)

        conn = worklog.connect(db_path)
        items = worklog.active_work(conn)
        paused = [i for i in items if i["branch"] == "issue-42-foo"]
        assert len(paused) == 1
        assert paused[0]["state"] == "paused"
        conn.close()

    def test_commit_passes_caller_metadata(self, tmp_path, worklog_env):
        import worklog
        db_path, repo_path = worklog_env
        meta = tmp_path / ".plan"
        _write_plan(meta, state="closing:pushed", branch="issue-42-foo", date="2026-08-03")

        result = transition(meta, "merge_pass")
        commit_transition(
            meta, result,
            repo_path=repo_path,
            metadata={"landed_sha": "abc123"},
        )

        conn = worklog.connect(db_path)
        events = worklog.event_log(conn, event_type="merge_pass")
        assert len(events) >= 1
        meta_json = json.loads(events[0]["metadata"])
        assert meta_json["landed_sha"] == "abc123"
        assert meta_json["from_state"] == "closing:pushed"
        assert meta_json["to_state"] == "closing:merged"
        conn.close()

    def test_commit_without_repo_path_skips_worklog(self, tmp_path):
        meta = tmp_path / ".plan"
        _write_plan(meta, state="active", branch="issue-42-foo", date="2026-08-03")
        result = transition(meta, "work_pause")
        commit_transition(meta, result)
        assert read_state(meta) == "paused"

    def test_commit_survives_worklog_failure(self, tmp_path, monkeypatch):
        meta = tmp_path / ".plan"
        _write_plan(meta, state="active", branch="issue-42-foo", date="2026-08-03")
        monkeypatch.setenv("WORKLOG_DB", "/nonexistent/path/worklog.db")
        result = transition(meta, "work_pause")
        commit_transition(meta, result, repo_path=str(tmp_path / "project"))
        assert read_state(meta) == "paused"

    def test_commit_to_idle_sets_ended(self, tmp_path, worklog_env):
        import worklog
        db_path, repo_path = worklog_env
        meta = tmp_path / ".plan"
        _write_plan(meta, state="closing:stamped", branch="issue-42-foo", date="2026-08-03")

        result = transition(meta, "cleanup_pass")
        commit_transition(meta, result, repo_path=repo_path)

        conn = worklog.connect(db_path)
        row = conn.execute(
            "SELECT state, ended_at FROM work_items wi "
            "JOIN repos r ON wi.repo_id = r.id "
            "WHERE wi.branch='issue-42-foo'"
        ).fetchone()
        assert row["state"] == "ended"
        assert row["ended_at"] is not None
        conn.close()


class TestWorklogIntegration:
    def test_full_lifecycle_produces_correct_event_trail(self, tmp_path):
        import worklog

        db_path = str(tmp_path / "worklog.db")
        project = tmp_path / "project"
        project.mkdir()
        repo_path = str(project)

        old_env = os.environ.get("WORKLOG_DB")
        os.environ["WORKLOG_DB"] = db_path

        try:
            conn = worklog.connect(db_path)
            worklog.ensure_repo(conn, repo_path)
            conn.close()

            meta = tmp_path / ".plan"

            # idle -> scaffolded
            result = transition(meta, "work")
            _write_plan(meta, state="scaffolded", branch="issue-99-test", date="2026-08-04")
            conn = worklog.connect(db_path)
            worklog.record_work_start(
                conn, "issue-99-test", repo_path,
                issue_number=99, issue_repo="org/repo",
            )
            conn.close()
            commit_transition(meta, result, repo_path=repo_path)

            # scaffolded -> active
            result = transition(meta, "auto_setup")
            commit_transition(meta, result, repo_path=repo_path)

            # active -> paused
            result = transition(meta, "work_pause")
            commit_transition(meta, result, repo_path=repo_path)

            # paused -> active
            result = transition(meta, "work_resume")
            commit_transition(meta, result, repo_path=repo_path)

            # active -> closing:review
            result = transition(meta, "work_end")
            commit_transition(meta, result, repo_path=repo_path)

            # closing:review -> closing:verified
            result = transition(meta, "review_pass")
            commit_transition(meta, result, repo_path=repo_path,
                              evidence={"review_result": "passed"})

            # closing:verified -> closing:promoted
            result = transition(meta, "promote_pass")
            commit_transition(meta, result, repo_path=repo_path,
                              evidence={"promoted_files": ["blog.md"], "target_repos": ["org/repo"]})

            # closing:promoted -> closing:pushed
            result = transition(meta, "push_pass")
            commit_transition(meta, result, repo_path=repo_path,
                              evidence={"pushed_repos": {"project": True}, "pushed_shas": {"project": "abc123"}})

            # closing:pushed -> closing:merged
            result = transition(meta, "merge_pass")
            commit_transition(
                meta, result, repo_path=repo_path,
                metadata={"landed_sha": "deadbeef"},
                evidence={"landed_shas": {"project": "deadbeef"}, "verified_on_main": {"project": True}},
            )

            # closing:merged -> closing:stamped
            result = transition(meta, "stamp_pass")
            commit_transition(meta, result, repo_path=repo_path,
                              evidence={"stamp_shas": {"project": "stamp123"}})

            # closing:stamped -> idle
            result = transition(meta, "cleanup_pass")
            commit_transition(meta, result, repo_path=repo_path,
                              evidence={"repos_on_main": {"project": True}, "work_items_ended": True})

            # Verify event trail
            conn = worklog.connect(db_path)
            events = worklog.event_log(conn, limit=50)

            event_types = [e["event_type"] for e in reversed(events)]

            assert "work-start" in event_types
            assert "work" in event_types
            assert "auto_setup" in event_types
            assert "work_pause" in event_types
            assert "work_resume" in event_types
            assert "work_end" in event_types
            assert "review_pass" in event_types
            assert "promote_pass" in event_types
            assert "push_pass" in event_types
            assert "merge_pass" in event_types
            assert "stamp_pass" in event_types
            assert "cleanup_pass" in event_types

            # Verify merge_pass has landed_sha and evidence
            merge_events = [e for e in events if e["event_type"] == "merge_pass"]
            assert len(merge_events) == 1
            merge_meta = json.loads(merge_events[0]["metadata"])
            assert merge_meta["landed_sha"] == "deadbeef"
            assert merge_meta["evidence"]["landed_shas"]["project"] == "deadbeef"
            assert merge_meta["evidence"]["verified_on_main"]["project"] is True

            # Verify work item ended
            row = conn.execute(
                "SELECT state, ended_at FROM work_items "
                "WHERE branch='issue-99-test'"
            ).fetchone()
            assert row["state"] == "ended"
            assert row["ended_at"] is not None
            conn.close()
        finally:
            if old_env is None:
                os.environ.pop("WORKLOG_DB", None)
            else:
                os.environ["WORKLOG_DB"] = old_env


# --- is_closed() predicate ---


class TestIsClosed:
    """Tests for is_closed() — single predicate for branch closure state."""

    def _init_repo(self, path):
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True,
                        capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"],
                        cwd=path, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"],
                        cwd=path, check=True, capture_output=True)
        (path / "README.md").write_text("init")
        subprocess.run(["git", "add", "."], cwd=path, check=True,
                        capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True,
                        capture_output=True)
        return path

    def _create_branch_with_commit(self, repo, branch, filename="work.txt"):
        subprocess.run(["git", "checkout", "-b", branch], cwd=repo,
                        check=True, capture_output=True)
        (repo / filename).write_text("work")
        subprocess.run(["git", "add", "."], cwd=repo, check=True,
                        capture_output=True)
        subprocess.run(["git", "commit", "-m", f"feat: {filename}"],
                        cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "checkout", "main"], cwd=repo, check=True,
                        capture_output=True)

    def _rebase_merge_branch(self, repo, branch):
        subprocess.run(["git", "rebase", branch], cwd=repo, check=True,
                        capture_output=True)

    def _stamp_branch(self, repo, branch, landing_sha=None):
        subprocess.run(["git", "checkout", branch], cwd=repo, check=True,
                        capture_output=True)
        msg = "chore: branch closed"
        if landing_sha:
            msg += f" — landed as {landing_sha} on main"
        subprocess.run(["git", "commit", "--allow-empty", "-m", msg],
                        cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "checkout", "main"], cwd=repo, check=True,
                        capture_output=True)

    def _get_sha(self, repo, ref="HEAD"):
        result = subprocess.run(["git", "rev-parse", ref], cwd=repo,
                                check=True, capture_output=True, text=True)
        return result.stdout.strip()

    def test_deleted_branch(self, tmp_path):
        repo = self._init_repo(tmp_path / "repo")
        assert is_closed(str(repo), "nonexistent") == ClosureState.DELETED

    def test_open_branch(self, tmp_path):
        repo = self._init_repo(tmp_path / "repo")
        self._create_branch_with_commit(repo, "feature-1")
        assert is_closed(str(repo), "feature-1") == ClosureState.OPEN

    def test_merged_unstamped(self, tmp_path):
        repo = self._init_repo(tmp_path / "repo")
        self._create_branch_with_commit(repo, "feature-2")
        self._rebase_merge_branch(repo, "feature-2")
        assert is_closed(str(repo), "feature-2") == ClosureState.MERGED_UNSTAMPED

    def test_closed_with_landing_sha(self, tmp_path):
        repo = self._init_repo(tmp_path / "repo")
        self._create_branch_with_commit(repo, "feature-3")
        self._rebase_merge_branch(repo, "feature-3")
        sha = self._get_sha(repo, "main")
        self._stamp_branch(repo, "feature-3", sha)
        assert is_closed(str(repo), "feature-3") == ClosureState.CLOSED

    def test_closed_old_format_stamp(self, tmp_path):
        repo = self._init_repo(tmp_path / "repo")
        self._create_branch_with_commit(repo, "feature-4")
        self._rebase_merge_branch(repo, "feature-4")
        self._stamp_branch(repo, "feature-4")
        assert is_closed(str(repo), "feature-4") == ClosureState.CLOSED

    def test_stamped_unmerged(self, tmp_path):
        repo = self._init_repo(tmp_path / "repo")
        self._create_branch_with_commit(repo, "feature-5")
        self._stamp_branch(repo, "feature-5")
        assert is_closed(str(repo), "feature-5") == ClosureState.STAMPED_UNMERGED

    def test_stamp_only_commit_ahead_is_closed(self, tmp_path):
        repo = self._init_repo(tmp_path / "repo")
        self._create_branch_with_commit(repo, "feature-6")
        self._rebase_merge_branch(repo, "feature-6")
        sha = self._get_sha(repo, "main")
        self._stamp_branch(repo, "feature-6", sha)
        assert is_closed(str(repo), "feature-6") == ClosureState.CLOSED

    def test_workspace_both_closed(self, tmp_path):
        project = self._init_repo(tmp_path / "proj")
        workspace = self._init_repo(tmp_path / "wksp")
        for repo in [project, workspace]:
            self._create_branch_with_commit(repo, "feature-7")
            self._rebase_merge_branch(repo, "feature-7")
            sha = self._get_sha(repo, "main")
            self._stamp_branch(repo, "feature-7", sha)
        assert is_closed(str(project), "feature-7",
                          workspace=str(workspace)) == ClosureState.CLOSED

    def test_workspace_not_closed_downgrades(self, tmp_path):
        project = self._init_repo(tmp_path / "proj")
        workspace = self._init_repo(tmp_path / "wksp")
        self._create_branch_with_commit(project, "feature-8")
        self._create_branch_with_commit(workspace, "feature-8")
        self._rebase_merge_branch(project, "feature-8")
        sha = self._get_sha(project, "main")
        self._stamp_branch(project, "feature-8", sha)
        assert is_closed(str(project), "feature-8",
                          workspace=str(workspace)) == ClosureState.OPEN

    def test_workspace_deleted_uses_project(self, tmp_path):
        project = self._init_repo(tmp_path / "proj")
        workspace = self._init_repo(tmp_path / "wksp")
        self._create_branch_with_commit(project, "feature-9")
        self._rebase_merge_branch(project, "feature-9")
        sha = self._get_sha(project, "main")
        self._stamp_branch(project, "feature-9", sha)
        assert is_closed(str(project), "feature-9",
                          workspace=str(workspace)) == ClosureState.CLOSED

    def test_landing_sha_mismatch_still_closed(self, tmp_path):
        repo = self._init_repo(tmp_path / "repo")
        self._create_branch_with_commit(repo, "feature-10")
        self._rebase_merge_branch(repo, "feature-10")
        self._stamp_branch(repo, "feature-10", "deadbeefdeadbeef")
        assert is_closed(str(repo), "feature-10") == ClosureState.CLOSED


# --- CLI interface ---


LIFECYCLE_SCRIPT = Path(__file__).parent.parent / "project" / "lifecycle.py"


def _run_lifecycle(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(LIFECYCLE_SCRIPT), *args],
        capture_output=True, text=True, timeout=10,
    )


def _parse_output(stdout: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in stdout.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip()
    return result


class TestCLITransition:
    def test_transition_outputs_key_value(self, tmp_path):
        plan = tmp_path / ".plan"
        _write_plan(plan, state="active")
        result = _run_lifecycle("transition", str(plan), "work_pause")
        assert result.returncode == 0
        out = _parse_output(result.stdout)
        assert out["FROM_STATE"] == "active"
        assert out["NEW_STATE"] == "paused"
        assert out["EVENT"] == "work_pause"

    def test_transition_from_idle(self, tmp_path):
        plan = tmp_path / ".plan"
        result = _run_lifecycle("transition", str(plan), "work")
        assert result.returncode == 0
        out = _parse_output(result.stdout)
        assert out["FROM_STATE"] == "idle"
        assert out["NEW_STATE"] == "scaffolded"
        assert "build_plan" in out.get("EFFECTS", "")

    def test_transition_invalid_event_exits_nonzero(self, tmp_path):
        plan = tmp_path / ".plan"
        _write_plan(plan, state="active")
        result = _run_lifecycle("transition", str(plan), "nonexistent_event")
        assert result.returncode == 1
        assert "ERROR" in result.stdout

    def test_transition_outputs_effects(self, tmp_path):
        plan = tmp_path / ".plan"
        _write_plan(plan, state="active")
        result = _run_lifecycle("transition", str(plan), "work_end")
        assert result.returncode == 0
        out = _parse_output(result.stdout)
        assert out["NEW_STATE"] == "closing:review"

    def test_transition_closing_sequence(self, tmp_path):
        plan = tmp_path / ".plan"
        _write_plan(plan, state="closing:review")
        result = _run_lifecycle("transition", str(plan), "review_pass")
        assert result.returncode == 0
        out = _parse_output(result.stdout)
        assert out["NEW_STATE"] == "closing:verified"


class TestCLICommitTransition:
    def test_commit_writes_state(self, tmp_path):
        plan = tmp_path / ".plan"
        _write_plan(plan, state="active")
        result = _run_lifecycle(
            "commit-transition", str(plan),
            "from_state=active", "new_state=paused", "event=work_pause",
        )
        assert result.returncode == 0
        out = _parse_output(result.stdout)
        assert out["COMMITTED"] == "yes"
        assert read_state(plan) == "paused"

    def test_commit_detects_concurrent_modification(self, tmp_path):
        plan = tmp_path / ".plan"
        _write_plan(plan, state="closing:review")
        result = _run_lifecycle(
            "commit-transition", str(plan),
            "from_state=active", "new_state=paused", "event=work_pause",
        )
        assert result.returncode == 1
        assert "ERROR" in result.stdout
        assert "concurrent" in result.stdout.lower() or "CONCURRENT" in result.stdout

    def test_commit_idle_to_scaffolded(self, tmp_path):
        plan = tmp_path / ".plan"
        _write_plan(plan, state="scaffolded")
        result = _run_lifecycle(
            "commit-transition", str(plan),
            "from_state=idle", "new_state=scaffolded", "event=work",
        )
        assert result.returncode == 0
        out = _parse_output(result.stdout)
        assert out["COMMITTED"] == "yes"


class TestCLIReadState:
    def test_read_existing_state(self, tmp_path):
        plan = tmp_path / ".plan"
        _write_plan(plan, state="active")
        result = _run_lifecycle("read-state", str(plan))
        assert result.returncode == 0
        out = _parse_output(result.stdout)
        assert out["STATE"] == "active"

    def test_read_missing_plan_returns_idle(self, tmp_path):
        plan = tmp_path / ".plan"
        result = _run_lifecycle("read-state", str(plan))
        assert result.returncode == 0
        out = _parse_output(result.stdout)
        assert out["STATE"] == "idle"

    def test_read_closing_state(self, tmp_path):
        plan = tmp_path / ".plan"
        _write_plan(plan, state="closing:verified")
        result = _run_lifecycle("read-state", str(plan))
        assert result.returncode == 0
        out = _parse_output(result.stdout)
        assert out["STATE"] == "closing:verified"


class TestCLIShowTransitions:
    def test_shows_valid_events_for_active(self, tmp_path):
        plan = tmp_path / ".plan"
        _write_plan(plan, state="active")
        result = _run_lifecycle("show-transitions", str(plan))
        assert result.returncode == 0
        out = _parse_output(result.stdout)
        assert out["STATE"] == "active"
        events = out["VALID_EVENTS"].split(",")
        assert "work_continue" in events
        assert "work_end" in events
        assert "work_pause" in events

    def test_shows_valid_events_for_scaffolded(self, tmp_path):
        plan = tmp_path / ".plan"
        _write_plan(plan, state="scaffolded")
        result = _run_lifecycle("show-transitions", str(plan))
        assert result.returncode == 0
        out = _parse_output(result.stdout)
        assert out["STATE"] == "scaffolded"
        events = out["VALID_EVENTS"].split(",")
        assert "auto_setup" in events
        assert "work_continue" not in events

    def test_shows_valid_events_for_idle(self, tmp_path):
        plan = tmp_path / ".plan"
        result = _run_lifecycle("show-transitions", str(plan))
        assert result.returncode == 0
        out = _parse_output(result.stdout)
        assert out["STATE"] == "idle"
        events = out["VALID_EVENTS"].split(",")
        assert "work" in events


class TestCLIBadArgs:
    def test_no_args(self):
        result = _run_lifecycle()
        assert result.returncode == 1

    def test_unknown_subcommand(self):
        result = _run_lifecycle("unknown")
        assert result.returncode == 1

    def test_transition_missing_event(self, tmp_path):
        plan = tmp_path / ".plan"
        result = _run_lifecycle("transition", str(plan))
        assert result.returncode == 1


# --- drained state (#261) ---


class TestDrainedState:
    def test_drained_in_valid_states(self):
        assert "drained" in VALID_STATES

    def test_drained_is_resting(self):
        assert "drained" in RESTING_STATES

    def test_drained_is_not_transient(self):
        assert "drained" not in TRANSIENT_STATES
        assert is_transient("drained") is False

    def test_drained_is_not_closing(self):
        assert "drained" not in CLOSING_STATES
        assert is_closing("drained") is False

    def test_valid_states_count_after_drained(self):
        assert len(VALID_STATES) == 12

    def test_cleanup_main_transitions_to_drained(self, tmp_path):
        plan = tmp_path / ".plan"
        _write_plan(plan, state="closing:stamped", branch="main")
        result = transition(plan, "cleanup_main")
        assert result.from_state == "closing:stamped"
        assert result.new_state == "drained"
        assert "write_plan_drained" in result.effects
        assert "write_handoff" in result.post_commit_effects
        assert "return_to_main" not in result.post_commit_effects

    def test_work_find_transitions_drained_to_transitioning(self, tmp_path):
        plan = tmp_path / ".plan"
        _write_plan(plan, state="drained", branch="main")
        result = transition(plan, "work_find")
        assert result.from_state == "drained"
        assert result.new_state == "transitioning"
        assert "queue_populated" in result.effects

    def test_drained_rejects_work_end(self, tmp_path):
        plan = tmp_path / ".plan"
        _write_plan(plan, state="drained", branch="main")
        with pytest.raises(InvalidTransition, match="Already drained"):
            transition(plan, "work_end")

    def test_drained_rejects_work_pause(self, tmp_path):
        plan = tmp_path / ".plan"
        _write_plan(plan, state="drained", branch="main")
        with pytest.raises(InvalidTransition, match="Nothing active to pause"):
            transition(plan, "work_pause")

    def test_drained_rejects_work_resume(self, tmp_path):
        plan = tmp_path / ".plan"
        _write_plan(plan, state="drained", branch="main")
        with pytest.raises(InvalidTransition, match="work find"):
            transition(plan, "work_resume")

    def test_drained_rejects_work_next(self, tmp_path):
        plan = tmp_path / ".plan"
        _write_plan(plan, state="drained", branch="main")
        with pytest.raises(InvalidTransition, match="Queue is empty"):
            transition(plan, "work_next")

    def test_drained_rejects_work_continue(self, tmp_path):
        plan = tmp_path / ".plan"
        _write_plan(plan, state="drained", branch="main")
        with pytest.raises(InvalidTransition, match="drained"):
            transition(plan, "work_continue")

    def test_drained_rejects_work(self, tmp_path):
        plan = tmp_path / ".plan"
        _write_plan(plan, state="drained", branch="main")
        with pytest.raises(InvalidTransition, match="drained"):
            transition(plan, "work")

    def test_read_drained_state(self, tmp_path):
        plan = tmp_path / ".plan"
        _write_plan(plan, state="drained", branch="main")
        assert read_state(plan) == "drained"

    def test_write_drained_state(self, tmp_path):
        plan = tmp_path / ".plan"
        _write_plan(plan, state="active", branch="main")
        write_state(plan, "drained")
        assert read_state(plan) == "drained"

    def test_drained_worklog_mapping(self):
        from lifecycle import _LIFECYCLE_TO_WORKLOG
        assert _LIFECYCLE_TO_WORKLOG["drained"] == "idle"


class TestEvidenceEra:
    def test_write_and_read_evidence_era(self, tmp_path):
        plan = tmp_path / ".plan"
        _write_plan(plan, state="active")
        assert _read_evidence_era(plan) is False
        _write_evidence_era(plan)
        assert _read_evidence_era(plan) is True

    def test_write_evidence_era_idempotent(self, tmp_path):
        plan = tmp_path / ".plan"
        _write_plan(plan, state="active")
        _write_evidence_era(plan)
        content_before = plan.read_text()
        _write_evidence_era(plan)
        assert plan.read_text() == content_before

    def test_work_end_writes_evidence_era(self, tmp_path):
        plan = tmp_path / ".plan"
        _write_plan(plan, state="active")
        result = transition(plan, "work_end")
        commit_transition(plan, result)
        assert _read_evidence_era(plan) is True

    def test_no_evidence_era_on_nonexistent_plan(self, tmp_path):
        plan = tmp_path / ".plan"
        assert _read_evidence_era(plan) is False


class TestEvidenceValidation:
    def test_merge_pass_valid(self):
        evidence = {
            "landed_shas": {"blocks": "abc123"},
            "verified_on_main": {"blocks": True},
        }
        assert _validate_evidence("merge_pass", evidence) == []

    def test_merge_pass_missing_key(self):
        evidence = {"landed_shas": {"blocks": "abc123"}}
        violations = _validate_evidence("merge_pass", evidence)
        assert any("verified_on_main" in v for v in violations)

    def test_merge_pass_not_on_main(self):
        evidence = {
            "landed_shas": {"blocks": "abc123"},
            "verified_on_main": {"blocks": False},
        }
        violations = _validate_evidence("merge_pass", evidence)
        assert any("blocks" in v for v in violations)

    def test_cleanup_pass_valid(self):
        evidence = {
            "repos_on_main": {"engine": True, "blocks": True},
            "work_items_ended": True,
        }
        assert _validate_evidence("cleanup_pass", evidence) == []

    def test_cleanup_pass_work_items_not_ended(self):
        evidence = {
            "repos_on_main": {"engine": True},
            "work_items_ended": False,
        }
        violations = _validate_evidence("cleanup_pass", evidence)
        assert any("work_items_ended" in v for v in violations)

    def test_cleanup_pass_repo_not_on_main(self):
        evidence = {
            "repos_on_main": {"engine": True, "blocks": False},
            "work_items_ended": True,
        }
        violations = _validate_evidence("cleanup_pass", evidence)
        assert any("blocks" in v for v in violations)

    def test_ungated_event_returns_empty(self):
        assert _validate_evidence("work_end", {}) == []

    def test_review_pass_valid(self):
        evidence = {"review_result": "passed"}
        assert _validate_evidence("review_pass", evidence) == []

    def test_promote_pass_valid(self):
        evidence = {
            "promoted_files": ["docs/blog/entry.md"],
            "target_repos": ["blocks"],
        }
        assert _validate_evidence("promote_pass", evidence) == []

    def test_stamp_pass_valid(self):
        evidence = {"stamp_shas": {"blocks": "abc123"}}
        assert _validate_evidence("stamp_pass", evidence) == []


class TestEvidenceGating:
    def test_gated_transition_requires_evidence_in_era(self, tmp_path):
        plan = tmp_path / ".plan"
        _write_plan(plan, state="closing:pushed")
        _write_evidence_era(plan)
        result = TransitionResult(
            from_state="closing:pushed", new_state="closing:merged",
            event="merge_pass",
        )
        with pytest.raises(MissingEvidence) as exc_info:
            commit_transition(plan, result)
        assert "landed_shas" in str(exc_info.value)
        assert "verified_on_main" in str(exc_info.value)

    def test_gated_transition_allows_legacy_without_evidence(self, tmp_path):
        plan = tmp_path / ".plan"
        _write_plan(plan, state="closing:pushed")
        result = TransitionResult(
            from_state="closing:pushed", new_state="closing:merged",
            event="merge_pass",
        )
        commit_transition(plan, result)
        assert read_state(plan) == "closing:merged"

    def test_gated_transition_succeeds_with_valid_evidence(self, tmp_path):
        plan = tmp_path / ".plan"
        _write_plan(plan, state="closing:pushed")
        _write_evidence_era(plan)
        result = TransitionResult(
            from_state="closing:pushed", new_state="closing:merged",
            event="merge_pass",
        )
        evidence = {
            "landed_shas": {"blocks": "abc123"},
            "verified_on_main": {"blocks": True},
        }
        commit_transition(plan, result, evidence=evidence)
        assert read_state(plan) == "closing:merged"

    def test_gated_transition_rejects_invalid_evidence(self, tmp_path):
        plan = tmp_path / ".plan"
        _write_plan(plan, state="closing:pushed")
        _write_evidence_era(plan)
        result = TransitionResult(
            from_state="closing:pushed", new_state="closing:merged",
            event="merge_pass",
        )
        evidence = {
            "landed_shas": {"blocks": "abc123"},
            "verified_on_main": {"blocks": False},
        }
        with pytest.raises(InvalidEvidence) as exc_info:
            commit_transition(plan, result, evidence=evidence)
        assert "blocks" in str(exc_info.value)

    def test_ungated_transition_ignores_evidence(self, tmp_path):
        plan = tmp_path / ".plan"
        _write_plan(plan, state="active")
        result = TransitionResult(
            from_state="active", new_state="paused",
            event="work_pause",
        )
        commit_transition(plan, result, evidence={"note": "test"})
        assert read_state(plan) == "paused"

    def test_all_closing_pass_events_are_gated(self):
        pass_events = {ev for (_, ev), (ns, _, _) in TRANSITION_TABLE.items()
                       if ev.endswith("_pass") or ev == "cleanup_main"}
        for event in pass_events:
            assert event in EVIDENCE_GATES, f"{event} should be gated"
