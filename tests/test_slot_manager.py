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

    def test_considers_attic(self, tmp_path):
        wt = tmp_path / "worktrees"
        wt.mkdir()
        (wt / "1").mkdir()
        (wt / "2").mkdir()
        attic = wt / "attic"
        attic.mkdir()
        (attic / "3").mkdir()
        (attic / "5").mkdir()
        assert slot_manager.allocate_slot_number(wt) == 6

    def test_only_attic(self, tmp_path):
        wt = tmp_path / "worktrees"
        wt.mkdir()
        attic = wt / "attic"
        attic.mkdir()
        (attic / "4").mkdir()
        assert slot_manager.allocate_slot_number(wt) == 5


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
    def test_archives_to_attic_by_default(self, tmp_path):
        family = tmp_path / "casehub"
        slot = family / "worktrees" / "1"
        slot.mkdir(parents=True)
        (slot / "SLOT.md").write_text("test")
        (slot / ".m2").mkdir()

        with patch("slot_manager.run_cmd") as mock_cmd:
            mock_cmd.return_value = (0, "", "")
            slot_manager.remove_slot(family, 1)

        assert not slot.exists()
        attic = family / "worktrees" / "attic" / "1"
        assert attic.exists()
        assert (attic / "SLOT.md").exists()

    def test_force_delete_permanently_removes(self, tmp_path):
        family = tmp_path / "casehub"
        slot = family / "worktrees" / "1"
        slot.mkdir(parents=True)
        (slot / "SLOT.md").write_text("test")

        with patch("slot_manager.run_cmd") as mock_cmd:
            mock_cmd.return_value = (0, "", "")
            slot_manager.remove_slot(family, 1, force_delete=True)

        assert not slot.exists()
        assert not (family / "worktrees" / "attic" / "1").exists()

    def test_nonexistent_slot_errors(self, tmp_path, capsys):
        family = tmp_path / "casehub"
        (family / "worktrees").mkdir(parents=True)

        with pytest.raises(SystemExit):
            slot_manager.remove_slot(family, 99)
        captured = capsys.readouterr()
        assert "ERROR=slot_not_found" in captured.out


class TestParseSlotMd:
    def test_parses_full_slot_md(self, tmp_path):
        (tmp_path / "SLOT.md").write_text(
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

    def test_missing_slot_md(self, tmp_path):
        assert slot_manager.parse_slot_md(tmp_path) == {}


class TestScanReady:
    def test_finds_phase_a_complete_slots(self, tmp_path):
        worktrees = tmp_path / "worktrees"
        worktrees.mkdir()
        slot1 = worktrees / "1"
        slot1.mkdir()
        (slot1 / ".phase-a-complete").write_text(
            "branch=issue-42-spi\nrepos=engine\ntimestamp=2026-07-18T14:32:00\n"
        )
        (slot1 / "SLOT.md").write_text(
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
        worktrees = tmp_path / "worktrees"
        worktrees.mkdir()
        (worktrees / "1").mkdir()
        assert slot_manager.scan_ready(tmp_path) == []

    def test_no_worktrees_dir(self, tmp_path):
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
    worktrees = family / "worktrees"
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
    (slot / "SLOT.md").write_text(
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
        (family / "worktrees").mkdir(parents=True)
        assert slot_manager.merge_slot(family, 99) == 1

    def test_not_ready(self, tmp_path):
        family = tmp_path / "family"
        slot = family / "worktrees" / "1"
        slot.mkdir(parents=True)
        assert slot_manager.merge_slot(family, 1) == 1

    def test_already_landed(self, tmp_path):
        family, _, slot, _ = _create_merge_test_repos(tmp_path, ["engine"])
        (slot / ".landed").write_text("already\n")
        assert slot_manager.merge_slot(family, 1) == 1


class TestArchiveSlot:
    def test_moves_to_attic(self, tmp_path):
        family, originals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        (slot / ".phase-a-complete").write_text("branch=issue-42-test\n")
        (slot / ".landed").write_text("landed\n")

        slot_manager.archive_slot(family, 1)

        assert not (family / "worktrees" / "1").exists()
        attic_slot = family / "worktrees" / "attic" / "1"
        assert attic_slot.exists()
        assert (attic_slot / "SLOT.md").exists()
        assert (attic_slot / ".phase-a-complete").exists()
        assert (attic_slot / ".landed").exists()

    def test_relocates_claude_projects(self, tmp_path, monkeypatch):
        family, originals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])

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
        attic_path = family / "worktrees" / "attic" / "1"
        dest_encoded = str(attic_path / "engine").replace("/", "-")
        moved_dir = claude_projects / dest_encoded
        assert moved_dir.exists()
        assert (moved_dir / "memory.md").read_text() == "session memory"

    def test_not_found_exits(self, tmp_path, capsys):
        family = tmp_path / "family"
        (family / "worktrees").mkdir(parents=True)
        with pytest.raises(SystemExit):
            slot_manager.archive_slot(family, 99)
        captured = capsys.readouterr()
        assert "ERROR=slot_not_found" in captured.out


class TestListSlotsExtended:
    def test_shows_landed_state(self, tmp_path):
        worktrees = tmp_path / "worktrees"
        worktrees.mkdir()
        slot = worktrees / "1"
        slot.mkdir()
        (slot / ".phase-a-complete").write_text("branch=issue-42\n")
        (slot / ".landed").write_text("landed\n")
        (slot / "SLOT.md").write_text("# Slot 1 — issue-42\n")

        result = slot_manager.list_slots(tmp_path, include_archived=False)
        assert len(result) == 1
        assert result[0]["state"] == "landed"

    def test_includes_archived(self, tmp_path):
        worktrees = tmp_path / "worktrees"
        worktrees.mkdir()
        attic = worktrees / "attic"
        attic.mkdir()
        archived = attic / "3"
        archived.mkdir()
        (archived / "SLOT.md").write_text(
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

    def test_backward_compat_no_arg(self, tmp_path):
        worktrees = tmp_path / "worktrees"
        worktrees.mkdir()
        slot = worktrees / "1"
        slot.mkdir()
        (slot / "SLOT.md").write_text("# Slot 1 — issue-42\n")
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
