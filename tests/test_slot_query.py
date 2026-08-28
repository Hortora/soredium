"""Tests for work-slot/slot_query.py"""

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

skill_dir = Path(__file__).parent.parent / "work-slot"
sys.path.insert(0, str(skill_dir))

scripts_dir = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(scripts_dir))

import slot_query
import slot_metadata
import slot_core
from slot_test_helpers import init_repo, init_repo_with_workspace


class TestListSlots:
    def test_empty_slots(self, tmp_path):
        family = tmp_path / "casehub"
        (family / "slots").mkdir(parents=True)
        slots = slot_query.list_slots(family)
        assert slots == []

    def test_active_slot(self, tmp_path):
        family = tmp_path / "casehub"
        slot = family / "slots" / "1"
        slot.mkdir(parents=True)
        (slot / ".slot").write_text("# Slot 1 — issue-42-spi\n")
        (slot / "engine").mkdir()
        (slot / "engine" / ".git").write_text("gitdir: /fake/.git/worktrees/engine")

        slots = slot_query.list_slots(family)
        assert len(slots) == 1
        assert slots[0]["number"] == 1
        assert slots[0]["state"] == "active"
        assert "engine" in slots[0]["repos"]

    def test_ready_to_land_slot(self, tmp_path):
        family = tmp_path / "casehub"
        slot = family / "slots" / "1"
        slot.mkdir(parents=True)
        (slot / ".slot").write_text("# Slot 1 — issue-42-spi\n")
        (slot / ".phase-a-complete").write_text("branch=issue-42\n")
        (slot / "engine").mkdir()
        (slot / "engine" / ".git").write_text("gitdir: /fake")

        slots = slot_query.list_slots(family)
        assert slots[0]["state"] == "ready to land"

    def test_no_slots_dir(self, tmp_path):
        family = tmp_path / "casehub"
        family.mkdir()
        slots = slot_query.list_slots(family)
        assert slots == []



class TestListSlotsExtended:
    def test_shows_landed_state(self, tmp_path):
        worktrees = tmp_path / "slots"
        worktrees.mkdir()
        slot = worktrees / "1"
        slot.mkdir()
        (slot / ".phase-a-complete").write_text("branch=issue-42\n")
        (slot / ".landed").write_text("landed\n")
        (slot / ".slot").write_text("# Slot 1 — issue-42\n")

        result = slot_query.list_slots(tmp_path, include_archived=False)
        assert len(result) == 1
        assert result[0]["state"] == "landed"

    def test_includes_archived(self, tmp_path):
        worktrees = tmp_path / "slots"
        worktrees.mkdir()
        attic = worktrees / "attic"
        attic.mkdir()
        archived = attic / "3"
        archived.mkdir()
        (archived / ".slot").write_text(
            "# Slot 3 — issue-99-old\n\n## Repos\n- engine\n- iot\n"
        )

        result_no_all = slot_query.list_slots(tmp_path, include_archived=False)
        assert len(result_no_all) == 0

        result_all = slot_query.list_slots(tmp_path, include_archived=True)
        assert len(result_all) == 1
        assert result_all[0]["number"] == 3
        assert result_all[0]["state"] == "archived"
        assert result_all[0]["branch"] == "issue-99-old"
        assert "engine" in result_all[0]["repos"]
        assert "iot" in result_all[0]["repos"]

    def test_remnant_dir_excluded_when_archived(self, tmp_path):
        """Remnant worktrees/<N>/ after archive should not appear as active."""
        worktrees = tmp_path / "slots"
        worktrees.mkdir()
        # Remnant directory left behind after shutil.move
        remnant = worktrees / "68"
        remnant.mkdir()
        (remnant / ".slot").write_text("# Slot 68 — issue-152-old\n")
        (remnant / "devtown").mkdir()
        (remnant / "devtown" / ".git").write_text("gitdir: /fake")
        # Archived copy in attic
        attic = worktrees / "attic" / "68"
        attic.mkdir(parents=True)
        (attic / ".slot").write_text("# Slot 68 — issue-152-old\n")

        result = slot_query.list_slots(tmp_path, include_archived=False)
        assert all(s["number"] != 68 for s in result), \
            "archived slot 68 appeared as active due to remnant directory"

        result_all = slot_query.list_slots(tmp_path, include_archived=True)
        archived = [s for s in result_all if s["number"] == 68]
        assert len(archived) == 1
        assert archived[0]["state"] == "archived"

    def test_backward_compat_no_arg(self, tmp_path):
        worktrees = tmp_path / "slots"
        worktrees.mkdir()
        slot = worktrees / "1"
        slot.mkdir()
        (slot / ".slot").write_text("# Slot 1 — issue-42\n")
        (slot / "engine").mkdir()
        (slot / "engine" / ".git").write_text("gitdir: /fake")
        result = slot_query.list_slots(tmp_path)
        assert len(result) == 1
        assert result[0]["state"] == "active"



