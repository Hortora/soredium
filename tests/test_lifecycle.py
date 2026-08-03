#!/usr/bin/env python3
"""Tests for project/lifecycle.py — the lifecycle state machine core."""

import subprocess
import sys
from pathlib import Path

import pytest

LIFECYCLE = Path(__file__).parent.parent / "project" / "lifecycle.py"

sys.path.insert(0, str(LIFECYCLE.parent))
from lifecycle import (
    CLOSING_STATES,
    RESTING_STATES,
    TRANSITION_TABLE,
    TRANSIENT_STATES,
    VALID_STATES,
    ConcurrentModification,
    CorruptedState,
    InvalidState,
    InvalidTransition,
    StateError,
    TransitionResult,
    can_transition,
    commit_transition,
    is_closing,
    is_transient,
    migrate_legacy_paused,
    read_state,
    transition,
    validate_state,
    write_state,
)


@pytest.fixture
def tmp_meta(tmp_path):
    meta = tmp_path / ".meta"
    meta.write_text("branch: issue-42-foo\nstate: active\ndate: 2026-08-03\n")
    return meta


# --- State constants and classification ---


class TestStateConstants:
    def test_valid_states_count(self):
        assert len(VALID_STATES) == 11

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
        meta = tmp_path / ".meta"
        meta.write_text("branch: x\nstate: closing:pushed\ndate: 2026-08-03\n")
        assert read_state(meta) == "closing:pushed"

    def test_read_all_valid_states(self, tmp_path):
        meta = tmp_path / ".meta"
        for state in VALID_STATES - {"idle"}:
            meta.write_text(f"branch: x\nstate: {state}\ndate: 2026-08-03\n")
            assert read_state(meta) == state

    def test_no_meta_returns_none(self, tmp_path):
        assert read_state(tmp_path / ".meta") is None

    def test_missing_state_field_returns_active(self, tmp_path):
        meta = tmp_path / ".meta"
        meta.write_text("branch: issue-42-foo\ndate: 2026-08-03\n")
        assert read_state(meta) == "active"

    def test_unknown_state_raises_corrupted(self, tmp_path):
        meta = tmp_path / ".meta"
        meta.write_text("branch: x\nstate: bogus\ndate: 2026-08-03\n")
        with pytest.raises(CorruptedState):
            read_state(meta)

    def test_truncated_closing_state_raises_corrupted(self, tmp_path):
        meta = tmp_path / ".meta"
        meta.write_text("branch: x\nstate: closing:pro\ndate: 2026-08-03\n")
        with pytest.raises(CorruptedState):
            read_state(meta)

    def test_write_updates_existing(self, tmp_meta):
        write_state(tmp_meta, "closing:review")
        assert read_state(tmp_meta) == "closing:review"
        assert tmp_meta.read_text().count("state:") == 1

    def test_write_appends_to_legacy(self, tmp_path):
        meta = tmp_path / ".meta"
        meta.write_text("branch: issue-42-foo\ndate: 2026-08-03\n")
        write_state(meta, "scaffolded")
        content = meta.read_text()
        assert "state: scaffolded" in content
        assert content.index("branch:") < content.index("state:")

    def test_write_appends_at_end_if_no_branch(self, tmp_path):
        meta = tmp_path / ".meta"
        meta.write_text("date: 2026-08-03\n")
        write_state(meta, "active")
        assert "state: active" in meta.read_text()

    def test_write_is_atomic(self, tmp_meta):
        write_state(tmp_meta, "closing:merged")
        assert not (tmp_meta.parent / ".meta.tmp").exists()

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
            ("idle", "work", "scaffolded", ["create_branch", "write_meta"]),
            ("idle", "work_epic", "scaffolded", ["create_branch", "write_meta", "write_epic"]),
            ("idle", "slot_create", "scaffolded", ["create_slot", "write_meta"]),
            ("idle", "slot_epic", "scaffolded", ["create_slot", "write_meta", "write_slot_epic"]),
            ("scaffolded", "auto_setup", "active", ["garden_search", "load_specs", "check_protocols", "check_intellij"]),
            ("active", "work_next", "transitioning", ["advance_issue", "update_meta", "tick_github"]),
            ("transitioning", "auto_refresh", "active", ["garden_search", "load_specs", "check_protocols"]),
            ("active", "work_pause", "paused", ["wip_commit"]),
            ("paused", "work_resume", "active", ["pop_stack", "reset_wip", "context_resume"]),
            ("active", "work_end", "closing:review", ["pre_close_sweep"]),
            ("closing:review", "review_pass", "closing:verified", ["record_review"]),
            ("closing:verified", "promote_pass", "closing:promoted", ["write_promotion_stamp"]),
            ("closing:promoted", "push_pass", "closing:pushed", []),
            ("closing:pushed", "merge_pass", "closing:merged", ["verify_content_landed"]),
            ("closing:merged", "stamp_pass", "closing:stamped", ["write_stamp"]),
            ("closing:stamped", "cleanup_pass", "idle", ["write_epic_closed"]),
        ],
    )
    def test_valid_transition(self, from_state, event, expected_state, expected_effects, tmp_path):
        meta = tmp_path / ".meta"
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
        meta = tmp_path / ".meta"
        meta.write_text("branch: x\nstate: closing:stamped\ndate: 2026-08-03\n")
        result = transition(meta, "cleanup_pass")
        assert result.effects == ["write_epic_closed"]
        assert result.post_commit_effects == ["return_to_main", "write_handoff"]

    def test_standard_transitions_have_empty_post_commit(self, tmp_meta):
        result = transition(tmp_meta, "work_end")
        assert result.post_commit_effects == []

    @pytest.mark.parametrize("closing_state", ["closing:review", "closing:verified"])
    def test_abort_from_pre_artifact(self, closing_state, tmp_path):
        meta = tmp_path / ".meta"
        meta.write_text(f"branch: x\nstate: {closing_state}\ndate: 2026-08-03\n")
        result = transition(meta, "abort_close")
        assert result.new_state == "active"
        assert result.effects == ["clear_closing_markers"]

    @pytest.mark.parametrize(
        "closing_state",
        ["closing:promoted", "closing:pushed", "closing:merged", "closing:stamped"],
    )
    def test_abort_blocked_post_artifact(self, closing_state, tmp_path):
        meta = tmp_path / ".meta"
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
            ("active", "work_epic"),
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
            ("closing:review", "work_epic"),
            ("closing:verified", "review_pass"),
            ("closing:promoted", "promote_pass"),
            ("closing:pushed", "push_pass"),
        ],
    )
    def test_invalid_transition_raises(self, from_state, event, tmp_path):
        meta = tmp_path / ".meta"
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
        meta = tmp_path / ".meta"
        result = transition(meta, "work")
        meta.write_text("branch: issue-1-test\nstate: scaffolded\ndate: 2026-08-03\n")
        commit_transition(meta, result)
        assert read_state(meta) == "scaffolded"

    def test_commit_idle_to_scaffolded_fails_without_meta(self, tmp_path):
        meta = tmp_path / ".meta"
        result = transition(meta, "work")
        with pytest.raises(StateError):
            commit_transition(meta, result)

    def test_commit_to_idle_skips_write(self, tmp_path):
        meta = tmp_path / ".meta"
        meta.write_text("branch: x\nstate: closing:stamped\ndate: 2026-08-03\n")
        result = transition(meta, "cleanup_pass")
        commit_transition(meta, result)
        assert read_state(meta) == "closing:stamped"

    def test_commit_to_idle_checks_concurrent(self, tmp_path):
        meta = tmp_path / ".meta"
        meta.write_text("branch: x\nstate: closing:stamped\ndate: 2026-08-03\n")
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
        meta = tmp_path / ".meta"
        meta.write_text("branch: issue-42-foo\ndate: 2026-08-03\n")
        assert migrate_legacy_paused(meta) is True
        assert read_state(meta) == "paused"

    def test_no_op_if_already_paused(self, tmp_path):
        meta = tmp_path / ".meta"
        meta.write_text("branch: issue-42-foo\nstate: paused\ndate: 2026-08-03\n")
        assert migrate_legacy_paused(meta) is False

    def test_no_op_if_has_explicit_state(self, tmp_path):
        meta = tmp_path / ".meta"
        meta.write_text("branch: issue-42-foo\nstate: active\ndate: 2026-08-03\n")
        assert migrate_legacy_paused(meta) is False

    def test_no_op_if_no_meta(self, tmp_path):
        meta = tmp_path / ".meta"
        assert migrate_legacy_paused(meta) is False


# --- transition table completeness ---


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
