"""Tests for scripts/place_workspace_markers.py"""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent / "work-slot"))


def init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@test.com"], capture_output=True)
    subprocess.run(["git", "-C", str(path), "commit", "--allow-empty", "-m", "init"], capture_output=True, check=True)
    return path


def _make_slot(family_root, slot_num, repos, workspaces, attic=False):
    base = family_root / "slots"
    if attic:
        base = base / "attic"
    slot_dir = base / str(slot_num)
    slot_dir.mkdir(parents=True)
    for r in repos:
        init_repo(slot_dir / r)
    for w in workspaces:
        init_repo(slot_dir / w)
    return slot_dir


class TestPlaceWorkspaceMarkers:
    def test_places_markers_on_work_prefixed_dirs(self, tmp_path):
        _make_slot(tmp_path, 1, ["engine"], ["work-casehub"])
        from place_workspace_markers import place_markers
        result = place_markers(tmp_path)
        assert (tmp_path / "slots" / "1" / "work-casehub" / ".workspace").exists()
        assert result["placed"] == 1

    def test_skips_project_repos(self, tmp_path):
        _make_slot(tmp_path, 1, ["engine"], ["work-casehub"])
        from place_workspace_markers import place_markers
        place_markers(tmp_path)
        assert not (tmp_path / "slots" / "1" / "engine" / ".workspace").exists()

    def test_idempotent(self, tmp_path):
        _make_slot(tmp_path, 1, ["engine"], ["work-casehub"])
        from place_workspace_markers import place_markers
        place_markers(tmp_path)
        result = place_markers(tmp_path)
        assert result["placed"] == 0
        assert result["already_marked"] == 1

    def test_includes_attic(self, tmp_path):
        _make_slot(tmp_path, 5, ["engine"], ["work-casehub"], attic=True)
        from place_workspace_markers import place_markers
        result = place_markers(tmp_path)
        assert (tmp_path / "slots" / "attic" / "5" / "work-casehub" / ".workspace").exists()
        assert result["placed"] == 1

    def test_skips_attic_when_disabled(self, tmp_path):
        _make_slot(tmp_path, 5, ["engine"], ["work-casehub"], attic=True)
        from place_workspace_markers import place_markers
        result = place_markers(tmp_path, include_attic=False)
        assert not (tmp_path / "slots" / "attic" / "5" / "work-casehub" / ".workspace").exists()
        assert result["placed"] == 0

    def test_detects_workspace_by_proj_symlink(self, tmp_path):
        slot_dir = _make_slot(tmp_path, 1, ["engine"], [])
        ws = init_repo(slot_dir / "custom-ws-name")
        (ws / "proj").symlink_to(str(slot_dir / "engine"))
        from place_workspace_markers import place_markers
        result = place_markers(tmp_path)
        assert (ws / ".workspace").exists()
        assert result["placed"] == 1

    def test_no_slots_dir(self, tmp_path):
        from place_workspace_markers import place_markers
        result = place_markers(tmp_path)
        assert result == {"placed": 0, "already_marked": 0, "skipped": 0}

    def test_multiple_slots(self, tmp_path):
        _make_slot(tmp_path, 1, ["engine"], ["work-casehub"])
        _make_slot(tmp_path, 2, ["platform"], ["work"])
        from place_workspace_markers import place_markers
        result = place_markers(tmp_path)
        assert result["placed"] == 2