class TestListSlotsDualPath:
    def test_finds_slots_in_legacy_worktrees(self, tmp_path):
        wt = tmp_path / "worktrees" / "1"
        wt.mkdir(parents=True)
        init_repo(wt / "myrepo")
        (wt / ".slot").write_text("# Slot 1 — test-branch\n")
        slots = slot_query.list_slots(tmp_path)
        assert len(slots) == 1
        assert slots[0]["number"] == 1

    def test_finds_slots_in_new_dir(self, tmp_path):
        sd = tmp_path / "slots" / "1"
        sd.mkdir(parents=True)
        init_repo(sd / "myrepo")
        (sd / ".slot").write_text("# Slot 1 — test-branch\n")
        slots = slot_query.list_slots(tmp_path)
        assert len(slots) == 1
        assert slots[0]["number"] == 1

    def test_merges_both_dirs(self, tmp_path):
        wt = tmp_path / "worktrees" / "1"
        wt.mkdir(parents=True)
        init_repo(wt / "repo1")
        (wt / ".slot").write_text("# Slot 1 — old-branch\n")
        sd = tmp_path / "slots" / "2"
        sd.mkdir(parents=True)
        init_repo(sd / "repo2")
        (sd / ".slot").write_text("# Slot 2 — new-branch\n")
        slots = slot_query.list_slots(tmp_path)
        assert len(slots) == 2
        nums = {s["number"] for s in slots}
        assert nums == {1, 2}





class TestListSlotsIsolation:
    def test_list_shows_isx_isolation(self, tmp_path):
        slot_dir = tmp_path / "slots" / "1"
        slot_dir.mkdir(parents=True)
        init_repo(slot_dir / "engine")
        slot_metadata.write_slot_md(
            slot_dir, 1, ["engine"], "test-branch", "42",
            "Org/repo", "42", "test",
            isolation_type="isx", isx_instance="test-inst",
            isx_template="tpl-java",
        )
        slots = slot_query.list_slots(tmp_path)
        assert slots[0]["isolation"] == "isx"

    def test_list_shows_none_isolation(self, tmp_path):
        slot_dir = tmp_path / "slots" / "1"
        slot_dir.mkdir(parents=True)
        init_repo(slot_dir / "engine")
        slot_metadata.write_slot_md(
            slot_dir, 1, ["engine"], "test-branch", "42",
            "Org/repo", "42", "test",
        )
        slots = slot_query.list_slots(tmp_path)
        assert slots[0]["isolation"] == "none"



class TestListSlotsWkspHealth:
    def test_wksp_ok_true_when_no_wksp(self, tmp_path):
        """Repos without workspace integration are wksp_ok=True."""
        slot_dir = tmp_path / "slots" / "1"
        slot_dir.mkdir(parents=True)
        (slot_dir / ".slot").write_text("# Slot 1 — test\n")
        init_repo(slot_dir / "engine")
        slots = slot_query.list_slots(tmp_path)
        assert len(slots) == 1
        assert slots[0]["wksp_ok"] is True

    def test_wksp_ok_false_when_dangling(self, tmp_path):
        """Broken wksp/ symlink surfaces as wksp_ok=False."""
        slot_dir = tmp_path / "slots" / "1"
        slot_dir.mkdir(parents=True)
        (slot_dir / ".slot").write_text("# Slot 1 — test\n")
        clone = init_repo(slot_dir / "engine")
        (clone / "wksp").symlink_to("/nonexistent")
        slots = slot_query.list_slots(tmp_path)
        assert len(slots) == 1
        assert slots[0]["wksp_ok"] is False



