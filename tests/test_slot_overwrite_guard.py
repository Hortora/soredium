"""Tests for slot overwrite protection (issue #615).

Verifies that create_slot and allocate_slot_number never destroy an
existing slot directory, regardless of DB state.
"""

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

skill_dir = Path(__file__).parent.parent / "work-slot"
sys.path.insert(0, str(skill_dir))

scripts_dir = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(scripts_dir))

import slot_lifecycle
import worklog as _wl_mod
from slot_core import SlotCreationError
from slot_test_helpers import init_repo


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path_factory, monkeypatch):
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))


@pytest.fixture(autouse=True)
def _no_stray_sessions(monkeypatch):
    monkeypatch.setattr("slot_claude.find_active_sessions", lambda d: [])


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = tmp_path / "guard_test.db"
    monkeypatch.setattr(slot_lifecycle, "_wl", _wl_mod)
    monkeypatch.setattr(_wl_mod, "DEFAULT_DB", str(db_path))
    return _wl_mod


class TestAllocateNeverOverwritesActiveSlot:
    """allocate_slot_number must never rmtree a directory that exists on disk
    when the DB says it's reusable but disk says it's occupied."""

    def test_reusable_slot_with_existing_dir_skips_to_next(self, tmp_path, db):
        """When find_reusable_slot returns a number whose directory exists
        on disk with content, allocate_slot_number must NOT rmtree it.
        It should fall back to reserve_slot_number."""
        family = tmp_path / "family"
        family.mkdir()
        slots_dir = family / "slots"
        slots_dir.mkdir()

        conn = db.connect()
        conn.execute(
            "INSERT INTO slots (slot_number, family_root, state, created_at) "
            "VALUES (?, ?, 'pending', '2026-01-01')",
            (5, db._norm(str(family))),
        )
        conn.commit()
        conn.close()

        active_slot = slots_dir / "5"
        active_slot.mkdir()
        repo_in_slot = init_repo(active_slot / "some-repo")
        marker = active_slot / "important-work.txt"
        marker.write_text("do not delete")

        result = slot_lifecycle.allocate_slot_number(family)

        assert result != 5, "Must not reuse slot number whose directory exists with content"
        assert active_slot.exists(), "Existing slot directory must not be deleted"
        assert marker.exists(), "Files in existing slot must survive"

    def test_reusable_slot_with_git_repos_never_deleted(self, tmp_path, db):
        """The critical case from issue #615: DB says pending, but the dir
        has git repos with commits inside."""
        family = tmp_path / "family"
        family.mkdir()
        slots_dir = family / "slots"
        slots_dir.mkdir()

        conn = db.connect()
        conn.execute(
            "INSERT INTO slots (slot_number, family_root, state, created_at) "
            "VALUES (?, ?, 'failed', '2026-01-01')",
            (3, db._norm(str(family))),
        )
        conn.commit()
        conn.close()

        occupied_slot = slots_dir / "3"
        occupied_slot.mkdir()
        repo = init_repo(occupied_slot / "engine")
        (repo / "src.java").write_text("class Foo {}")
        subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "work"],
                       capture_output=True)

        result = slot_lifecycle.allocate_slot_number(family)

        assert result != 3
        assert occupied_slot.exists()
        assert (repo / "src.java").exists()

    def test_truly_empty_reusable_slot_can_be_reused(self, tmp_path, db):
        """An empty directory (no git repos, no files) is genuine debris
        and can be safely removed for reuse."""
        family = tmp_path / "family"
        family.mkdir()
        slots_dir = family / "slots"
        slots_dir.mkdir()

        conn = db.connect()
        conn.execute(
            "INSERT INTO slots (slot_number, family_root, state, created_at) "
            "VALUES (?, ?, 'pending', '2026-01-01')",
            (2, db._norm(str(family))),
        )
        conn.commit()
        conn.close()

        empty_slot = slots_dir / "2"
        empty_slot.mkdir()

        result = slot_lifecycle.allocate_slot_number(family)

        assert result == 2, "Empty debris directory should be reusable"
        assert not empty_slot.exists() or not any(empty_slot.iterdir()), \
            "Empty debris should be cleaned up"

    def test_m2_only_debris_is_reusable(self, tmp_path, db):
        """A slot dir with only .m2 (Maven cache) is creation debris,
        not real work — safe to reuse."""
        family = tmp_path / "family"
        family.mkdir()
        slots_dir = family / "slots"
        slots_dir.mkdir()

        conn = db.connect()
        conn.execute(
            "INSERT INTO slots (slot_number, family_root, state, created_at) "
            "VALUES (?, ?, 'pending', '2026-01-01')",
            (4, db._norm(str(family))),
        )
        conn.commit()
        conn.close()

        debris_slot = slots_dir / "4"
        debris_slot.mkdir()
        (debris_slot / ".m2").mkdir()

        result = slot_lifecycle.allocate_slot_number(family)

        assert result == 4, ".m2-only debris should be reusable"
        assert not debris_slot.exists(), "Debris dir should be removed"

    def test_other_reusable_slots_with_content_not_deleted(self, tmp_path, db):
        """When multiple reusable slots exist, 'others' directories with
        content must not be rmtree'd either."""
        family = tmp_path / "family"
        family.mkdir()
        slots_dir = family / "slots"
        slots_dir.mkdir()

        conn = db.connect()
        for n, state in [(10, 'pending'), (8, 'failed')]:
            conn.execute(
                "INSERT INTO slots (slot_number, family_root, state, created_at) "
                "VALUES (?, ?, ?, '2026-01-01')",
                (n, db._norm(str(family)), state),
            )
        conn.commit()
        conn.close()

        other_slot = slots_dir / "8"
        other_slot.mkdir()
        repo = init_repo(other_slot / "work-repo")

        result = slot_lifecycle.allocate_slot_number(family)

        assert other_slot.exists(), "'Other' reusable slot with content must not be deleted"
        assert (other_slot / "work-repo" / ".git").exists()


