"""Tests for work-slot/slot_manager.py"""

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
    def test_empty_worktrees_dir(self, tmp_path):
        wt = tmp_path / "worktrees"
        wt.mkdir()
        assert slot_manager.allocate_slot_number(wt) == 1

    def test_existing_slots(self, tmp_path):
        wt = tmp_path / "worktrees"
        wt.mkdir()
        (wt / "1").mkdir()
        (wt / "2").mkdir()
        assert slot_manager.allocate_slot_number(wt) == 3

    def test_gap_in_numbering(self, tmp_path):
        wt = tmp_path / "worktrees"
        wt.mkdir()
        (wt / "1").mkdir()
        (wt / "3").mkdir()
        assert slot_manager.allocate_slot_number(wt) == 4

    def test_no_worktrees_dir(self, tmp_path):
        wt = tmp_path / "worktrees"
        assert slot_manager.allocate_slot_number(wt) == 1


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


class TestSetupMavenConfig:
    def test_creates_new_config(self, tmp_path):
        repo_wt = tmp_path / "engine"
        repo_wt.mkdir()
        m2 = tmp_path / ".m2"
        slot_manager.setup_maven_config(repo_wt, m2)
        config = (repo_wt / ".mvn" / "maven.config").read_text()
        assert f"-Dmaven.repo.local={m2}" in config

    def test_appends_to_existing_config(self, tmp_path):
        repo_wt = tmp_path / "engine"
        mvn_dir = repo_wt / ".mvn"
        mvn_dir.mkdir(parents=True)
        (mvn_dir / "maven.config").write_text(
            "-Dquarkus.bootstrap.application-model.serialization.format=jos\n"
        )
        m2 = tmp_path / ".m2"
        slot_manager.setup_maven_config(repo_wt, m2)
        config = (mvn_dir / "maven.config").read_text()
        assert "serialization.format=jos" in config
        assert f"-Dmaven.repo.local={m2}" in config

    def test_idempotent(self, tmp_path):
        repo_wt = tmp_path / "engine"
        repo_wt.mkdir()
        m2 = tmp_path / ".m2"
        slot_manager.setup_maven_config(repo_wt, m2)
        slot_manager.setup_maven_config(repo_wt, m2)
        config = (repo_wt / ".mvn" / "maven.config").read_text()
        assert config.count("-Dmaven.repo.local=") == 1


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
        content = (tmp_path / "SLOT.md").read_text()
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
        content = (tmp_path / "SLOT.md").read_text()
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
        slot_dir = family / "worktrees" / "1"
        assert slot_dir.is_dir()
        assert (slot_dir / ".m2").is_dir()
        assert (slot_dir / "SLOT.md").exists()
        assert "issue-42-spi" in (slot_dir / "SLOT.md").read_text()

    @patch("slot_manager.run_cmd")
    def test_slot_numbering_increments(self, mock_cmd, tmp_path):
        family = tmp_path / "casehub"
        (family / "worktrees" / "1").mkdir(parents=True)
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
    def test_worktree_add_failure_exits(self, mock_cmd, tmp_path, capsys):
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
            (1, "", "fatal: branch already exists"),  # worktree add fails
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
        assert "ERROR=worktree_add_failed" in captured.out


class TestListSlots:
    def test_empty_worktrees(self, tmp_path):
        family = tmp_path / "casehub"
        (family / "worktrees").mkdir(parents=True)
        slots = slot_manager.list_slots(family)
        assert slots == []

    def test_active_slot(self, tmp_path):
        family = tmp_path / "casehub"
        slot = family / "worktrees" / "1"
        slot.mkdir(parents=True)
        (slot / "SLOT.md").write_text("# Slot 1 — issue-42-spi\n")
        (slot / "engine").mkdir()
        (slot / "engine" / ".git").write_text("gitdir: /fake/.git/worktrees/engine")

        slots = slot_manager.list_slots(family)
        assert len(slots) == 1
        assert slots[0]["number"] == 1
        assert slots[0]["state"] == "active"
        assert "engine" in slots[0]["repos"]

    def test_ready_to_land_slot(self, tmp_path):
        family = tmp_path / "casehub"
        slot = family / "worktrees" / "1"
        slot.mkdir(parents=True)
        (slot / "SLOT.md").write_text("# Slot 1 — issue-42-spi\n")
        (slot / ".phase-a-complete").write_text("branch=issue-42\n")
        (slot / "engine").mkdir()
        (slot / "engine" / ".git").write_text("gitdir: /fake")

        slots = slot_manager.list_slots(family)
        assert slots[0]["state"] == "ready to land"

    def test_no_worktrees_dir(self, tmp_path):
        family = tmp_path / "casehub"
        family.mkdir()
        slots = slot_manager.list_slots(family)
        assert slots == []


class TestRemoveSlot:
    def test_removes_slot_dir(self, tmp_path):
        family = tmp_path / "casehub"
        slot = family / "worktrees" / "1"
        slot.mkdir(parents=True)
        (slot / "SLOT.md").write_text("test")
        (slot / ".m2").mkdir()

        with patch("slot_manager.run_cmd") as mock_cmd:
            mock_cmd.return_value = (0, "", "")
            slot_manager.remove_slot(family, 1)

        assert not slot.exists()

    def test_nonexistent_slot_errors(self, tmp_path, capsys):
        family = tmp_path / "casehub"
        (family / "worktrees").mkdir(parents=True)

        with pytest.raises(SystemExit):
            slot_manager.remove_slot(family, 99)
        captured = capsys.readouterr()
        assert "ERROR=slot_not_found" in captured.out


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