class TestListSlotsGhostFilter:
    def test_skips_ghost_directories(self, tmp_path, monkeypatch):
        monkeypatch.setattr(slot_query, "_wl", None)
        real = tmp_path / "slots" / "1"
        real.mkdir(parents=True)
        (real / ".slot").write_text("# Slot 1 — issue-1-real\n\n## Repos\n- myrepo\n")
        init_repo(real / "myrepo")
        ghost = tmp_path / "slots" / "2"
        ghost.mkdir(parents=True)
        (ghost / "somedir").mkdir()

        slots = slot_query.list_slots(tmp_path)
        nums = [s["number"] for s in slots]
        assert 1 in nums
        assert 2 not in nums



class TestScanReady:
    def test_finds_phase_a_complete_slots(self, tmp_path):
        worktrees = tmp_path / "slots"
        worktrees.mkdir()
        slot1 = worktrees / "1"
        slot1.mkdir()
        (slot1 / ".phase-a-complete").write_text(
            "branch=issue-42-spi\nrepos=engine\ntimestamp=2026-07-18T14:32:00\n"
        )
        (slot1 / ".slot").write_text(
            "# Slot 1 — issue-42-spi\n\n## Issue\ncasehubio/engine#42\n"
            "Covers: 42\n\n## What to do\nImplement SPI\n\n## Repos\n- engine (primary)\n"
        )
        engine = slot1 / "engine"
        engine.mkdir()

        # Slot 2: active (no marker)
        (worktrees / "2").mkdir()

        # Slot 3: landed (should NOT appear)
        slot3 = worktrees / "3"
        slot3.mkdir()
        (slot3 / ".phase-a-complete").write_text("branch=issue-99\n")
        (slot3 / ".landed").write_text("landed\n")

        result = slot_query.scan_ready(tmp_path)
        assert len(result) == 1
        assert result[0]["number"] == 1
        assert result[0]["branch"] == "issue-42-spi"
        assert result[0]["context"] == "Implement SPI"

    def test_empty_when_no_ready_slots(self, tmp_path):
        worktrees = tmp_path / "slots"
        worktrees.mkdir()
        (worktrees / "1").mkdir()
        assert slot_query.scan_ready(tmp_path) == []

    def test_no_slots_dir(self, tmp_path):
        assert slot_query.scan_ready(tmp_path) == []


from slot_test_helpers import init_repo_with_remote as _init_repo_with_remote



class TestFindSlotByBranch:
    def test_finds_match(self, tmp_path):
        slots_dir = tmp_path / "slots" / "1"
        slots_dir.mkdir(parents=True)
        (slots_dir / ".slot").write_text("# Slot 1 — issue-42-feature\n\n## Repos\n- myrepo\n")
        result = slot_query.find_slot_by_branch(tmp_path, "issue-42-feature")
        assert result is not None
        assert result == (1, False)

    def test_returns_landed_flag(self, tmp_path):
        slots_dir = tmp_path / "slots" / "1"
        slots_dir.mkdir(parents=True)
        (slots_dir / ".slot").write_text("# Slot 1 — issue-42-feature\n\n## Repos\n- myrepo\n")
        (slots_dir / ".landed").write_text("landed_shas=myrepo:abc123\n")
        result = slot_query.find_slot_by_branch(tmp_path, "issue-42-feature")
        assert result == (1, True)

    def test_no_match(self, tmp_path):
        slots_dir = tmp_path / "slots" / "1"
        slots_dir.mkdir(parents=True)
        (slots_dir / ".slot").write_text("# Slot 1 — issue-42-feature\n\n## Repos\n- myrepo\n")
        assert slot_query.find_slot_by_branch(tmp_path, "other-branch") is None

    def test_ignores_attic(self, tmp_path):
        attic = tmp_path / "slots" / "attic" / "1"
        attic.mkdir(parents=True)
        (attic / ".slot").write_text("# Slot 1 — issue-42-feature\n\n## Repos\n- myrepo\n")
        assert slot_query.find_slot_by_branch(tmp_path, "issue-42-feature") is None

    def test_ignores_ghost_dirs(self, tmp_path):
        slots_dir = tmp_path / "slots" / "1"
        slots_dir.mkdir(parents=True)
        assert slot_query.find_slot_by_branch(tmp_path, "anything") is None