class TestCreateSlotDirExistsGuard:
    """create_slot must refuse if the target slot directory already exists,
    even if allocate_slot_number somehow returns a colliding number."""

    @patch("slot_lifecycle.run_cmd")
    def test_create_slot_refuses_when_dir_exists(self, mock_cmd, tmp_path, db):
        """If the allocated slot dir already exists (e.g. from a different DB),
        create_slot must raise, not overwrite."""
        family = tmp_path / "family"
        family.mkdir()
        repo = init_repo(family / "myrepo")
        ws = init_repo(tmp_path / "public" / "myrepo")
        (repo / "wksp").symlink_to(ws)

        slots_dir = family / "slots"
        slots_dir.mkdir()
        existing = slots_dir / "1"
        existing.mkdir()
        sentinel = existing / "do-not-destroy.txt"
        sentinel.write_text("active work here")

        mock_cmd.return_value = (0, "", "")

        with patch("slot_lifecycle.resolve_workspace_source") as mock_resolve:
            mock_resolve.return_value = (ws, "wsp-myrepo")
            with pytest.raises(SlotCreationError, match="already exists"):
                slot_lifecycle.create_slot(
                    family_root=family,
                    repos=["myrepo"],
                    branch="issue-999-test",
                    issue="999",
                    issue_repo="test/repo",
                    covers="999",
                    context="Overwrite test",
                )

        assert sentinel.exists(), "Existing slot content must survive"

    @patch("slot_lifecycle.run_cmd")
    def test_reserve_path_collision_caught_by_create_slot(self, mock_cmd, tmp_path, db):
        """When reserve_slot_number returns MAX+1 but that dir exists on disk
        (different DB scenario), create_slot still refuses."""
        family = tmp_path / "family"
        family.mkdir()
        repo = init_repo(family / "myrepo")
        ws = init_repo(tmp_path / "public" / "myrepo")
        (repo / "wksp").symlink_to(ws)

        conn = db.connect()
        conn.execute(
            "INSERT INTO slots (slot_number, family_root, state, created_at) "
            "VALUES (?, ?, 'active', '2026-01-01')",
            (5, db._norm(str(family))),
        )
        conn.commit()
        conn.close()

        slots_dir = family / "slots"
        slots_dir.mkdir()
        collision = slots_dir / "6"
        collision.mkdir()
        work_in_collision = init_repo(collision / "engine")

        mock_cmd.return_value = (0, "", "")

        with patch("slot_lifecycle.resolve_workspace_source") as mock_resolve:
            mock_resolve.return_value = (ws, "wsp-myrepo")
            with pytest.raises(SlotCreationError, match="already exists"):
                slot_lifecycle.create_slot(
                    family_root=family,
                    repos=["myrepo"],
                    branch="issue-888-test",
                    issue="888",
                    issue_repo="test/repo",
                    covers="888",
                    context="Reserve collision test",
                )

        assert (collision / "engine" / ".git").exists(), \
            "Git repo in colliding slot must survive"
