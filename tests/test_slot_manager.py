"""Tests for work-slot/slot_manager.py"""

import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, call

import pytest

skill_dir = Path(__file__).parent.parent / "work-slot"
sys.path.insert(0, str(skill_dir))

import slot_manager


def init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@test.com"], capture_output=True)
    subprocess.run(["git", "-C", str(path), "commit", "--allow-empty", "-m", "init"], capture_output=True, check=True)
    return path


class TestAllocateSlotNumber:
    def test_empty_slots_dir(self, tmp_path):
        (tmp_path / "slots").mkdir()
        assert slot_manager.allocate_slot_number(tmp_path) == 1

    def test_existing_slots(self, tmp_path):
        slots = tmp_path / "slots"
        slots.mkdir()
        (slots / "1").mkdir()
        (slots / "2").mkdir()
        assert slot_manager.allocate_slot_number(tmp_path) == 3

    def test_gap_in_numbering(self, tmp_path):
        slots = tmp_path / "slots"
        slots.mkdir()
        (slots / "1").mkdir()
        (slots / "3").mkdir()
        assert slot_manager.allocate_slot_number(tmp_path) == 4

    def test_no_slots_dir(self, tmp_path):
        assert slot_manager.allocate_slot_number(tmp_path) == 1

    def test_considers_attic(self, tmp_path):
        slots = tmp_path / "slots"
        slots.mkdir()
        (slots / "1").mkdir()
        (slots / "2").mkdir()
        attic = slots / "attic"
        attic.mkdir()
        (attic / "3").mkdir()
        (attic / "5").mkdir()
        assert slot_manager.allocate_slot_number(tmp_path) == 6

    def test_only_attic(self, tmp_path):
        slots = tmp_path / "slots"
        slots.mkdir()
        attic = slots / "attic"
        attic.mkdir()
        (attic / "4").mkdir()
        assert slot_manager.allocate_slot_number(tmp_path) == 5

    def test_considers_legacy_worktrees(self, tmp_path):
        slots = tmp_path / "slots"
        slots.mkdir()
        (slots / "1").mkdir()
        (slots / "2").mkdir()
        wt = tmp_path / "worktrees"
        wt.mkdir()
        attic = wt / "attic"
        attic.mkdir()
        (attic / "50").mkdir()
        (attic / "60").mkdir()
        assert slot_manager.allocate_slot_number(tmp_path) == 61

    def test_considers_active_legacy_slots(self, tmp_path):
        slots = tmp_path / "slots"
        slots.mkdir()
        (slots / "1").mkdir()
        wt = tmp_path / "worktrees"
        wt.mkdir()
        (wt / "54").mkdir()
        assert slot_manager.allocate_slot_number(tmp_path) == 55


class TestResolveWorkspaceSource:
    def test_shared_workspace(self, tmp_path):
        shared_ws = init_repo(tmp_path / "public" / "casehub")
        (shared_ws / "engine").mkdir()
        repo = tmp_path / "casehub" / "engine"
        repo.mkdir(parents=True)
        (repo / "wksp").symlink_to(shared_ws / "engine")

        src, name = slot_manager.resolve_workspace_source(repo)
        assert src == shared_ws
        assert name == "work"

    def test_external_workspace(self, tmp_path):
        ext_ws = init_repo(tmp_path / "public" / "casehub-iot")
        repo = tmp_path / "casehub" / "iot"
        repo.mkdir(parents=True)
        (repo / "wksp").symlink_to(ext_ws)

        src, name = slot_manager.resolve_workspace_source(repo)
        assert src == ext_ws
        assert name == "work-casehub-iot"

    def test_no_wksp_symlink(self, tmp_path):
        repo = tmp_path / "casehub" / "engine"
        repo.mkdir(parents=True)
        result = slot_manager.resolve_workspace_source(repo)
        assert result is None


class TestWorkspaceNameCollision:
    @patch("slot_manager.run_cmd")
    def test_deconflicts_workspace_name_with_repo_name(self, mock_cmd, tmp_path):
        """When a repo is named 'work' and the shared workspace would also
        clone as 'work', create_slot must deconflict the names."""
        family = tmp_path / "casehub"
        family.mkdir()
        work_repo = init_repo(family / "work")
        shared_ws = init_repo(tmp_path / "public" / "casehub")
        (shared_ws / "work").mkdir()
        (work_repo / "wksp").symlink_to(shared_ws / "work")

        mock_cmd.return_value = (0, "", "")

        result = slot_manager.create_slot(
            family_root=family,
            repos=["work"],
            branch="issue-99-test",
            issue="99",
            issue_repo="casehubio/parent",
            covers="99",
            context="Test collision",
        )

        slot_dir = family / "slots" / str(result["slot_number"])
        assert (slot_dir / ".slot").exists()
        # The workspace clone must NOT be at slot_dir/work (that's the repo)
        # It should be at slot_dir/work-casehub (deconflicted)
        assert not any(
            c.args[0] == "git" and "clone" in c.args and str(slot_dir / "work") == c.args[-1]
            for c in mock_cmd.call_args_list
            if len(c.args[0]) > 3 and isinstance(c.args[0], list)
        ), "workspace clone tried to use same path as repo clone"


class TestWriteSlotSettings:
    def test_creates_settings_with_host_fallback(self, tmp_path):
        slot_dir = tmp_path / "slots" / "82"
        slot_dir.mkdir(parents=True)
        settings_path = slot_manager._write_slot_settings(slot_dir)
        assert settings_path.exists()
        content = settings_path.read_text()
        assert "host-m2" in content
        assert "file://" in content
        assert ".m2/repository" in content
        assert "slot-host-fallback" in content

    def test_includes_plugin_repositories(self, tmp_path):
        slot_dir = tmp_path / "slots" / "82"
        slot_dir.mkdir(parents=True)
        settings_path = slot_manager._write_slot_settings(slot_dir)
        content = settings_path.read_text()
        assert "host-m2-plugins" in content
        assert "<pluginRepository>" in content

    def test_snapshots_update_policy_always(self, tmp_path):
        slot_dir = tmp_path / "slots" / "82"
        slot_dir.mkdir(parents=True)
        settings_path = slot_manager._write_slot_settings(slot_dir)
        content = settings_path.read_text()
        assert "<updatePolicy>always</updatePolicy>" in content

    def test_idempotent(self, tmp_path):
        slot_dir = tmp_path / "slots" / "82"
        slot_dir.mkdir(parents=True)
        path1 = slot_manager._write_slot_settings(slot_dir)
        content1 = path1.read_text()
        path2 = slot_manager._write_slot_settings(slot_dir)
        content2 = path2.read_text()
        assert content1 == content2

    def test_settings_path_is_in_slot_dir(self, tmp_path):
        slot_dir = tmp_path / "slots" / "82"
        slot_dir.mkdir(parents=True)
        settings_path = slot_manager._write_slot_settings(slot_dir)
        assert settings_path.parent == slot_dir
        assert settings_path.name == "slot-settings.xml"


