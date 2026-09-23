"""Tests for project/clone_manager.py — family clone creation and management."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "project"))


def init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t.com"], capture_output=True)
    (path / "README.md").write_text("init\n")
    subprocess.run(["git", "-C", str(path), "add", "."], cwd=str(path), capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=str(path), capture_output=True, check=True,
    )
    return path


class TestCreateClone:
    def test_creates_local_clone(self, tmp_path):
        family = tmp_path / "casehub"
        family.mkdir()
        init_repo(family / "engine")
        from clone_manager import create_clone
        result = create_clone(family, "engine")
        assert result["CREATED"] == "yes"
        clone_path = Path(result["CLONE_PATH"])
        assert clone_path.is_dir()
        assert (clone_path / ".git").exists()
        assert (clone_path / "README.md").exists()

    def test_idempotent_when_clone_exists(self, tmp_path):
        family = tmp_path / "casehub"
        family.mkdir()
        init_repo(family / "engine")
        from clone_manager import create_clone
        create_clone(family, "engine")
        result = create_clone(family, "engine")
        assert result["CREATED"] == "already_exists"

    def test_error_when_canonical_missing(self, tmp_path):
        family = tmp_path / "casehub"
        family.mkdir()
        from clone_manager import create_clone
        result = create_clone(family, "nonexistent")
        assert "ERROR" in result
        assert result["ERROR"] == "canonical_not_found"

    def test_clone_origin_points_at_canonical(self, tmp_path):
        family = tmp_path / "casehub"
        family.mkdir()
        canonical = init_repo(family / "engine")
        from clone_manager import create_clone
        result = create_clone(family, "engine")
        clone_path = Path(result["CLONE_PATH"])
        origin = subprocess.run(
            ["git", "-C", str(clone_path), "remote", "get-url", "origin"],
            capture_output=True, text=True,
        )
        assert origin.returncode == 0
        assert str(canonical) in origin.stdout.strip()

    def test_creates_clone_dir_if_missing(self, tmp_path):
        family = tmp_path / "casehub"
        family.mkdir()
        init_repo(family / "engine")
        assert not (family / "clone").exists()
        from clone_manager import create_clone
        create_clone(family, "engine")
        assert (family / "clone").is_dir()


class TestCloneExists:
    def test_returns_path_when_exists(self, tmp_path):
        family = tmp_path / "casehub"
        family.mkdir()
        init_repo(family / "engine")
        from clone_manager import create_clone, clone_exists
        create_clone(family, "engine")
        result = clone_exists(family, "engine")
        assert result is not None
        assert result.name == "engine"

    def test_returns_none_when_missing(self, tmp_path):
        family = tmp_path / "casehub"
        family.mkdir()
        from clone_manager import clone_exists
        assert clone_exists(family, "engine") is None


class TestDecline:
    def test_decline_persisted(self, tmp_path):
        family = tmp_path / "casehub"
        family.mkdir()
        from clone_manager import record_decline, is_declined
        assert not is_declined(family, "docs-repo")
        record_decline(family, "docs-repo")
        assert is_declined(family, "docs-repo")

    def test_decline_per_repo(self, tmp_path):
        family = tmp_path / "casehub"
        family.mkdir()
        from clone_manager import record_decline, is_declined
        record_decline(family, "docs-repo")
        assert not is_declined(family, "engine")

    def test_decline_idempotent(self, tmp_path):
        family = tmp_path / "casehub"
        family.mkdir()
        from clone_manager import record_decline, is_declined
        record_decline(family, "docs-repo")
        record_decline(family, "docs-repo")
        config = (family / "clone" / ".clone-config").read_text()
        assert config.count("decline:docs-repo") == 1


class TestEnabled:
    def test_disabled_by_default(self, tmp_path, monkeypatch):
        monkeypatch.setattr("clone_manager._settings_path",
                            lambda: tmp_path / "settings.json")
        from clone_manager import is_enabled
        assert is_enabled() is False

    def test_enabled_when_set(self, tmp_path, monkeypatch):
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"clone_enabled": True}))
        monkeypatch.setattr("clone_manager._settings_path",
                            lambda: settings)
        from clone_manager import is_enabled
        assert is_enabled() is True

    def test_disabled_when_false(self, tmp_path, monkeypatch):
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"clone_enabled": False}))
        monkeypatch.setattr("clone_manager._settings_path",
                            lambda: settings)
        from clone_manager import is_enabled
        assert is_enabled() is False