class TestListSlotsDriftDetection:
    """Inline drift detection comparing DB vs disk state."""

    def _setup_db(self, tmp_path, monkeypatch):
        scripts_dir = Path(__file__).parent.parent / "scripts"
        sys.path.insert(0, str(scripts_dir))
        import worklog as _wl_mod
        db_path = tmp_path / "drift_test.db"
        monkeypatch.setattr(slot_query, "_wl", _wl_mod)
        monkeypatch.setattr(_wl_mod, "DEFAULT_DB", str(db_path))
        return _wl_mod

    def test_no_warnings_when_aligned(self, tmp_path, monkeypatch, capsys):
        _wl_mod = self._setup_db(tmp_path, monkeypatch)
        family = tmp_path / "family"
        slot_dir = family / "slots" / "1"
        slot_dir.mkdir(parents=True)
        (slot_dir / ".slot").write_text("# Slot 1 — test-branch\n")
        conn = _wl_mod.connect()
        conn.execute(
            "INSERT INTO slots (slot_number, family_root, state, created_at) "
            "VALUES (1, ?, 'active', '2026-01-01')",
            (_wl_mod._norm(str(family)),),
        )
        conn.commit()
        conn.close()
        slot_query.list_slots(family)
        captured = capsys.readouterr()
        assert "WARN=db_drift" not in captured.out

    def test_warns_on_db_only(self, tmp_path, monkeypatch, capsys):
        _wl_mod = self._setup_db(tmp_path, monkeypatch)
        family = tmp_path / "family"
        (family / "slots").mkdir(parents=True)
        conn = _wl_mod.connect()
        conn.execute(
            "INSERT INTO slots (slot_number, family_root, state, created_at) "
            "VALUES (99, ?, 'active', '2026-01-01')",
            (_wl_mod._norm(str(family)),),
        )
        conn.commit()
        conn.close()
        slot_query.list_slots(family)
        captured = capsys.readouterr()
        assert "WARN=db_drift type=db-only slot=99" in captured.out

    def test_warns_on_disk_only(self, tmp_path, monkeypatch, capsys):
        _wl_mod = self._setup_db(tmp_path, monkeypatch)
        family = tmp_path / "family"
        slot_dir = family / "slots" / "1"
        slot_dir.mkdir(parents=True)
        (slot_dir / ".slot").write_text("# Slot 1 — test\n")
        _wl_mod.connect().close()
        slot_query.list_slots(family)
        captured = capsys.readouterr()
        assert "WARN=db_drift type=disk-only slot=1" in captured.out

    def test_warns_on_state_mismatch(self, tmp_path, monkeypatch, capsys):
        _wl_mod = self._setup_db(tmp_path, monkeypatch)
        family = tmp_path / "family"
        attic = family / "slots" / "attic" / "1"
        attic.mkdir(parents=True)
        (attic / ".slot").write_text("# Slot 1 — test\n")
        conn = _wl_mod.connect()
        conn.execute(
            "INSERT INTO slots (slot_number, family_root, state, created_at) "
            "VALUES (1, ?, 'active', '2026-01-01')",
            (_wl_mod._norm(str(family)),),
        )
        conn.commit()
        conn.close()
        slot_query.list_slots(family, include_archived=True)
        captured = capsys.readouterr()
        assert "WARN=db_drift type=state-mismatch slot=1" in captured.out

    def test_warns_on_ghost(self, tmp_path, monkeypatch, capsys):
        _wl_mod = self._setup_db(tmp_path, monkeypatch)
        family = tmp_path / "family"
        ghost = family / "slots" / "1"
        ghost.mkdir(parents=True)
        (ghost / ".m2").mkdir()
        _wl_mod.connect().close()
        slot_query.list_slots(family)
        captured = capsys.readouterr()
        assert "WARN=db_drift type=ghost slot=1" in captured.out

    def test_no_drift_check_without_worklog(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(slot_query, "_wl", None)
        family = tmp_path / "family"
        slot_dir = family / "slots" / "1"
        slot_dir.mkdir(parents=True)
        (slot_dir / ".slot").write_text("# Slot 1 — test\n")
        slot_query.list_slots(family)
        captured = capsys.readouterr()
        assert "WARN=db_drift" not in captured.out