class TestSetupMavenConfig:
    def test_creates_new_config_with_repo_local_and_settings(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        repo_wt = slot_dir / "engine"
        repo_wt.mkdir()
        m2 = slot_dir / ".m2"
        slot_manager.setup_maven_config(repo_wt, m2)
        config = (repo_wt / ".mvn" / "maven.config").read_text()
        assert f"-Dmaven.repo.local={m2}" in config
        assert "--settings=.mvn/slot-settings.xml" in config

    def test_generates_slot_settings_xml(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        repo_wt = slot_dir / "engine"
        repo_wt.mkdir()
        m2 = slot_dir / ".m2"
        slot_manager.setup_maven_config(repo_wt, m2)
        assert (slot_dir / "slot-settings.xml").exists()

    def test_copies_settings_into_mvn_dir(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        repo_wt = slot_dir / "engine"
        repo_wt.mkdir()
        m2 = slot_dir / ".m2"
        slot_manager.setup_maven_config(repo_wt, m2)
        local = repo_wt / ".mvn" / "slot-settings.xml"
        assert local.exists()
        assert local.read_text() == (slot_dir / "slot-settings.xml").read_text()

    def test_appends_to_existing_config(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        repo_wt = slot_dir / "engine"
        mvn_dir = repo_wt / ".mvn"
        mvn_dir.mkdir(parents=True)
        (mvn_dir / "maven.config").write_text(
            "-Dquarkus.bootstrap.application-model.serialization.format=jos\n"
        )
        m2 = slot_dir / ".m2"
        slot_manager.setup_maven_config(repo_wt, m2)
        config = (mvn_dir / "maven.config").read_text()
        assert "serialization.format=jos" in config
        assert f"-Dmaven.repo.local={m2}" in config
        assert "--settings=.mvn/slot-settings.xml" in config

    def test_fixes_legacy_dash_s_format(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        repo_wt = slot_dir / "engine"
        mvn_dir = repo_wt / ".mvn"
        mvn_dir.mkdir(parents=True)
        m2 = slot_dir / ".m2"
        (mvn_dir / "maven.config").write_text(
            f"-Dmaven.repo.local={m2}\n"
            f"-s {slot_dir}/slot-settings.xml\n"
        )
        slot_manager.setup_maven_config(repo_wt, m2)
        config = (mvn_dir / "maven.config").read_text()
        assert "-s " not in config
        assert "--settings=.mvn/slot-settings.xml" in config

    def test_idempotent(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        repo_wt = slot_dir / "engine"
        repo_wt.mkdir()
        m2 = slot_dir / ".m2"
        slot_manager.setup_maven_config(repo_wt, m2)
        slot_manager.setup_maven_config(repo_wt, m2)
        config = (repo_wt / ".mvn" / "maven.config").read_text()
        assert config.count("-Dmaven.repo.local=") == 1
        assert config.count("--settings=") == 1

    def test_multiple_repos_share_same_settings(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        m2 = slot_dir / ".m2"
        repo_a = slot_dir / "engine"
        repo_a.mkdir()
        repo_b = slot_dir / "blocks"
        repo_b.mkdir()
        slot_manager.setup_maven_config(repo_a, m2)
        slot_manager.setup_maven_config(repo_b, m2)
        config_a = (repo_a / ".mvn" / "maven.config").read_text()
        config_b = (repo_b / ".mvn" / "maven.config").read_text()
        assert "--settings=.mvn/slot-settings.xml" in config_a
        assert "--settings=.mvn/slot-settings.xml" in config_b
        assert (slot_dir / "slot-settings.xml").exists()
        assert (repo_a / ".mvn" / "slot-settings.xml").exists()
        assert (repo_b / ".mvn" / "slot-settings.xml").exists()


class TestRepointSymlinks:
    def test_repoints_wksp_in_repo(self, tmp_path):
        repo_wt = tmp_path / "slot" / "engine"
        repo_wt.mkdir(parents=True)
        (repo_wt / "wksp").symlink_to("/original/workspace/engine")
        ws_wt = tmp_path / "slot" / "work"
        (ws_wt / "engine").mkdir(parents=True)

        slot_manager.repoint_wksp(repo_wt, ws_wt / "engine")

        assert (repo_wt / "wksp").is_symlink()
        target = (repo_wt / "wksp").readlink()
        assert "work/engine" in str(target)

    def test_creates_proj_in_workspace(self, tmp_path):
        ws_subdir = tmp_path / "slot" / "work" / "engine"
        ws_subdir.mkdir(parents=True)
        repo_wt = tmp_path / "slot" / "engine"
        repo_wt.mkdir(parents=True)

        slot_manager.create_proj_symlink(ws_subdir, repo_wt)

        assert (ws_subdir / "proj").is_symlink()
        target = (ws_subdir / "proj").readlink()
        assert "engine" in str(target)

    def test_repoint_replaces_existing(self, tmp_path):
        repo_wt = tmp_path / "slot" / "engine"
        repo_wt.mkdir(parents=True)
        (repo_wt / "wksp").symlink_to("/old/target")
        new_target = tmp_path / "slot" / "work" / "engine"
        new_target.mkdir(parents=True)

        slot_manager.repoint_wksp(repo_wt, new_target)

        assert (repo_wt / "wksp").is_symlink()
        resolved = (repo_wt / "wksp").resolve()
        assert resolved == new_target


class TestWriteSlotMd:
    def test_writes_slot_md(self, tmp_path):
        slot_manager.write_slot_md(
            tmp_path, 1, ["engine"], "issue-42-spi",
            "42", "casehubio/engine", "42", "Add SPI layer",
        )
        content = (tmp_path / ".slot").read_text()
        assert "# Slot 1" in content
        assert "issue-42-spi" in content
        assert "casehubio/engine#42" in content
        assert "Add SPI layer" in content
        assert "engine (primary)" in content

    def test_multi_repo_slot(self, tmp_path):
        slot_manager.write_slot_md(
            tmp_path, 2, ["engine", "iot"], "issue-55-cross",
            "55", "casehubio/engine", "55,56", "Cross-repo work",
        )
        content = (tmp_path / ".slot").read_text()
        assert "engine (primary)" in content
        assert "- iot" in content
        assert "55,56" in content


class TestCreateSlot:
    @patch("slot_manager.run_cmd")
    def test_creates_single_repo_slot(self, mock_cmd, tmp_path):
        family = tmp_path / "casehub"
        family.mkdir()
        engine = init_repo(family / "engine")
        shared_ws = init_repo(tmp_path / "public" / "casehub")
        (shared_ws / "engine").mkdir()
        (engine / "wksp").symlink_to(shared_ws / "engine")

        mock_cmd.return_value = (0, "", "")

        result = slot_manager.create_slot(
            family_root=family,
            repos=["engine"],
            branch="issue-42-spi",
            issue="42",
            issue_repo="casehubio/engine",
            covers="42",
            context="Add SPI layer",
        )

        assert result["slot_number"] == 1
        slot_dir = family / "slots" / "1"
        assert slot_dir.is_dir()
        assert (slot_dir / ".m2").is_dir()
        assert (slot_dir / ".slot").exists()
        assert "issue-42-spi" in (slot_dir / ".slot").read_text()

    @patch("slot_manager.run_cmd")
    def test_slot_numbering_increments(self, mock_cmd, tmp_path):
        family = tmp_path / "casehub"
        (family / "slots" / "1").mkdir(parents=True)
        engine = init_repo(family / "engine")
        shared_ws = init_repo(tmp_path / "public" / "casehub")
        (shared_ws / "engine").mkdir()
        (engine / "wksp").symlink_to(shared_ws / "engine")

        mock_cmd.return_value = (0, "", "")

        result = slot_manager.create_slot(
            family_root=family,
            repos=["engine"],
            branch="issue-55-ledger",
            issue="55",
            issue_repo="casehubio/engine",
            covers="55",
            context="Fix ledger",
        )
        assert result["slot_number"] == 2

    @patch("slot_manager.run_cmd")
    def test_clone_failure_exits(self, mock_cmd, tmp_path, capsys):
        family = tmp_path / "casehub"
        engine = init_repo(family / "engine")
        shared_ws = init_repo(tmp_path / "public" / "casehub")
        (shared_ws / "engine").mkdir()
        (engine / "wksp").symlink_to(shared_ws / "engine")

        mock_cmd.side_effect = [
            (0, "", ""),  # fetch
            (0, "", ""),  # remote get-url upstream check
            (0, "", ""),  # fetch upstream
            (0, "", ""),  # rebase upstream
            (0, "", ""),  # push origin
            (1, "", "fatal: clone failed"),  # clone fails
        ]

        with pytest.raises(SystemExit):
            slot_manager.create_slot(
                family_root=family,
                repos=["engine"],
                branch="issue-42-spi",
                issue="42",
                issue_repo="casehubio/engine",
                covers="42",
                context="test",
            )
        captured = capsys.readouterr()
        assert "ERROR=clone_failed" in captured.out


class TestListSlots:
    def test_empty_slots(self, tmp_path):
        family = tmp_path / "casehub"
        (family / "slots").mkdir(parents=True)
        slots = slot_manager.list_slots(family)
        assert slots == []

    def test_active_slot(self, tmp_path):
        family = tmp_path / "casehub"
        slot = family / "slots" / "1"
        slot.mkdir(parents=True)
        (slot / ".slot").write_text("# Slot 1 — issue-42-spi\n")
        (slot / "engine").mkdir()
        (slot / "engine" / ".git").write_text("gitdir: /fake/.git/worktrees/engine")

        slots = slot_manager.list_slots(family)
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

        slots = slot_manager.list_slots(family)
        assert slots[0]["state"] == "ready to land"

    def test_no_slots_dir(self, tmp_path):
        family = tmp_path / "casehub"
        family.mkdir()
        slots = slot_manager.list_slots(family)
        assert slots == []


class TestRemoveSlot:
    def test_archives_to_attic_by_default(self, tmp_path):
        family = tmp_path / "casehub"
        slot = family / "slots" / "1"
        slot.mkdir(parents=True)
        (slot / ".slot").write_text("test")
        (slot / ".m2").mkdir()
        (slot / ".landed").write_text("branch=test\n")

        with patch("slot_manager.run_cmd") as mock_cmd:
            mock_cmd.return_value = (0, "", "")
            slot_manager.remove_slot(family, 1)

        assert not slot.exists()
        attic = family / "slots" / "attic" / "1"
        assert attic.exists()
        assert (attic / ".slot").exists()

    def test_preserves_repos_in_attic(self, tmp_path):
        """Default remove archives to attic with repos intact."""
        family = tmp_path / "casehub"
        slot = family / "slots" / "1"
        slot.mkdir(parents=True)
        (slot / ".slot").write_text("test")
        (slot / ".landed").write_text("branch=test\n")
        repo = slot / "myrepo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / "src.java").write_text("class Foo {}")

        with patch("slot_manager.run_cmd") as mock_cmd:
            mock_cmd.return_value = (0, "", "")
            slot_manager.remove_slot(family, 1)

        attic = family / "slots" / "attic" / "1"
        assert (attic / "myrepo" / "src.java").exists(), "repo deleted during archive — attic is useless without it"

    def test_force_delete_permanently_removes(self, tmp_path):
        family = tmp_path / "casehub"
        slot = family / "slots" / "1"
        slot.mkdir(parents=True)
        (slot / ".slot").write_text("test")

        with patch("slot_manager.run_cmd") as mock_cmd:
            mock_cmd.return_value = (0, "", "")
            slot_manager.remove_slot(family, 1, force_delete=True)

        assert not slot.exists()
        assert not (family / "slots" / "attic" / "1").exists()

    def test_nonexistent_slot_errors(self, tmp_path, capsys):
        family = tmp_path / "casehub"
        (family / "slots").mkdir(parents=True)

        with pytest.raises(SystemExit):
            slot_manager.remove_slot(family, 99)
        captured = capsys.readouterr()
        assert "ERROR=slot_not_found" in captured.out


class TestParseSlotMd:
    def test_parses_full_slot_md(self, tmp_path):
        (tmp_path / ".slot").write_text(
            "# Slot 1 — issue-42-spi\n\n## Issue\ncasehubio/engine#42\n"
            "Covers: 42\n\n## What to do\nImplement SPI\n\n## Repos\n- engine (primary)\n- iot\n"
        )
        md = slot_manager.parse_slot_md(tmp_path)
        assert md["branch"] == "issue-42-spi"
        assert md["issue"] == "42"
        assert md["issue_repo"] == "casehubio/engine"
        assert md["covers"] == "42"
        assert md["context"] == "Implement SPI"
        assert md["repos"] == ["engine", "iot"]

    def test_detects_epic_type(self, tmp_path):
        (tmp_path / ".slot").write_text(
            "# Slot 1 — issue-50-profiles\n\n## Issue\n"
            "casehubio/engine#50\nCovers: 108\nType: epic\n"
            "Safe exit: after any completed batch\n\n"
            "## What to do\nEpic work\n\n## Repos\n- engine\n"
        )
        md = slot_manager.parse_slot_md(tmp_path)
        assert md["is_epic"] is True
        assert md["issue"] == "50"
        assert md["issue_repo"] == "casehubio/engine"

    def test_non_epic_defaults_false(self, tmp_path):
        (tmp_path / ".slot").write_text(
            "# Slot 1 — issue-42-spi\n\n## Issue\n"
            "casehubio/engine#42\nCovers: 42\n\n"
            "## What to do\nSPI work\n\n## Repos\n- engine\n"
        )
        md = slot_manager.parse_slot_md(tmp_path)
        assert md.get("is_epic") is False

    def test_missing_slot_md(self, tmp_path):
        assert slot_manager.parse_slot_md(tmp_path) == {}


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

        result = slot_manager.scan_ready(tmp_path)
        assert len(result) == 1
        assert result[0]["number"] == 1
        assert result[0]["branch"] == "issue-42-spi"
        assert result[0]["context"] == "Implement SPI"

    def test_empty_when_no_ready_slots(self, tmp_path):
        worktrees = tmp_path / "slots"
        worktrees.mkdir()
        (worktrees / "1").mkdir()
        assert slot_manager.scan_ready(tmp_path) == []

    def test_no_slots_dir(self, tmp_path):
        assert slot_manager.scan_ready(tmp_path) == []


def _init_repo_with_remote(path: Path) -> Path:
    bare = path.parent / f".{path.name}-bare.git"
    bare.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--bare", str(bare)], capture_output=True, check=True)
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", str(bare), str(path)], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@test.com"], capture_output=True)
    subprocess.run(["git", "-C", str(path), "checkout", "-b", "main"], capture_output=True)
    (path / "README.md").write_text(f"# {path.name}\n")
    subprocess.run(["git", "-C", str(path), "add", "."], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-m", "initial"], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "push", "-u", "origin", "main"], capture_output=True, check=True)
    return path


def _create_merge_test_repos(tmp_path, repo_names):
    family = tmp_path / "family"
    family.mkdir()
    worktrees = family / "slots"
    worktrees.mkdir()

    originals = {}
    for name in repo_names:
        originals[name] = _init_repo_with_remote(family / name)

    slot = worktrees / "1"
    slot.mkdir()
    branch = "issue-42-test"

    for name in repo_names:
        subprocess.run([
            "git", "-C", str(originals[name]),
            "worktree", "add", str(slot / name), "-b", branch,
        ], capture_output=True, check=True)
        (slot / name / "feature.py").write_text(f"# {name} feature\n")
        subprocess.run(["git", "-C", str(slot / name), "add", "."], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(slot / name), "commit", "-m", f"feat: {name} feature"], capture_output=True, check=True)

    (slot / ".phase-a-complete").write_text(
        f"branch={branch}\nrepos={','.join(repo_names)}\ntimestamp=2026-07-18T14:32:00\n"
    )
    (slot / ".slot").write_text(
        f"# Slot 1 — {branch}\n\n## Issue\ntest/repo#42\nCovers: 42\n\n"
        f"## What to do\nTest\n\n## Repos\n" +
        "\n".join(f"- {n}" for n in repo_names) + "\n"
    )
    return family, originals, slot, branch


class TestResolveOriginalRepo:
    def test_resolves_worktree_to_original(self, tmp_path):
        family, originals, slot, _ = _create_merge_test_repos(tmp_path, ["engine"])
        resolved = slot_manager.resolve_original_repo(slot / "engine")
        assert resolved == originals["engine"]


class TestMergeSlot:
    def test_clean_rebase_and_push(self, tmp_path):
        family, originals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        exit_code = slot_manager.merge_slot(family, 1)
        assert exit_code == 0
        assert (originals["engine"] / "feature.py").exists()
        assert (slot / ".landed").exists()
        landed = (slot / ".landed").read_text()
        assert "branch=issue-42-test" in landed
        assert "engine:" in landed

    def test_conflict_returns_error(self, tmp_path):
        family, originals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        (originals["engine"] / "feature.py").write_text("# conflict\n")
        subprocess.run(["git", "-C", str(originals["engine"]), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(originals["engine"]), "commit", "-m", "conflict"], capture_output=True)
        exit_code = slot_manager.merge_slot(family, 1)
        assert exit_code != 0
        assert not (slot / ".landed").exists()

    def test_not_found(self, tmp_path):
        family = tmp_path / "family"
        (family / "slots").mkdir(parents=True)
        assert slot_manager.merge_slot(family, 99) == 1

    def test_not_ready(self, tmp_path):
        family = tmp_path / "family"
        slot = family / "slots" / "1"
        slot.mkdir(parents=True)
        assert slot_manager.merge_slot(family, 1) == 1

    def test_already_landed(self, tmp_path):
        family, _, slot, _ = _create_merge_test_repos(tmp_path, ["engine"])
        (slot / ".landed").write_text("already\n")
        assert slot_manager.merge_slot(family, 1) == 1


class TestIsSlotLanded:
    def test_true_with_landed_marker(self, tmp_path):
        (tmp_path / ".landed").write_text("branch=test\n")
        assert slot_manager.is_slot_landed(tmp_path) is True

    def test_false_without_landed_marker(self, tmp_path):
        assert slot_manager.is_slot_landed(tmp_path) is False

    def test_stamp_commit_alone_is_not_sufficient(self, tmp_path):
        repo = tmp_path / "engine"
        repo.mkdir()
        (repo / ".git").write_text("gitdir: /fake")
        assert slot_manager.is_slot_landed(tmp_path) is False


class TestMergeSlotStamping:
    def test_writes_stamp_commits_on_merge(self, tmp_path):
        family, originals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        exit_code = slot_manager.merge_slot(family, 1)
        assert exit_code == 0

        rc, log, _ = slot_manager.run_cmd(
            ["git", "-C", str(slot / "engine"), "log", "-1", "--format=%s"]
        )
        assert rc == 0
        assert log.strip().startswith("chore: branch closed — landed as")
        assert "on main" in log.strip()

    def test_stamp_sha_matches_landed_shas(self, tmp_path):
        family, originals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        slot_manager.merge_slot(family, 1)

        landed = (slot / ".landed").read_text()
        sha_from_landed = ""
        for line in landed.splitlines():
            if line.startswith("landed_shas="):
                for entry in line.split("=", 1)[1].split(","):
                    if entry.startswith("engine:"):
                        sha_from_landed = entry.split(":", 1)[1]

        rc, log, _ = slot_manager.run_cmd(
            ["git", "-C", str(slot / "engine"), "log", "-1", "--format=%s"]
        )
        assert sha_from_landed in log.strip()

    def test_multi_repo_all_stamped(self, tmp_path):
        family, originals, slot, branch = _create_merge_test_repos(
            tmp_path, ["engine", "iot"]
        )
        slot_manager.merge_slot(family, 1)

        for repo_name in ["engine", "iot"]:
            rc, log, _ = slot_manager.run_cmd(
                ["git", "-C", str(slot / repo_name), "log", "-1", "--format=%s"]
            )
            assert rc == 0
            assert log.strip().startswith("chore: branch closed")

    def test_no_stamp_on_merge_failure(self, tmp_path):
        family, originals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        (originals["engine"] / "feature.py").write_text("# conflict\n")
        subprocess.run(["git", "-C", str(originals["engine"]), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(originals["engine"]), "commit", "-m", "conflict"], capture_output=True)

        slot_manager.merge_slot(family, 1)

        rc, log, _ = slot_manager.run_cmd(
            ["git", "-C", str(slot / "engine"), "log", "-1", "--format=%s"]
        )
        assert "chore: branch closed" not in log.strip()


class TestVerifyLandedShas:
    def test_passes_when_sha_on_main(self, tmp_path):
        family, originals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        slot_manager.merge_slot(family, 1)

        ok, failures = slot_manager.verify_landed_shas(slot, family)
        assert ok is True
        assert failures == []

    def test_fails_when_sha_not_on_main(self, tmp_path):
        family, _, slot, _ = _create_merge_test_repos(tmp_path, ["engine"])
        rc, sha, _ = slot_manager.run_cmd(
            ["git", "-C", str(slot / "engine"), "rev-parse", "HEAD"]
        )
        (slot / ".landed").write_text(
            f"branch=issue-42-test\nrepos=engine\nlanded_shas=engine:{sha.strip()}\n"
        )

        ok, failures = slot_manager.verify_landed_shas(slot, family)
        assert ok is False
        assert len(failures) == 1
        assert "not reachable from main" in failures[0]

    def test_fails_with_no_landed_marker(self, tmp_path):
        ok, failures = slot_manager.verify_landed_shas(tmp_path, tmp_path)
        assert ok is False
        assert "no .landed marker" in failures[0]

    def test_fails_with_unknown_sha(self, tmp_path):
        family, _, slot, _ = _create_merge_test_repos(tmp_path, ["engine"])
        (slot / ".landed").write_text(
            "branch=issue-42-test\nrepos=engine\nlanded_shas=engine:unknown\n"
        )

        ok, failures = slot_manager.verify_landed_shas(slot, family)
        assert ok is False
        assert "unknown" in failures[0]


class TestArchiveSlot:
    def test_moves_to_attic_after_verified_merge(self, tmp_path):
        family, originals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        slot_manager.merge_slot(family, 1)

        slot_manager.archive_slot(family, 1)

        assert not (family / "slots" / "1").exists()
        attic_slot = family / "slots" / "attic" / "1"
        assert attic_slot.exists()
        assert (attic_slot / ".slot").exists()
        assert (attic_slot / ".landed").exists()

    def test_preserves_repos_in_attic(self, tmp_path):
        """Archived slot must retain repo directories — attic is the recovery safety net."""
        family, originals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        slot_manager.merge_slot(family, 1)

        assert (slot / "engine").is_dir()
        slot_manager.archive_slot(family, 1)

        attic_slot = family / "slots" / "attic" / "1"
        assert (attic_slot / "engine").exists(), "repo deleted during archive — attic is useless without it"

    def test_blocks_archive_without_landed_marker(self, tmp_path, capsys):
        family, _, slot, _ = _create_merge_test_repos(tmp_path, ["engine"])

        with pytest.raises(SystemExit):
            slot_manager.archive_slot(family, 1)
        captured = capsys.readouterr()
        assert "ERROR=slot_not_landed" in captured.out

    def test_blocks_archive_when_sha_not_on_main(self, tmp_path, capsys):
        family, _, slot, _ = _create_merge_test_repos(tmp_path, ["engine"])
        rc, sha, _ = slot_manager.run_cmd(
            ["git", "-C", str(slot / "engine"), "rev-parse", "HEAD"]
        )
        (slot / ".landed").write_text(
            f"branch=issue-42-test\nrepos=engine\nlanded_shas=engine:{sha.strip()}\n"
        )

        with pytest.raises(SystemExit):
            slot_manager.archive_slot(family, 1)
        captured = capsys.readouterr()
        assert "ERROR=sha_not_on_main" in captured.out

    def test_force_bypasses_all_checks(self, tmp_path):
        family, _, slot, _ = _create_merge_test_repos(tmp_path, ["engine"])

        slot_manager.archive_slot(family, 1, force=True)

        assert not (family / "slots" / "1").exists()
        assert (family / "slots" / "attic" / "1").exists()

    def test_relocates_claude_projects(self, tmp_path, monkeypatch):
        family, originals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        slot_manager.merge_slot(family, 1)

        fake_home = tmp_path / "home"
        claude_projects = fake_home / ".claude" / "projects"
        claude_projects.mkdir(parents=True)
        slot_path_encoded = str(slot / "engine").replace("/", "-")
        proj_dir = claude_projects / slot_path_encoded
        proj_dir.mkdir()
        (proj_dir / "memory.md").write_text("session memory")

        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

        slot_manager.archive_slot(family, 1)

        assert not proj_dir.exists()
        attic_path = family / "slots" / "attic" / "1"
        dest_encoded = str(attic_path / "engine").replace("/", "-")
        moved_dir = claude_projects / dest_encoded
        assert moved_dir.exists()
        assert (moved_dir / "memory.md").read_text() == "session memory"

    def test_not_found_exits(self, tmp_path, capsys):
        family = tmp_path / "family"
        (family / "slots").mkdir(parents=True)
        with pytest.raises(SystemExit):
            slot_manager.archive_slot(family, 99)
        captured = capsys.readouterr()
        assert "ERROR=slot_not_found" in captured.out


class TestListSlotsExtended:
    def test_shows_landed_state(self, tmp_path):
        worktrees = tmp_path / "slots"
        worktrees.mkdir()
        slot = worktrees / "1"
        slot.mkdir()
        (slot / ".phase-a-complete").write_text("branch=issue-42\n")
        (slot / ".landed").write_text("landed\n")
        (slot / ".slot").write_text("# Slot 1 — issue-42\n")

        result = slot_manager.list_slots(tmp_path, include_archived=False)
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

        result_no_all = slot_manager.list_slots(tmp_path, include_archived=False)
        assert len(result_no_all) == 0

        result_all = slot_manager.list_slots(tmp_path, include_archived=True)
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

        result = slot_manager.list_slots(tmp_path, include_archived=False)
        assert all(s["number"] != 68 for s in result), \
            "archived slot 68 appeared as active due to remnant directory"

        result_all = slot_manager.list_slots(tmp_path, include_archived=True)
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
        result = slot_manager.list_slots(tmp_path)
        assert len(result) == 1
        assert result[0]["state"] == "active"


class TestCLI:
    def test_parse_args_create(self):
        sys.argv = ["slot_manager.py", "create-slot", "/path/to/family",
                     "repos=engine,iot", "branch=issue-42"]
        args = slot_manager.parse_args()
        assert args["subcommand"] == "create-slot"
        assert args["target"] == "/path/to/family"
        assert args["repos"] == "engine,iot"

    def test_parse_args_list(self):
        sys.argv = ["slot_manager.py", "list-slots", "/path/to/family"]
        args = slot_manager.parse_args()
        assert args["subcommand"] == "list-slots"
        assert args["target"] == "/path/to/family"

    def test_missing_repos_error(self, capsys):
        sys.argv = ["slot_manager.py", "create-slot", "/path"]
        with pytest.raises(SystemExit):
            slot_manager.main()
        captured = capsys.readouterr()
        assert "ERROR=missing_repos" in captured.out

    def test_missing_slot_number_error(self, capsys):
        sys.argv = ["slot_manager.py", "remove-slot", "/path"]
        with pytest.raises(SystemExit):
            slot_manager.main()
        captured = capsys.readouterr()
        assert "ERROR=missing_slot_number" in captured.out


def _create_clone_test_repos(tmp_path, repo_names):
    """Create a test family with clone-based slots (new model)."""
    family = tmp_path / "family"
    family.mkdir()
    worktrees = family / "slots"
    worktrees.mkdir()

    originals = {}
    for name in repo_names:
        originals[name] = _init_repo_with_remote(family / name)

    slot = worktrees / "1"
    slot.mkdir()
    branch = "issue-42-test"

    for name in repo_names:
        subprocess.run([
            "git", "clone", "--shared", "--branch", "main",
            str(originals[name]), str(slot / name),
        ], capture_output=True, check=True)
        subprocess.run([
            "git", "-C", str(slot / name), "checkout", "-b", branch,
        ], capture_output=True, check=True)
        (slot / name / "feature.py").write_text(f"# {name} feature\n")
        subprocess.run(["git", "-C", str(slot / name), "add", "."], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(slot / name), "commit", "-m", f"feat: {name} feature"], capture_output=True, check=True)

    (slot / ".phase-a-complete").write_text(
        f"branch={branch}\nrepos={','.join(repo_names)}\ntimestamp=2026-07-18T14:32:00\n"
    )
    (slot / ".slot").write_text(
        f"# Slot 1 — {branch}\n\n## Issue\ntest/repo#42\nCovers: 42\n\n"
        f"## What to do\nTest\n\n## Repos\n" +
        "\n".join(f"- {n}" for n in repo_names) + "\n"
    )
    return family, originals, slot, branch


class TestIsWorktree:
    def test_worktree_detected(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").write_text("gitdir: /some/path/.git/worktrees/repo")
        assert slot_manager.is_worktree(repo) is True

    def test_clone_not_detected(self, tmp_path):
        repo = init_repo(tmp_path / "repo")
        assert slot_manager.is_worktree(repo) is False

    def test_no_git_not_detected(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        assert slot_manager.is_worktree(repo) is False


class TestResolveOriginalRepoClone:
    def test_resolves_clone_to_original(self, tmp_path):
        original = _init_repo_with_remote(tmp_path / "original")
        clone = tmp_path / "clone"
        subprocess.run([
            "git", "clone", "--shared", str(original), str(clone),
        ], capture_output=True, check=True)
        resolved = slot_manager.resolve_original_repo(clone)
        assert resolved == original.resolve()

    def test_resolves_worktree_to_original(self, tmp_path):
        family, originals, slot, _ = _create_merge_test_repos(tmp_path, ["engine"])
        resolved = slot_manager.resolve_original_repo(slot / "engine")
        assert resolved == originals["engine"]

    def test_fallback_returns_self(self, tmp_path):
        repo = init_repo(tmp_path / "standalone")
        resolved = slot_manager.resolve_original_repo(repo)
        assert resolved == repo


class TestExcludeSymlinks:
    def test_adds_entries_to_exclude(self, tmp_path):
        repo = init_repo(tmp_path / "repo")
        slot_manager._exclude_symlinks(repo)
        exclude = (repo / ".git" / "info" / "exclude").read_text()
        assert "proj" in exclude
        assert "wksp" in exclude

    def test_idempotent(self, tmp_path):
        repo = init_repo(tmp_path / "repo")
        slot_manager._exclude_symlinks(repo)
        slot_manager._exclude_symlinks(repo)
        exclude = (repo / ".git" / "info" / "exclude").read_text()
        non_comment = [l.strip() for l in exclude.splitlines() if l.strip() and not l.startswith("#")]
        assert non_comment.count("proj") == 1
        assert non_comment.count("wksp") == 1


class TestMergeSlotClone:
    def test_clone_merge_pushes_then_merges(self, tmp_path):
        family, originals, slot, branch = _create_clone_test_repos(tmp_path, ["engine"])
        exit_code = slot_manager.merge_slot(family, 1)
        assert exit_code == 0
        assert (originals["engine"] / "feature.py").exists()
        assert (slot / ".landed").exists()

    def test_clone_multi_repo_merge(self, tmp_path):
        family, originals, slot, branch = _create_clone_test_repos(tmp_path, ["engine", "iot"])
        exit_code = slot_manager.merge_slot(family, 1)
        assert exit_code == 0
        for name in ["engine", "iot"]:
            assert (originals[name] / "feature.py").exists()

    def test_clone_stamps_pushed_to_original(self, tmp_path):
        family, originals, slot, branch = _create_clone_test_repos(tmp_path, ["engine"])
        slot_manager.merge_slot(family, 1)
        rc, log, _ = slot_manager.run_cmd(
            ["git", "-C", str(originals["engine"]), "log", "--all", "--oneline", "--grep=branch closed"]
        )
        assert "branch closed" in log


class TestMergeSlotOriginalSafety:
    def test_fails_when_original_not_on_main(self, tmp_path, capsys):
        family, originals, slot, branch = _create_clone_test_repos(tmp_path, ["engine"])
        subprocess.run(
            ["git", "-C", str(originals["engine"]), "checkout", "-b", "some-other-branch"],
            capture_output=True, check=True,
        )
        exit_code = slot_manager.merge_slot(family, 1)
        assert exit_code != 0
        assert not (slot / ".landed").exists()
        out = capsys.readouterr().out
        assert "not_on_main" in out.lower()

    def test_fails_when_original_has_dirty_worktree(self, tmp_path, capsys):
        family, originals, slot, branch = _create_clone_test_repos(tmp_path, ["engine"])
        (originals["engine"] / "dirty.txt").write_text("uncommitted change\n")
        subprocess.run(
            ["git", "-C", str(originals["engine"]), "add", "dirty.txt"],
            capture_output=True, check=True,
        )
        exit_code = slot_manager.merge_slot(family, 1)
        assert exit_code != 0
        assert not (slot / ".landed").exists()
        out = capsys.readouterr().out
        assert "dirty" in out.lower() or "DIRTY" in out

    def test_checks_all_originals_before_merging_any(self, tmp_path, capsys):
        family, originals, slot, branch = _create_clone_test_repos(
            tmp_path, ["engine", "iot"]
        )
        # Put iot on the wrong branch — engine is fine
        subprocess.run(
            ["git", "-C", str(originals["iot"]), "checkout", "-b", "detour"],
            capture_output=True, check=True,
        )
        exit_code = slot_manager.merge_slot(family, 1)
        assert exit_code != 0
        assert not (slot / ".landed").exists()
        # Engine must NOT have been merged even though it was fine
        rc, log, _ = slot_manager.run_cmd(
            ["git", "-C", str(originals["engine"]), "log", "--oneline", "-5"]
        )
        assert "feat: engine feature" not in log

    def test_fails_when_original_not_on_main_worktree(self, tmp_path, capsys):
        family, originals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        # Worktree-based: detach original from main
        subprocess.run(
            ["git", "-C", str(originals["engine"]), "checkout", "-b", "detour"],
            capture_output=True, check=True,
        )
        exit_code = slot_manager.merge_slot(family, 1)
        assert exit_code != 0
        assert not (slot / ".landed").exists()


class TestEnsureCloneLayout:
    def test_migrates_worktree_to_clone(self, tmp_path):
        family, originals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        assert slot_manager.is_worktree(slot / "engine")
        count = slot_manager.ensure_clone_layout(slot)
        assert count >= 1
        assert not slot_manager.is_worktree(slot / "engine")
        assert (slot / "engine" / ".git").is_dir()
        assert (slot / "engine" / "feature.py").exists()

    def test_noop_on_clones(self, tmp_path):
        family, originals, slot, branch = _create_clone_test_repos(tmp_path, ["engine"])
        count = slot_manager.ensure_clone_layout(slot)
        assert count == 0

    def test_migrated_slot_can_merge(self, tmp_path):
        family, originals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        slot_manager.ensure_clone_layout(slot)
        exit_code = slot_manager.merge_slot(family, 1)
        assert exit_code == 0
        assert (originals["engine"] / "feature.py").exists()


class TestCleanupRemnantDir:
    def test_removes_idea_directory(self, tmp_path):
        target = tmp_path / "repo"
        target.mkdir()
        (target / ".idea").mkdir()
        (target / ".idea" / "workspace.xml").write_text("<xml/>")
        assert slot_manager._cleanup_remnant_dir(target) is True
        assert not target.exists()

    def test_removes_multiple_ide_artifacts(self, tmp_path):
        target = tmp_path / "repo"
        target.mkdir()
        for name in [".idea", ".run", ".vscode"]:
            d = target / name
            d.mkdir()
            (d / "config").write_text("x")
        assert slot_manager._cleanup_remnant_dir(target) is True
        assert not target.exists()

    def test_preserves_non_ide_content(self, tmp_path):
        target = tmp_path / "repo"
        target.mkdir()
        (target / ".idea").mkdir()
        (target / "src.java").write_text("class Foo {}")
        assert slot_manager._cleanup_remnant_dir(target) is False
        assert target.exists()
        assert not (target / ".idea").exists()
        assert (target / "src.java").exists()

    def test_nonexistent_path_returns_true(self, tmp_path):
        assert slot_manager._cleanup_remnant_dir(tmp_path / "nonexistent") is True

    def test_already_empty_dir(self, tmp_path):
        target = tmp_path / "empty"
        target.mkdir()
        assert slot_manager._cleanup_remnant_dir(target) is True
        assert not target.exists()

    def test_nested_ide_artifacts(self, tmp_path):
        """Slot dir with subdirs that each only have IDE artifacts."""
        slot = tmp_path / "slot"
        slot.mkdir()
        engine = slot / "engine"
        engine.mkdir()
        (engine / ".idea").mkdir()
        (engine / ".idea" / "workspace.xml").write_text("<xml/>")
        assert slot_manager._cleanup_remnant_dir(slot) is True
        assert not slot.exists()


class TestMigrateWorktreeIdeCleanup:
    def test_migration_succeeds_despite_ide_artifacts(self, tmp_path):
        """After git worktree remove leaves .idea behind, migration should clean it and succeed."""
        family, originals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        wt_path = slot / "engine"
        assert slot_manager.is_worktree(wt_path)

        (wt_path / ".idea").mkdir()
        (wt_path / ".idea" / "workspace.xml").write_text("<xml/>")

        result = slot_manager._migrate_worktree_to_clone(wt_path)
        assert result is True
        assert not slot_manager.is_worktree(wt_path)
        assert (wt_path / ".git").is_dir()
        assert (wt_path / "feature.py").exists()


class TestArchiveSlotDoubleArchive:
    def test_blocks_when_attic_slot_already_exists(self, tmp_path, capsys):
        """archive_slot must refuse if attic/<N>/ already exists — prevents nesting."""
        family, originals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        slot_manager.merge_slot(family, 1)

        # First archive — should succeed
        slot_manager.archive_slot(family, 1)
        assert (family / "slots" / "attic" / "1").exists()

        # Recreate slot dir (simulates remnant ghost)
        (family / "slots" / "1").mkdir()
        (family / "slots" / "1" / ".slot").write_text("ghost")

        # Second archive — should error, not nest
        with pytest.raises(SystemExit):
            slot_manager.archive_slot(family, 1, force=True)
        captured = capsys.readouterr()
        assert "ERROR=attic_slot_exists" in captured.out


class TestArchiveSlotCleanup:
    def test_cleans_remnant_after_move(self, tmp_path):
        """If shutil.move succeeds but source dir reappears, archive cleans it up."""
        family, originals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        slot_manager.merge_slot(family, 1)

        original_move = shutil.move

        def move_then_recreate(src, dst):
            result = original_move(src, dst)
            Path(src).mkdir(parents=True)
            (Path(src) / "engine").mkdir()
            (Path(src) / "engine" / ".idea").mkdir()
            return result

        with patch("slot_manager.shutil.move", side_effect=move_then_recreate):
            slot_manager.archive_slot(family, 1)

        assert not slot.exists(), "remnant directory should be cleaned after archive"
        assert (family / "slots" / "attic" / "1").exists()

    def test_warns_if_remnant_persists(self, tmp_path, capsys):
        """If cleanup can't remove the dir (non-IDE content), warn."""
        family, originals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        slot_manager.merge_slot(family, 1)

        original_move = shutil.move

        def move_then_recreate_with_content(src, dst):
            result = original_move(src, dst)
            Path(src).mkdir(parents=True)
            (Path(src) / "real_file.txt").write_text("not an IDE artifact")
            return result

        with patch("slot_manager.shutil.move", side_effect=move_then_recreate_with_content):
            slot_manager.archive_slot(family, 1)

        captured = capsys.readouterr()
        assert "WARN=remnant_dir_persists" in captured.out


class TestEscapeSlotCwd:
    def test_escapes_when_cwd_inside_slot(self, tmp_path):
        slot = tmp_path / "slots" / "1"
        slot.mkdir(parents=True)
        escape_to = tmp_path
        original_cwd = os.getcwd()
        try:
            os.chdir(slot)
            assert slot_manager._escape_slot_cwd(slot, escape_to) is True
            assert Path.cwd().resolve() == escape_to.resolve()
        finally:
            os.chdir(original_cwd)

    def test_escapes_when_cwd_in_subdirectory(self, tmp_path):
        slot = tmp_path / "slots" / "1"
        engine = slot / "engine"
        engine.mkdir(parents=True)
        escape_to = tmp_path
        original_cwd = os.getcwd()
        try:
            os.chdir(engine)
            assert slot_manager._escape_slot_cwd(slot, escape_to) is True
            assert Path.cwd().resolve() == escape_to.resolve()
        finally:
            os.chdir(original_cwd)

    def test_noop_when_cwd_outside_slot(self, tmp_path):
        slot = tmp_path / "slots" / "1"
        slot.mkdir(parents=True)
        escape_to = tmp_path
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            assert slot_manager._escape_slot_cwd(slot, escape_to) is False
        finally:
            os.chdir(original_cwd)


class TestArchiveSlotPromotionGate:
    def test_warns_when_no_promotion_stamp(self, tmp_path, capsys):
        """archive_slot should warn when .artifacts-promoted stamp is missing."""
        family, originals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        slot_manager.merge_slot(family, 1)

        # No .artifacts-promoted stamp — promotion never ran
        slot_manager.archive_slot(family, 1)

        captured = capsys.readouterr()
        assert "WARN=artifacts_not_promoted" in captured.out

    def test_no_warning_when_stamp_exists(self, tmp_path, capsys):
        """No warning when .artifacts-promoted stamp is present."""
        family, originals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        slot_manager.merge_slot(family, 1)

        # Simulate promotion stamp from close_artifacts.py
        ws_dirs = [d for d in slot.iterdir() if d.is_dir() and d.name.startswith("work")]
        # No workspace dir in this test — create a fake design/ with stamp
        # The stamp lives in workspace design/ but for non-workspace slots, we check the slot itself
        stamp_dir = slot / "design"
        stamp_dir.mkdir(exist_ok=True)
        (stamp_dir / ".artifacts-promoted").write_text("timestamp=2026-07-31\n")

        slot_manager.archive_slot(family, 1)

        captured = capsys.readouterr()
        assert "WARN=artifacts_not_promoted" not in captured.out

    def test_force_archive_still_warns_about_promotion(self, tmp_path, capsys):
        """Even --force should warn about missing promotion stamp."""
        family, _, slot, _ = _create_merge_test_repos(tmp_path, ["engine"])

        slot_manager.archive_slot(family, 1, force=True)

        captured = capsys.readouterr()
        assert "WARN=artifacts_not_promoted" in captured.out


class TestClaudeProjectMatching:
    def test_exact_match(self):
        assert slot_manager._claude_project_matches(
            "-path-worktrees-1", "-path-worktrees-1"
        ) is True

    def test_subdirectory_match(self):
        assert slot_manager._claude_project_matches(
            "-path-worktrees-1-engine", "-path-worktrees-1"
        ) is True

    def test_no_false_positive_on_prefix_number(self):
        """Slot 1 must not match slot 10, 11, 100, etc."""
        assert slot_manager._claude_project_matches(
            "-path-worktrees-10", "-path-worktrees-1"
        ) is False
        assert slot_manager._claude_project_matches(
            "-path-worktrees-10-engine", "-path-worktrees-1"
        ) is False

    def test_no_match_on_unrelated(self):
        assert slot_manager._claude_project_matches(
            "-path-worktrees-2-engine", "-path-worktrees-1"
        ) is False


class TestIsProjectRepo:
    def test_excludes_workspace_dirs(self):
        assert slot_manager.is_project_repo("work") is False
        assert slot_manager.is_project_repo("work-casehub") is False
        assert slot_manager.is_project_repo("work-casehub-ras") is False

    def test_includes_real_repos(self):
        assert slot_manager.is_project_repo("engine") is True
        assert slot_manager.is_project_repo("blocks") is True

    def test_includes_worker_named_repos(self):
        """Repos named 'worker', 'workflow' etc must not be excluded."""
        assert slot_manager.is_project_repo("worker") is True
        assert slot_manager.is_project_repo("workflow") is True
        assert slot_manager.is_project_repo("workbench") is True

    def test_excludes_infrastructure_dirs(self):
        assert slot_manager.is_project_repo(".m2") is False
        assert slot_manager.is_project_repo("attic") is False


class TestRemoveSlotForceDeleteClaude:
    def test_force_delete_removes_claude_projects(self, tmp_path, monkeypatch):
        """force-delete must remove Claude session dirs for the destroyed slot."""
        family = tmp_path / "casehub"
        slot = family / "slots" / "1"
        slot.mkdir(parents=True)
        (slot / ".slot").write_text("test")
        repo = slot / "engine"
        repo.mkdir()
        (repo / ".git").mkdir()

        fake_home = tmp_path / "home"
        claude_projects = fake_home / ".claude" / "projects"
        claude_projects.mkdir(parents=True)
        slot_path_encoded = str(slot / "engine").replace("/", "-")
        proj_dir = claude_projects / slot_path_encoded
        proj_dir.mkdir()
        (proj_dir / "memory.md").write_text("session memory")

        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

        with patch("slot_manager.run_cmd") as mock_cmd:
            mock_cmd.return_value = (0, "", "")
            slot_manager.remove_slot(family, 1, force_delete=True)

        assert not proj_dir.exists(), "Claude session dir was not removed during force-delete"


class TestReadPromotionStamp:
    """Tests for _read_promotion_stamp helper."""

    def test_reads_stamp_counts(self, tmp_path):
        slot = tmp_path / "1"
        slot.mkdir()
        repo = slot / "engine"
        (repo / "design").mkdir(parents=True)
        (repo / "design" / ".artifacts-promoted").write_text(
            "timestamp=2026-08-01T00:00:00\n"
            "branch=issue-42\n"
            "workspace_promoted=2\n"
            "project_promoted=1\n"
            "issues_closed=3\n"
            "blog_published=1\n"
            "plans_archived=2\n"
        )
        promoted, published, dest = slot_manager._read_promotion_stamp(slot)
        assert "workspace:2" in promoted
        assert "project:1" in promoted
        assert "plans:2" in promoted
        assert "blog:1" in published

    def test_no_stamp(self, tmp_path):
        slot = tmp_path / "1"
        slot.mkdir()
        (slot / "engine").mkdir()
        promoted, published, dest = slot_manager._read_promotion_stamp(slot)
        assert promoted == []
        assert published == []

    def test_zero_counts_excluded(self, tmp_path):
        slot = tmp_path / "1"
        slot.mkdir()
        repo = slot / "engine"
        (repo / "design").mkdir(parents=True)
        (repo / "design" / ".artifacts-promoted").write_text(
            "workspace_promoted=0\n"
            "project_promoted=0\n"
            "blog_published=0\n"
            "plans_archived=0\n"
        )
        promoted, published, _ = slot_manager._read_promotion_stamp(slot)
        assert promoted == []
        assert published == []


class TestUnignoreSubdir:
    """Tests for _unignore_subdir — removes gitignore entries that hide workspace subdirs in slots."""

    def test_removes_slash_prefix_entry(self, tmp_path):
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("/claudony\n/connectors\n/engine\n")
        slot_manager._unignore_subdir(tmp_path, "claudony")
        content = gitignore.read_text()
        assert "/claudony" not in content
        assert "/connectors" in content
        assert "/engine" in content

    def test_removes_bare_name_entry(self, tmp_path):
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("claudony\nother\n")
        slot_manager._unignore_subdir(tmp_path, "claudony")
        content = gitignore.read_text()
        assert "claudony" not in content
        assert "other" in content

    def test_removes_trailing_slash_entry(self, tmp_path):
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("/claudony/\nother\n")
        slot_manager._unignore_subdir(tmp_path, "claudony")
        content = gitignore.read_text()
        assert "claudony" not in content

    def test_no_gitignore_file(self, tmp_path):
        slot_manager._unignore_subdir(tmp_path, "claudony")

    def test_subdir_not_in_gitignore(self, tmp_path):
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("/engine\n/connectors\n")
        slot_manager._unignore_subdir(tmp_path, "claudony")
        content = gitignore.read_text()
        assert "/engine" in content
        assert "/connectors" in content

    def test_preserves_other_entries(self, tmp_path):
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("*.pyc\n__pycache__\n/claudony\n.DS_Store\n")
        slot_manager._unignore_subdir(tmp_path, "claudony")
        content = gitignore.read_text()
        assert "*.pyc" in content
        assert "__pycache__" in content
        assert ".DS_Store" in content
        assert "claudony" not in content

    def test_artifact_committable_after_unignore(self, tmp_path):
        """Integration: after _unignore_subdir, files in the subdirectory
        are visible to git and can be committed. Regression test for #148."""
        ws = tmp_path / "workspace"
        ws.mkdir()
        subprocess.run(["git", "init", str(ws)], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(ws), "config", "user.name", "Test"], capture_output=True)
        subprocess.run(["git", "-C", str(ws), "config", "user.email", "t@t.com"], capture_output=True)

        (ws / ".gitignore").write_text("/claudony\n")
        subprocess.run(["git", "-C", str(ws), "add", ".gitignore"], capture_output=True)
        subprocess.run(["git", "-C", str(ws), "commit", "-m", "init"], capture_output=True)

        subdir = ws / "claudony" / "blog"
        subdir.mkdir(parents=True)
        (subdir / "entry.md").write_text("# Blog Entry\n")

        check_before = subprocess.run(
            ["git", "-C", str(ws), "status", "--short"],
            capture_output=True, text=True,
        )
        assert "claudony" not in check_before.stdout, "dir should be invisible before fix"

        slot_manager._unignore_subdir(ws, "claudony")

        check_after = subprocess.run(
            ["git", "-C", str(ws), "status", "--short"],
            capture_output=True, text=True,
        )
        assert "claudony" in check_after.stdout, "dir should be visible after fix"

        subprocess.run(["git", "-C", str(ws), "add", "claudony/blog/entry.md"], capture_output=True)
        result = subprocess.run(
            ["git", "-C", str(ws), "commit", "-m", "add blog entry"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"commit should succeed: {result.stderr}"


class TestMergeSlotEpicCheck:
    """Tests for merge_slot() epic status output and post-merge tick."""

    def test_merge_slot_prints_epic_status(self, tmp_path, capsys):
        """merge_slot prints EPIC_STATUS for epic slots."""
        family = tmp_path / "family"
        wt = family / "slots" / "72"
        wt.mkdir(parents=True)
        (wt / ".slot").write_text(
            "# Slot 72\n\n## Issue\norg/repo#50\nCovers: 83,84\nType: epic\n\n"
            "## Batch Plan\n\n### Batch 1 — Work\n"
            "- [x] #83 — Done\n- [ ] #84 — Active ← active\n\n"
            "## Session State\nCurrent batch: 1\nCurrent issue: #84 — Active\n\n"
            "## Repos\n- engine (primary)\n"
        )
        (wt / ".phase-a-complete").write_text("branch=issue-50\nrepos=engine\n")
        repo = init_repo(wt / "engine")
        subprocess.run(["git", "-C", str(repo), "checkout", "-b", "issue-50"], capture_output=True)
        (repo / "file.txt").write_text("content")
        subprocess.run(["git", "-C", str(repo), "add", "file.txt"], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "feat: work"], capture_output=True)
        with patch.object(slot_manager, "resolve_original_repo", return_value=repo):
            with patch.object(slot_manager, "is_worktree", return_value=False):
                result = slot_manager.merge_slot(family, 72)
        out = capsys.readouterr().out
        assert "EPIC_STATUS=" in out


class TestArchiveSlotCheckboxFix:
    """Tests for archive_slot() stale checkbox auto-fix."""

    def test_fixes_stale_checkboxes(self, tmp_path):
        """archive_slot auto-ticks unchecked boxes for completed issues."""
        slot_dir = tmp_path / "slots" / "72"
        slot_dir.mkdir(parents=True)
        (slot_dir / ".slot").write_text(
            "# Slot 72\n\n## Issue\norg/repo#50\nCovers: 83,84\nType: epic\n\n"
            "## Batch Plan\n\n### Batch 1 — Work\n"
            "- [ ] #83 — Task A\n- [x] #84 — Task B\n"
        )
        slot_manager._fix_stale_checkboxes(slot_dir / ".slot", [83])
        content = (slot_dir / ".slot").read_text()
        assert "- [x] #83" in content
        assert "- [x] #84" in content

    def test_no_fix_needed(self, tmp_path):
        slot_dir = tmp_path / "slots" / "72"
        slot_dir.mkdir(parents=True)
        (slot_dir / ".slot").write_text(
            "# Slot 72\n\n## Issue\norg/repo#50\nType: epic\n\n"
            "## Batch Plan\n\n### Batch 1 — Work\n"
            "- [x] #83 — Task A\n"
        )
        fixed = slot_manager._fix_stale_checkboxes(slot_dir / ".slot", [83])
        assert fixed == 0

    def test_only_fixes_listed_issues(self, tmp_path):
        slot_dir = tmp_path / "slots" / "72"
        slot_dir.mkdir(parents=True)
        (slot_dir / ".slot").write_text(
            "# Slot 72\n\n## Issue\norg/repo#50\nType: epic\n\n"
            "## Batch Plan\n\n### Batch 1 — Work\n"
            "- [ ] #83 — Task A\n- [ ] #84 — Task B\n"
        )
        slot_manager._fix_stale_checkboxes(slot_dir / ".slot", [83])
        content = (slot_dir / ".slot").read_text()
        assert "- [x] #83" in content
        assert "- [ ] #84" in content


class TestSlotDirResolution:
    def test_prefers_slots_over_worktrees(self, tmp_path):
        (tmp_path / "slots").mkdir()
        (tmp_path / "worktrees").mkdir()
        result = slot_manager._resolve_slots_dir(tmp_path)
        assert result == tmp_path / "slots"

    def test_falls_back_to_worktrees(self, tmp_path):
        (tmp_path / "worktrees").mkdir()
        result = slot_manager._resolve_slots_dir(tmp_path)
        assert result == tmp_path / "worktrees"

    def test_returns_slots_when_neither_exists(self, tmp_path):
        result = slot_manager._resolve_slots_dir(tmp_path)
        assert result == tmp_path / "slots"

    def test_resolve_slot_number_in_slots(self, tmp_path):
        (tmp_path / "slots" / "1").mkdir(parents=True)
        result = slot_manager._resolve_slot_dir_for_number(tmp_path, 1)
        assert result == tmp_path / "slots" / "1"

    def test_resolve_slot_number_falls_back_to_worktrees(self, tmp_path):
        (tmp_path / "worktrees" / "1").mkdir(parents=True)
        result = slot_manager._resolve_slot_dir_for_number(tmp_path, 1)
        assert result == tmp_path / "worktrees" / "1"

    def test_resolve_slot_number_prefers_slots(self, tmp_path):
        (tmp_path / "slots" / "1").mkdir(parents=True)
        (tmp_path / "worktrees" / "1").mkdir(parents=True)
        result = slot_manager._resolve_slot_dir_for_number(tmp_path, 1)
        assert result == tmp_path / "slots" / "1"


class TestIsSlotPath:
    def test_detects_slots_path(self):
        assert slot_manager.is_slot_path("/home/user/family/slots/1/repo") is True

    def test_detects_legacy_worktrees_path(self):
        assert slot_manager.is_slot_path("/home/user/family/worktrees/1/repo") is True

    def test_rejects_claude_worktrees(self):
        assert slot_manager.is_slot_path("/home/user/repo/.claude/worktrees/issue-17") is False

    def test_rejects_dot_worktrees(self):
        assert slot_manager.is_slot_path("/home/user/repo/.worktrees/feat") is False

    def test_rejects_plain_path(self):
        assert slot_manager.is_slot_path("/home/user/project/src") is False


class TestAddRepo:
    def test_adds_repo_to_slot(self, tmp_path):
        family = tmp_path / "family"
        repo1 = init_repo(family / "engine")
        repo2 = init_repo(family / "trellis")
        result = slot_manager.create_slot(
            family_root=family, repos=["engine"], branch="issue-42-test",
            issue="42", issue_repo="org/repo", covers="42", context="test",
        )
        slot_dir = family / "slots" / str(result["slot_number"])
        slot_manager.add_repo(family, result["slot_number"], "trellis", "issue-42-test")
        assert (slot_dir / "trellis").exists()
        assert (slot_dir / "trellis" / ".git").exists()
        current = subprocess.run(
            ["git", "-C", str(slot_dir / "trellis"), "branch", "--show-current"],
            capture_output=True, text=True,
        ).stdout.strip()
        assert current == "issue-42-test"

    def test_updates_slot_file(self, tmp_path):
        family = tmp_path / "family"
        init_repo(family / "engine")
        init_repo(family / "trellis")
        result = slot_manager.create_slot(
            family_root=family, repos=["engine"], branch="issue-42-test",
            issue="42", issue_repo="org/repo", covers="42", context="test",
        )
        slot_dir = family / "slots" / str(result["slot_number"])
        slot_manager.add_repo(family, result["slot_number"], "trellis", "issue-42-test")
        content = (slot_dir / ".slot").read_text()
        assert "trellis" in content

    def test_rejects_duplicate_repo(self, tmp_path):
        family = tmp_path / "family"
        init_repo(family / "engine")
        result = slot_manager.create_slot(
            family_root=family, repos=["engine"], branch="issue-42-test",
            issue="42", issue_repo="org/repo", covers="42", context="test",
        )
        with pytest.raises(SystemExit):
            slot_manager.add_repo(family, result["slot_number"], "engine", "issue-42-test")


class TestRemoveRepo:
    def test_removes_repo_from_slot(self, tmp_path):
        family = tmp_path / "family"
        init_repo(family / "engine")
        init_repo(family / "trellis")
        result = slot_manager.create_slot(
            family_root=family, repos=["engine", "trellis"], branch="issue-42-test",
            issue="42", issue_repo="org/repo", covers="42", context="test",
        )
        slot_dir = family / "slots" / str(result["slot_number"])
        slot_manager.remove_repo(family, result["slot_number"], "trellis")
        assert not (slot_dir / "trellis").exists()
        content = (slot_dir / ".slot").read_text()
        assert "trellis" not in content

    def test_refuses_to_remove_primary(self, tmp_path):
        family = tmp_path / "family"
        init_repo(family / "engine")
        result = slot_manager.create_slot(
            family_root=family, repos=["engine"], branch="issue-42-test",
            issue="42", issue_repo="org/repo", covers="42", context="test",
        )
        with pytest.raises(ValueError, match="primary"):
            slot_manager.remove_repo(family, result["slot_number"], "engine")


class TestCreateSlotUsesNewDir:
    def test_creates_under_slots_not_worktrees(self, tmp_path):
        repo = init_repo(tmp_path / "myrepo")
        result = slot_manager.create_slot(
            family_root=tmp_path, repos=["myrepo"], branch="test-branch",
            issue="1", issue_repo="org/repo", covers="1", context="test",
        )
        assert (tmp_path / "slots").exists()
        assert not (tmp_path / "worktrees").exists()
        assert (tmp_path / "slots" / "1").exists()


class TestListSlotsDualPath:
    def test_finds_slots_in_legacy_worktrees(self, tmp_path):
        wt = tmp_path / "worktrees" / "1"
        wt.mkdir(parents=True)
        init_repo(wt / "myrepo")
        (wt / ".slot").write_text("# Slot 1 — test-branch\n")
        slots = slot_manager.list_slots(tmp_path)
        assert len(slots) == 1
        assert slots[0]["number"] == 1

    def test_finds_slots_in_new_dir(self, tmp_path):
        sd = tmp_path / "slots" / "1"
        sd.mkdir(parents=True)
        init_repo(sd / "myrepo")
        (sd / ".slot").write_text("# Slot 1 — test-branch\n")
        slots = slot_manager.list_slots(tmp_path)
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
        slots = slot_manager.list_slots(tmp_path)
        assert len(slots) == 2
        nums = {s["number"] for s in slots}
        assert nums == {1, 2}


class TestSymlinkGitignoredAssets:
    """Tests for _symlink_gitignored_assets — carries gitignored asset dirs into slot clones."""

    def test_symlinks_gitignored_directory(self, tmp_path):
        """A gitignored directory present in source should be symlinked into clone."""
        source = init_repo(tmp_path / "source")
        (source / ".gitignore").write_text(".casehub-packages\n")
        subprocess.run(["git", "-C", str(source), "add", ".gitignore"], capture_output=True)
        subprocess.run(["git", "-C", str(source), "commit", "-m", "add gitignore"], capture_output=True)
        pkg_dir = source / ".casehub-packages"
        pkg_dir.mkdir()
        (pkg_dir / "graph-core").mkdir()
        (pkg_dir / "graph-core" / "index.js").write_text("module.exports = {}")

        clone = tmp_path / "clone"
        subprocess.run(["git", "clone", str(source), str(clone)], capture_output=True, check=True)

        linked = slot_manager._symlink_gitignored_assets(source, clone)
        assert ".casehub-packages" in linked
        assert (clone / ".casehub-packages").is_symlink()
        assert (clone / ".casehub-packages" / "graph-core" / "index.js").exists()

    def test_skips_regenerable_directories(self, tmp_path):
        """node_modules, build, dist, target etc. should NOT be symlinked."""
        source = init_repo(tmp_path / "source")
        (source / ".gitignore").write_text("node_modules\nbuild\ndist\ntarget\n.idea\n")
        subprocess.run(["git", "-C", str(source), "add", ".gitignore"], capture_output=True)
        subprocess.run(["git", "-C", str(source), "commit", "-m", "add gitignore"], capture_output=True)
        for name in ["node_modules", "build", "dist", "target", ".idea"]:
            d = source / name
            d.mkdir()
            (d / "file.txt").write_text("content")

        clone = tmp_path / "clone"
        subprocess.run(["git", "clone", str(source), str(clone)], capture_output=True, check=True)

        linked = slot_manager._symlink_gitignored_assets(source, clone)
        assert linked == []
        for name in ["node_modules", "build", "dist", "target", ".idea"]:
            assert not (clone / name).is_symlink()

    def test_skips_directories_already_in_clone(self, tmp_path):
        """If the directory already exists in the clone, don't symlink over it."""
        source = init_repo(tmp_path / "source")
        (source / ".gitignore").write_text(".cache\n")
        subprocess.run(["git", "-C", str(source), "add", ".gitignore"], capture_output=True)
        subprocess.run(["git", "-C", str(source), "commit", "-m", "add gitignore"], capture_output=True)
        (source / ".cache").mkdir()
        (source / ".cache" / "data").write_text("cached")

        clone = tmp_path / "clone"
        subprocess.run(["git", "clone", str(source), str(clone)], capture_output=True, check=True)
        (clone / ".cache").mkdir()
        (clone / ".cache" / "local").write_text("clone-local")

        linked = slot_manager._symlink_gitignored_assets(source, clone)
        assert ".cache" not in linked
        assert not (clone / ".cache").is_symlink()
        assert (clone / ".cache" / "local").read_text() == "clone-local"

    def test_skips_non_gitignored_directories(self, tmp_path):
        """Directories that are tracked (not gitignored) should not be symlinked."""
        source = init_repo(tmp_path / "source")
        src_dir = source / "src"
        src_dir.mkdir()
        (src_dir / "main.py").write_text("print('hi')")
        subprocess.run(["git", "-C", str(source), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(source), "commit", "-m", "add src"], capture_output=True)

        clone = tmp_path / "clone"
        subprocess.run(["git", "clone", str(source), str(clone)], capture_output=True, check=True)

        linked = slot_manager._symlink_gitignored_assets(source, clone)
        assert linked == []

    def test_skips_files_not_directories(self, tmp_path):
        """Gitignored files (not directories) should not be symlinked."""
        source = init_repo(tmp_path / "source")
        (source / ".gitignore").write_text(".env\n")
        subprocess.run(["git", "-C", str(source), "add", ".gitignore"], capture_output=True)
        subprocess.run(["git", "-C", str(source), "commit", "-m", "add gitignore"], capture_output=True)
        (source / ".env").write_text("SECRET=abc")

        clone = tmp_path / "clone"
        subprocess.run(["git", "clone", str(source), str(clone)], capture_output=True, check=True)

        linked = slot_manager._symlink_gitignored_assets(source, clone)
        assert linked == []
        assert not (clone / ".env").exists()

    def test_create_slot_symlinks_gitignored_assets(self, tmp_path):
        """Integration: create_slot should automatically symlink gitignored asset dirs."""
        family = tmp_path / "family"
        repo = init_repo(family / "blocks-ui")
        (repo / ".gitignore").write_text(".casehub-packages\n")
        subprocess.run(["git", "-C", str(repo), "add", ".gitignore"], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "add gitignore"], capture_output=True)
        pkg_dir = repo / ".casehub-packages"
        pkg_dir.mkdir()
        (pkg_dir / "graph-core").mkdir()
        (pkg_dir / "graph-core" / "package.json").write_text('{"name": "graph-core"}')

        result = slot_manager.create_slot(
            family_root=family, repos=["blocks-ui"], branch="issue-107-test",
            issue="107", issue_repo="org/repo", covers="107", context="test",
        )
        clone = family / "slots" / str(result["slot_number"]) / "blocks-ui"
        assert (clone / ".casehub-packages").is_symlink(), \
            "create_slot did not symlink gitignored .casehub-packages into clone"
        assert (clone / ".casehub-packages" / "graph-core" / "package.json").exists()

    def test_add_repo_symlinks_gitignored_assets(self, tmp_path):
        """Integration: add_repo should also symlink gitignored asset dirs."""
        family = tmp_path / "family"
        init_repo(family / "engine")
        repo2 = init_repo(family / "blocks-ui")
        (repo2 / ".gitignore").write_text(".casehub-packages\n")
        subprocess.run(["git", "-C", str(repo2), "add", ".gitignore"], capture_output=True)
        subprocess.run(["git", "-C", str(repo2), "commit", "-m", "add gitignore"], capture_output=True)
        pkg_dir = repo2 / ".casehub-packages"
        pkg_dir.mkdir()
        (pkg_dir / "pages-component").mkdir()
        (pkg_dir / "pages-component" / "index.js").write_text("export default {}")

        result = slot_manager.create_slot(
            family_root=family, repos=["engine"], branch="issue-107-test",
            issue="107", issue_repo="org/repo", covers="107", context="test",
        )
        slot_manager.add_repo(family, result["slot_number"], "blocks-ui", "issue-107-test")
        clone = family / "slots" / str(result["slot_number"]) / "blocks-ui"
        assert (clone / ".casehub-packages").is_symlink(), \
            "add_repo did not symlink gitignored .casehub-packages into clone"
        assert (clone / ".casehub-packages" / "pages-component" / "index.js").exists()