"""Tests for slot_state.py — central slot state management."""

import sys
from pathlib import Path

import pytest

SOREDIUM_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(SOREDIUM_ROOT / "work-slot"))
sys.path.insert(0, str(SOREDIUM_ROOT / "scripts"))

from slot_state import (
    VALID_TRANSITIONS,
    VISIBLE_STATES,
    InvalidTransition,
    audit_state,
    current_state,
    transition,
)
from slot_metadata import write_slot_md, parse_slot_md, set_slot_state


def _make_slot(tmp_path: Path, slot_num: int = 1,
               state: str = "active") -> Path:
    slot_dir = tmp_path / "slots" / str(slot_num)
    slot_dir.mkdir(parents=True)
    write_slot_md(
        slot_dir, slot_num, ["engine"],
        branch="issue-42-test", issue="42",
        issue_repo="org/repo", covers="42",
        context="test slot",
    )
    if state != "active":
        set_slot_state(slot_dir, state)
    return slot_dir


class TestCurrentState:

    def test_reads_active_from_new_slot(self, tmp_path):
        slot_dir = _make_slot(tmp_path)
        assert current_state(slot_dir) == "active"

    def test_reads_custom_state(self, tmp_path):
        slot_dir = _make_slot(tmp_path, state="landed")
        assert current_state(slot_dir) == "landed"

    def test_defaults_to_active_when_no_slot_file(self, tmp_path):
        slot_dir = tmp_path / "slots" / "1"
        slot_dir.mkdir(parents=True)
        assert current_state(slot_dir) == "active"

    def test_reads_legacy_status_field(self, tmp_path):
        slot_dir = tmp_path / "slots" / "1"
        slot_dir.mkdir(parents=True)
        (slot_dir / ".slot").write_text(
            "# Slot 1\nslug: test\n\n## Status\nstatus: ready\n"
        )
        assert current_state(slot_dir) == "ready"


class TestTransitionValidation:

    def test_valid_active_to_paused(self, tmp_path):
        slot_dir = _make_slot(tmp_path)
        old = transition(slot_dir, "paused")
        assert old == "active"
        assert current_state(slot_dir) == "paused"

    def test_valid_active_to_ready(self, tmp_path):
        slot_dir = _make_slot(tmp_path)
        old = transition(slot_dir, "ready")
        assert old == "active"
        assert current_state(slot_dir) == "ready"

    def test_valid_ready_to_landed(self, tmp_path):
        slot_dir = _make_slot(tmp_path, state="ready")
        old = transition(slot_dir, "landed")
        assert old == "ready"
        assert current_state(slot_dir) == "landed"

    def test_valid_landed_to_archived(self, tmp_path):
        slot_dir = _make_slot(tmp_path, state="landed")
        old = transition(slot_dir, "archived")
        assert old == "landed"
        assert current_state(slot_dir) == "archived"

    def test_valid_paused_to_active(self, tmp_path):
        slot_dir = _make_slot(tmp_path, state="paused")
        old = transition(slot_dir, "active")
        assert old == "paused"
        assert current_state(slot_dir) == "active"

    def test_invalid_active_to_archived_raises(self, tmp_path):
        slot_dir = _make_slot(tmp_path)
        with pytest.raises(InvalidTransition) as exc_info:
            transition(slot_dir, "archived")
        assert exc_info.value.from_state == "active"
        assert exc_info.value.to_state == "archived"

    def test_invalid_active_to_landed_raises(self, tmp_path):
        slot_dir = _make_slot(tmp_path)
        with pytest.raises(InvalidTransition):
            transition(slot_dir, "landed")

    def test_invalid_archived_to_anything_raises(self, tmp_path):
        slot_dir = _make_slot(tmp_path, state="archived")
        with pytest.raises(InvalidTransition):
            transition(slot_dir, "active")

    def test_force_bypasses_validation(self, tmp_path):
        slot_dir = _make_slot(tmp_path)
        old = transition(slot_dir, "archived", force=True)
        assert old == "active"
        assert current_state(slot_dir) == "archived"

    def test_unknown_state_raises_value_error(self, tmp_path):
        slot_dir = _make_slot(tmp_path)
        with pytest.raises(ValueError, match="Unknown state"):
            transition(slot_dir, "nonexistent")


class TestTransitionTable:

    def test_all_visible_states_have_transition_entry(self):
        for state in VISIBLE_STATES:
            assert state in VALID_TRANSITIONS, f"Missing transition entry for {state}"

    def test_archived_is_terminal(self):
        assert VALID_TRANSITIONS["archived"] == frozenset()

    def test_no_self_transitions(self):
        for state, targets in VALID_TRANSITIONS.items():
            assert state not in targets, f"Self-transition found: {state} → {state}"

    def test_active_can_reach_paused_ready_stale(self):
        targets = VALID_TRANSITIONS["active"]
        assert "paused" in targets
        assert "ready" in targets
        assert "stale" in targets

    def test_stale_can_recover_to_active(self):
        assert "active" in VALID_TRANSITIONS["stale"]


class TestSlotFileIntegration:

    def test_write_slot_md_creates_state_field(self, tmp_path):
        slot_dir = _make_slot(tmp_path)
        info = parse_slot_md(slot_dir)
        assert info["state"] == "active"
        assert info["status"] == "active"  # legacy alias

    def test_transition_updates_slot_file(self, tmp_path):
        slot_dir = _make_slot(tmp_path)
        transition(slot_dir, "ready")
        content = (slot_dir / ".slot").read_text()
        assert "state: ready" in content

    def test_transition_preserves_other_fields(self, tmp_path):
        slot_dir = _make_slot(tmp_path)
        transition(slot_dir, "ready")
        info = parse_slot_md(slot_dir)
        assert info["issue"] == "42"
        assert info["issue_repo"] == "org/repo"
        assert info["repos"] == ["engine"]
        assert info["state"] == "ready"


class TestAuditState:

    def test_clean_active_slot(self, tmp_path):
        family_root = tmp_path
        slot_dir = _make_slot(tmp_path)
        divergences = audit_state(slot_dir, family_root)
        assert len(divergences) == 0

    def test_slot_says_active_but_has_landed_marker(self, tmp_path):
        family_root = tmp_path
        slot_dir = _make_slot(tmp_path)
        (slot_dir / ".landed").write_text("branch=test\n")
        divergences = audit_state(slot_dir, family_root)
        assert len(divergences) == 1
        assert divergences[0]["class"] == "slot-disk-mismatch"
        assert divergences[0]["disk_state"] == "landed"

    def test_slot_says_active_but_in_attic(self, tmp_path):
        family_root = tmp_path
        attic_dir = tmp_path / "slots" / "attic" / "1"
        attic_dir.mkdir(parents=True)
        write_slot_md(
            attic_dir, 1, ["engine"],
            branch="test", issue="1",
            issue_repo="org/repo", covers="1",
            context="test",
        )
        divergences = audit_state(attic_dir, family_root)
        assert len(divergences) == 1
        assert divergences[0]["class"] == "slot-disk-mismatch"
        assert divergences[0]["disk_state"] == "archived"

    def test_correct_landed_state_no_divergence(self, tmp_path):
        family_root = tmp_path
        slot_dir = _make_slot(tmp_path, state="landed")
        (slot_dir / ".landed").write_text("branch=test\n")
        divergences = audit_state(slot_dir, family_root)
        assert len(divergences) == 0

    def test_stale_state_not_flagged_as_disk_mismatch(self, tmp_path):
        family_root = tmp_path
        slot_dir = _make_slot(tmp_path, state="stale")
        divergences = audit_state(slot_dir, family_root)
        assert not any(d["class"] == "slot-disk-mismatch" for d in divergences)


class TestMigrateSlotState:

    def test_dry_run_reports_changes(self, tmp_path):
        from migrate_slot_state import migrate
        sys.path.insert(0, str(SOREDIUM_ROOT / "scripts"))

        family_root = tmp_path
        slots_dir = family_root / "slots"
        slots_dir.mkdir()
        slot_dir = slots_dir / "1"
        slot_dir.mkdir()
        slot_file = slot_dir / ".slot"
        slot_file.write_text("# Slot 1\nslug: test\n\n## Created\n2026-01-01\n")

        results = migrate(family_root, apply=False)
        assert results["updated"] == 1
        content = slot_file.read_text()
        assert "state:" not in content

    def test_apply_writes_state(self, tmp_path):
        from migrate_slot_state import migrate

        family_root = tmp_path
        slots_dir = family_root / "slots"
        slots_dir.mkdir()
        slot_dir = slots_dir / "1"
        slot_dir.mkdir()
        slot_file = slot_dir / ".slot"
        slot_file.write_text("# Slot 1\nslug: test\n\n## Created\n2026-01-01\n")

        results = migrate(family_root, apply=True)
        assert results["updated"] == 1
        content = slot_file.read_text()
        assert "state: active" in content

    def test_attic_gets_archived_state(self, tmp_path):
        from migrate_slot_state import migrate

        family_root = tmp_path
        attic_dir = family_root / "slots" / "attic" / "5"
        attic_dir.mkdir(parents=True)
        slot_file = attic_dir / ".slot"
        slot_file.write_text("# Slot 5\nslug: test\n\n## Created\n2026-01-01\n")

        results = migrate(family_root, apply=True)
        assert results["updated"] == 1
        content = slot_file.read_text()
        assert "state: archived" in content

    def test_landed_marker_gets_landed_state(self, tmp_path):
        from migrate_slot_state import migrate

        family_root = tmp_path
        slots_dir = family_root / "slots"
        slots_dir.mkdir()
        slot_dir = slots_dir / "2"
        slot_dir.mkdir()
        (slot_dir / ".slot").write_text("# Slot 2\nslug: test\n\n## Created\n2026-01-01\n")
        (slot_dir / ".landed").write_text("branch=test\n")

        results = migrate(family_root, apply=True)
        content = (slot_dir / ".slot").read_text()
        assert "state: landed" in content
