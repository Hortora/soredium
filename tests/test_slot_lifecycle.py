"""Tests for work-slot/slot_lifecycle.py"""

import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, call, MagicMock

import pytest

skill_dir = Path(__file__).parent.parent / "work-slot"
sys.path.insert(0, str(skill_dir))

scripts_dir = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(scripts_dir))

import slot_lifecycle
import slot_manager
import slot_core
import slot_workspace
import slot_metadata
import slot_git
import slot_claude
import slot_isx
from slot_test_helpers import init_repo, init_repo_with_workspace, init_repo_with_remote


class TestAllocateSlotNumber:
    """DB-authoritative numbering replaced disk-scan allocation.
    See TestAllocateSlotNumberDB for the primary test class."""

    def _setup_db(self, tmp_path, monkeypatch):
        scripts_dir = Path(__file__).parent.parent / "scripts"
        sys.path.insert(0, str(scripts_dir))
        import worklog as _wl_mod
        db_path = tmp_path / "alloc_test.db"
        monkeypatch.setattr(slot_lifecycle, "_wl", _wl_mod)
        monkeypatch.setattr(_wl_mod, "DEFAULT_DB", str(db_path))
        return _wl_mod

    def test_empty_db_returns_1(self, tmp_path, monkeypatch):
        self._setup_db(tmp_path, monkeypatch)
        assert slot_lifecycle.allocate_slot_number(tmp_path) == 1

    def test_increments_from_db_max(self, tmp_path, monkeypatch):
        _wl_mod = self._setup_db(tmp_path, monkeypatch)
        conn = _wl_mod.connect()
        conn.execute(
            "INSERT INTO slots (slot_number, family_root, state, created_at) "
            "VALUES (?, ?, 'active', '2026-01-01')",
            (5, _wl_mod._norm(str(tmp_path))),
        )
        conn.commit()
        conn.close()
        assert slot_lifecycle.allocate_slot_number(tmp_path) == 6

    def test_skips_gaps(self, tmp_path, monkeypatch):
        _wl_mod = self._setup_db(tmp_path, monkeypatch)
        conn = _wl_mod.connect()
        for n in (1, 3):
            conn.execute(
                "INSERT INTO slots (slot_number, family_root, state, created_at) "
                "VALUES (?, ?, 'active', '2026-01-01')",
                (n, _wl_mod._norm(str(tmp_path))),
            )
        conn.commit()
        conn.close()
        assert slot_lifecycle.allocate_slot_number(tmp_path) == 4

    def test_considers_archived_in_db(self, tmp_path, monkeypatch):
        _wl_mod = self._setup_db(tmp_path, monkeypatch)
        conn = _wl_mod.connect()
        conn.execute(
            "INSERT INTO slots (slot_number, family_root, state, created_at) "
            "VALUES (?, ?, 'archived', '2026-01-01')",
            (50, _wl_mod._norm(str(tmp_path))),
        )
        conn.commit()
        conn.close()
        assert slot_lifecycle.allocate_slot_number(tmp_path) == 51



class TestWorkspaceNameCollision:
    @patch("slot_lifecycle.run_cmd")
    def test_collision_detected_when_workspace_name_matches_repo(self, mock_cmd, tmp_path):
        """When resolve_workspace_source returns a name that collides with
        an existing directory (e.g., a repo clone), create_slot errors."""
        family = tmp_path / "casehub"
        family.mkdir()
        work_repo = init_repo(family / "work")
        ws_repo = init_repo(tmp_path / "public" / "casehub" / "work")
        (work_repo / "wksp").symlink_to(ws_repo)

        mock_cmd.return_value = (0, "", "")

        with patch("slot_lifecycle.resolve_workspace_source") as mock_resolve:
            mock_resolve.return_value = (ws_repo, "work")
            with pytest.raises(slot_core.SlotCreationError):
                slot_lifecycle.create_slot(
                    family_root=family,
                    repos=["work"],
                    branch="issue-99-test",
                    issue="99",
                    issue_repo="casehubio/parent",
                    covers="99",
                    context="Test collision",
                )



class TestCrossOrgWorkspaceWiring:
    @patch("slot_lifecycle.run_cmd")
    def test_cross_org_repos_get_separate_workspace_clones(self, mock_cmd, tmp_path):
        """When a slot mixes repos from different families, each gets its
        own workspace clone with a unique name from resolve_workspace_source."""
        family = tmp_path / "hortora"
        family.mkdir()

        ws_trellis = init_repo(tmp_path / "public" / "hortora" / "trellis")
        ws_pages = init_repo(tmp_path / "public" / "casehub" / "pages")

        repo_a = init_repo(family / "trellis")
        (repo_a / "wksp").symlink_to(ws_trellis)

        repo_b = init_repo(family / "pages")
        (repo_b / "wksp").symlink_to(ws_pages)

        mock_cmd.return_value = (0, "", "")

        with patch("slot_lifecycle.resolve_workspace_source") as mock_resolve:
            mock_resolve.side_effect = [
                (ws_trellis, "wsp-hortora-trellis"),
                (ws_pages, "wsp-casehub-pages"),
            ]
            result = slot_lifecycle.create_slot(
                family_root=family,
                repos=["trellis", "pages"],
                branch="issue-200-test",
                issue="200",
                issue_repo="Hortora/soredium",
                covers="200",
                context="Cross-org test",
            )

        slot_dir = family / "slots" / str(result["slot_number"])

        clone_dests = []
        for c in mock_cmd.call_args_list:
            args = c.args[0] if c.args else c[0]
            if isinstance(args, list) and len(args) >= 2 and args[0] == "git" and "clone" in args:
                clone_dests.append(args[-1])

        ws_dests = [d for d in clone_dests if "wsp-" in Path(d).name]
        assert len(ws_dests) == 2, (
            f"Expected 2 workspace clones, got {len(ws_dests)}: {ws_dests}"
        )
        assert len(set(ws_dests)) == 2, f"Workspace clone directories collided: {ws_dests}"



class TestCreateSlot:
    @patch("slot_lifecycle.run_cmd")
    def test_creates_single_repo_slot(self, mock_cmd, tmp_path):
        family = tmp_path / "casehub"
        family.mkdir()
        engine = init_repo(family / "engine")
        ws_engine = init_repo(tmp_path / "public" / "casehub" / "engine")
        (engine / "wksp").symlink_to(ws_engine)

        mock_cmd.return_value = (0, "", "")

        with patch("slot_lifecycle.resolve_workspace_source") as mock_resolve:
            mock_resolve.return_value = (ws_engine, "wsp-casehub-engine")
            result = slot_lifecycle.create_slot(
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

    @patch("slot_lifecycle.run_cmd")
    def test_slot_numbering_increments(self, mock_cmd, tmp_path):
        family = tmp_path / "casehub"
        family.mkdir(parents=True)
        engine = init_repo(family / "engine")
        ws_engine = init_repo(tmp_path / "public" / "casehub" / "engine")
        (engine / "wksp").symlink_to(ws_engine)

        mock_cmd.return_value = (0, "", "")

        with patch("slot_lifecycle.resolve_workspace_source") as mock_resolve:
            mock_resolve.return_value = (ws_engine, "wsp-casehub-engine")
            result1 = slot_lifecycle.create_slot(
                family_root=family,
                repos=["engine"],
                branch="issue-42-spi",
                issue="42",
                issue_repo="casehubio/engine",
                covers="42",
                context="First slot",
            )
            assert result1["slot_number"] == 1

            result2 = slot_lifecycle.create_slot(
                family_root=family,
                repos=["engine"],
                branch="issue-55-ledger",
                issue="55",
                issue_repo="casehubio/engine",
                covers="55",
                context="Fix ledger",
            )
            assert result2["slot_number"] == 2

    @patch("slot_git.run_cmd")
    @patch("slot_lifecycle.run_cmd")
    def test_clone_failure_exits(self, mock_cmd, mock_git_cmd, tmp_path, capsys):
        family = tmp_path / "casehub"
        engine = init_repo(family / "engine")
        ws_engine = init_repo(tmp_path / "public" / "casehub" / "engine")
        (engine / "wksp").symlink_to(ws_engine)

        mock_cmd.side_effect = [
            (1, "", "fatal: clone failed"),  # clone fails
        ]
        mock_git_cmd.return_value = (0, "", "")

        with patch("slot_lifecycle.resolve_workspace_source") as mock_resolve:
            mock_resolve.return_value = (ws_engine, "wsp-casehub-engine")
            with pytest.raises(slot_core.SlotCreationError, match="clone_failed"):
                slot_lifecycle.create_slot(
                    family_root=family,
                    repos=["engine"],
                    branch="issue-42-spi",
                    issue="42",
                    issue_repo="casehubio/engine",
                    covers="42",
                    context="test",
                )



class TestCreateSlotPrimaryWorkspace:
    @patch("slot_lifecycle.run_cmd")
    def test_errors_when_primary_repo_has_no_workspace(self, mock_cmd, tmp_path):
        """When the primary repo has no workspace (even after discovery), create_slot should error."""
        family = tmp_path / "casehub"
        family.mkdir()
        init_repo(family / "engine")

        mock_cmd.return_value = (0, "", "")

        with patch("slot_lifecycle.discover_workspace", return_value=None):
            with pytest.raises(slot_core.SlotCreationError, match="primary_no_workspace"):
                slot_lifecycle.create_slot(
                    family_root=family,
                    repos=["engine"],
                    branch="issue-42-spi",
                    issue="42",
                    issue_repo="casehubio/engine",
                    covers="42",
                    context="Add SPI layer",
                )

    @patch("slot_lifecycle.run_cmd")
    def test_discovers_workspace_when_wksp_symlink_missing(self, mock_cmd, tmp_path, capsys):
        """When wksp symlink is missing but discover_workspace finds it, clone proceeds."""
        family = tmp_path / "casehub"
        family.mkdir()
        engine = init_repo(family / "engine")
        ws_engine = init_repo(tmp_path / "public" / "casehub" / "engine")

        mock_cmd.return_value = (0, "", "")

        with patch("slot_lifecycle.resolve_workspace_source", return_value=None), \
             patch("slot_lifecycle.discover_workspace", return_value=(ws_engine, "wsp-casehub-engine")):
            slot_lifecycle.create_slot(
                family_root=family,
                repos=["engine"],
                branch="issue-42-spi",
                issue="42",
                issue_repo="casehubio/engine",
                covers="42",
                context="Add SPI layer",
            )

        captured = capsys.readouterr()
        assert "DISCOVERED_WORKSPACE=wsp-casehub-engine" in captured.out

    @patch("slot_lifecycle.run_cmd")
    def test_no_error_when_primary_has_workspace(self, mock_cmd, tmp_path, capsys):
        """No error when primary repo has a wksp symlink."""
        family = tmp_path / "casehub"
        family.mkdir()
        engine = init_repo(family / "engine")
        ws_engine = init_repo(tmp_path / "public" / "casehub" / "engine")
        (engine / "wksp").symlink_to(ws_engine)

        mock_cmd.return_value = (0, "", "")

        with patch("slot_lifecycle.resolve_workspace_source") as mock_resolve:
            mock_resolve.return_value = (ws_engine, "wsp-casehub-engine")
            slot_lifecycle.create_slot(
                family_root=family,
                repos=["engine"],
                branch="issue-42-spi",
                issue="42",
                issue_repo="casehubio/engine",
                covers="42",
                context="Add SPI layer",
            )

    @patch("slot_lifecycle.run_cmd")
    def test_secondary_without_workspace_is_not_an_error(self, mock_cmd, tmp_path, capsys):
        """When only a secondary repo lacks workspace, no error is raised."""
        family = tmp_path / "casehub"
        family.mkdir()
        engine = init_repo(family / "engine")
        ws_engine = init_repo(tmp_path / "public" / "casehub" / "engine")
        (engine / "wksp").symlink_to(ws_engine)
        init_repo(family / "iot")

        mock_cmd.return_value = (0, "", "")

        with patch("slot_lifecycle.resolve_workspace_source") as mock_resolve:
            mock_resolve.side_effect = [
                (ws_engine, "wsp-casehub-engine"),
                None,
            ]
            with patch("slot_lifecycle.discover_workspace", return_value=None):
                slot_lifecycle.create_slot(
                    family_root=family,
                    repos=["engine", "iot"],
                    branch="issue-42-spi",
                    issue="42",
                    issue_repo="casehubio/engine",
                    covers="42",
                    context="Cross-repo work",
                )



class TestCreateSlotIsx:
    @patch("slot_lifecycle.run_cmd")
    def test_create_isx_slot_preflight_fails(self, mock_cmd, tmp_path):
        family = tmp_path / "casehub"
        family.mkdir()
        init_repo(family / "engine")
        mock_cmd.return_value = (0, "", "")
        with patch("shutil.which", return_value=None):
            with pytest.raises(slot_core.SlotCreationError, match="isx is not on PATH"):
                slot_lifecycle.create_slot(
                    family_root=family, repos=["engine"],
                    branch="issue-42-fix", issue="42",
                    issue_repo="Hortora/soredium", covers="42",
                    context="test", isx=True, isx_template="tpl-java",
                )

    @patch("slot_lifecycle.run_cmd")
    def test_create_isx_slot_writes_isolation(self, mock_cmd, tmp_path):
        family = tmp_path / "casehub"
        family.mkdir()
        init_repo(family / "engine")
        mock_cmd.return_value = (0, "", "")
        with patch("shutil.which", return_value="/opt/homebrew/bin/isx"):
            result = slot_lifecycle.create_slot(
                family_root=family, repos=["engine"],
                branch="issue-42-fix", issue="42",
                issue_repo="Hortora/soredium", covers="42",
                context="test", isx=True, isx_template="tpl-java",
            )
        slot_dir = family / "slots" / str(result["slot_number"])
        info = slot_metadata.parse_slot_md(slot_dir)
        assert info["isolation_type"] == "isx"
        assert info["isx_template"] == "tpl-java"
        assert info["isx_instance"] == "issue-42-fix"

    @patch("slot_lifecycle.run_cmd")
    def test_create_non_isx_unchanged(self, mock_cmd, tmp_path):
        family = tmp_path / "casehub"
        family.mkdir()
        init_repo(family / "engine")
        mock_cmd.return_value = (0, "", "")
        result = slot_lifecycle.create_slot(
            family_root=family, repos=["engine"],
            branch="issue-42-fix", issue="42",
            issue_repo="Hortora/soredium", covers="42",
            context="test",
        )
        slot_dir = family / "slots" / str(result["slot_number"])
        info = slot_metadata.parse_slot_md(slot_dir)
        assert info["isolation_type"] == ""

    @patch("slot_lifecycle.run_cmd")
    def test_create_isx_slot_isx_branch_fails(self, mock_cmd, tmp_path, capsys):
        family = tmp_path / "casehub"
        family.mkdir()
        init_repo(family / "engine")
        call_count = [0]
        def side_effect(args, cwd=None):
            call_count[0] += 1
            if args[0] == "isx" and args[1] == "branch":
                return (1, "", "template not found")
            return (0, "", "")
        mock_cmd.side_effect = side_effect
        with patch("shutil.which", return_value="/opt/homebrew/bin/isx"):
            with pytest.raises(slot_core.SlotCreationError, match="isx_branch_failed"):
                slot_lifecycle.create_slot(
                    family_root=family, repos=["engine"],
                    branch="issue-42-fix", issue="42",
                    issue_repo="Hortora/soredium", covers="42",
                    context="test", isx=True, isx_template="tpl-java",
                )



class TestRemoveSlot:
    def test_archives_to_attic_by_default(self, tmp_path):
        family = tmp_path / "casehub"
        slot = family / "slots" / "1"
        slot.mkdir(parents=True)
        (slot / ".slot").write_text("test")
        (slot / ".m2").mkdir()
        (slot / ".landed").write_text("branch=test\n")

        with patch("slot_core.run_cmd") as mock_cmd:
            mock_cmd.return_value = (0, "", "")
            slot_lifecycle.remove_slot(family, 1)

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

        with patch("slot_core.run_cmd") as mock_cmd:
            mock_cmd.return_value = (0, "", "")
            slot_lifecycle.remove_slot(family, 1)

        attic = family / "slots" / "attic" / "1"
        assert (attic / "myrepo" / "src.java").exists(), "repo deleted during archive — attic is useless without it"

    def test_force_archives_without_landed_check(self, tmp_path):
        """--force skips .landed check but still archives to attic."""
        family = tmp_path / "casehub"
        slot = family / "slots" / "1"
        slot.mkdir(parents=True)
        (slot / ".slot").write_text("test")

        with patch("slot_core.run_cmd") as mock_cmd:
            mock_cmd.return_value = (0, "", "")
            slot_lifecycle.remove_slot(family, 1, force=True)

        assert not slot.exists()
        attic = family / "slots" / "attic" / "1"
        assert attic.exists(), "force must archive to attic, never delete"
        assert (attic / ".slot").exists()

    def test_nonexistent_slot_errors(self, tmp_path, capsys):
        family = tmp_path / "casehub"
        (family / "slots").mkdir(parents=True)

        with pytest.raises(SystemExit):
            slot_lifecycle.remove_slot(family, 99)
        captured = capsys.readouterr()
        assert "ERROR=slot_not_found" in captured.out



class TestAddRepoIsx:
    @patch("slot_isx.run_cmd")
    def test_add_repo_wires_isx_remote(self, mock_cmd, tmp_path):
        family = tmp_path / "casehub"
        family.mkdir()
        slot_dir = family / "slots" / "1"
        slot_dir.mkdir(parents=True)
        init_repo(slot_dir / "engine")
        init_repo(family / "iot")
        slot_metadata.write_slot_md(
            slot_dir, 1, ["engine"], "test-branch", "42",
            "Org/repo", "42", "test",
            isolation_type="isx", isx_instance="test-inst",
            isx_template="tpl-java",
        )
        mock_cmd.return_value = (0, "", "")
        slot_lifecycle.add_repo(family, 1, "iot", "test-branch")
        isx_calls = [c for c in mock_cmd.call_args_list
                    if len(c[0][0]) > 5 and "isx://" in str(c[0][0])]
        assert len(isx_calls) >= 1

    @patch("slot_isx.run_cmd")
    def test_add_repo_non_isx_no_remote(self, mock_cmd, tmp_path):
        family = tmp_path / "casehub"
        family.mkdir()
        slot_dir = family / "slots" / "1"
        slot_dir.mkdir(parents=True)
        init_repo(slot_dir / "engine")
        init_repo(family / "iot")
        slot_metadata.write_slot_md(
            slot_dir, 1, ["engine"], "test-branch", "42",
            "Org/repo", "42", "test",
        )
        mock_cmd.return_value = (0, "", "")
        slot_lifecycle.add_repo(family, 1, "iot", "test-branch")
        isx_calls = [c for c in mock_cmd.call_args_list
                    if any("isx://" in str(a) for a in c[0][0])]
        assert len(isx_calls) == 0



class TestRemoveSlotIsx:
    def test_remove_destroys_isx(self, tmp_path):
        family = tmp_path / "casehub"
        slot_dir = family / "slots" / "1"
        slot_dir.mkdir(parents=True)
        init_repo(slot_dir / "engine")
        slot_metadata.write_slot_md(
            slot_dir, 1, ["engine"], "test-branch", "42",
            "Org/repo", "42", "test",
            isolation_type="isx", isx_instance="test-inst",
            isx_template="tpl-java",
        )
        (slot_dir / ".landed").write_text("landed")
        with patch("slot_core.run_cmd", return_value=(0, "", "")):
            with patch("slot_lifecycle._teardown_isx") as mock_teardown:
                slot_lifecycle.remove_slot(family, 1)
                mock_teardown.assert_called_once()



class TestResolveOriginalRepo:
    def test_resolves_worktree_to_original(self, tmp_path):
        family, originals, slot, _ = _create_worktree_test_repos(tmp_path, ["engine"])
        resolved = slot_core.resolve_original_repo(slot / "engine")
        assert resolved == originals["engine"]



class TestMergeSlot:
    def test_clean_rebase_and_push(self, tmp_path):
        family, originals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        exit_code = slot_lifecycle.merge_slot(family, 1)
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
        subprocess.run(["git", "-C", str(originals["engine"]), "push", "origin", "main"], capture_output=True)
        exit_code = slot_lifecycle.merge_slot(family, 1)
        assert exit_code != 0
        assert not (slot / ".landed").exists()

    def test_not_found(self, tmp_path):
        family = tmp_path / "family"
        (family / "slots").mkdir(parents=True)
        assert slot_lifecycle.merge_slot(family, 99) == 1

    def test_not_ready(self, tmp_path):
        family = tmp_path / "family"
        slot = family / "slots" / "1"
        slot.mkdir(parents=True)
        assert slot_lifecycle.merge_slot(family, 1) == 1

    def test_already_landed(self, tmp_path):
        family, _, slot, _ = _create_merge_test_repos(tmp_path, ["engine"])
        (slot / ".landed").write_text("already\n")
        assert slot_lifecycle.merge_slot(family, 1) == 1



class TestMergeSlotStamping:
    def test_writes_stamp_commits_on_merge(self, tmp_path):
        family, originals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        exit_code = slot_lifecycle.merge_slot(family, 1)
        assert exit_code == 0

        rc, log, _ = slot_core.run_cmd(
            ["git", "-C", str(slot / "engine"), "log", "-1", "--format=%s"]
        )
        assert rc == 0
        assert log.strip().startswith("chore: branch closed — landed as")
        assert "on main" in log.strip()

    def test_stamp_sha_matches_landed_shas(self, tmp_path):
        family, originals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        slot_lifecycle.merge_slot(family, 1)

        landed = (slot / ".landed").read_text()
        sha_from_landed = ""
        for line in landed.splitlines():
            if line.startswith("landed_shas="):
                for entry in line.split("=", 1)[1].split(","):
                    if entry.startswith("engine:"):
                        sha_from_landed = entry.split(":", 1)[1]

        rc, log, _ = slot_core.run_cmd(
            ["git", "-C", str(slot / "engine"), "log", "-1", "--format=%s"]
        )
        assert sha_from_landed in log.strip()

    def test_multi_repo_all_stamped(self, tmp_path):
        family, originals, slot, branch = _create_merge_test_repos(
            tmp_path, ["engine", "iot"]
        )
        slot_lifecycle.merge_slot(family, 1)

        for repo_name in ["engine", "iot"]:
            rc, log, _ = slot_core.run_cmd(
                ["git", "-C", str(slot / repo_name), "log", "-1", "--format=%s"]
            )
            assert rc == 0
            assert log.strip().startswith("chore: branch closed")

    def test_no_stamp_on_merge_failure(self, tmp_path):
        family, originals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        (originals["engine"] / "feature.py").write_text("# conflict\n")
        subprocess.run(["git", "-C", str(originals["engine"]), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(originals["engine"]), "commit", "-m", "conflict"], capture_output=True)
        subprocess.run(["git", "-C", str(originals["engine"]), "push", "origin", "main"], capture_output=True)

        slot_lifecycle.merge_slot(family, 1)

        rc, log, _ = slot_core.run_cmd(
            ["git", "-C", str(slot / "engine"), "log", "-1", "--format=%s"]
        )
        assert "chore: branch closed" not in log.strip()



class TestArchiveSlot:
    def test_moves_to_attic_after_verified_merge(self, tmp_path):
        family, originals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        slot_lifecycle.merge_slot(family, 1)

        slot_lifecycle.archive_slot(family, 1)

        assert not (family / "slots" / "1").exists()
        attic_slot = family / "slots" / "attic" / "1"
        assert attic_slot.exists()
        assert (attic_slot / ".slot").exists()
        assert (attic_slot / ".landed").exists()

    def test_preserves_repos_in_attic(self, tmp_path):
        """Archived slot must retain repo directories — attic is the recovery safety net."""
        family, originals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        slot_lifecycle.merge_slot(family, 1)

        assert (slot / "engine").is_dir()
        slot_lifecycle.archive_slot(family, 1)

        attic_slot = family / "slots" / "attic" / "1"
        assert (attic_slot / "engine").exists(), "repo deleted during archive — attic is useless without it"

    def test_blocks_archive_without_landed_marker(self, tmp_path, capsys):
        family, _, slot, _ = _create_merge_test_repos(tmp_path, ["engine"])
        subprocess.run(["git", "-C", str(slot / "engine"), "checkout", "main"], capture_output=True)

        with pytest.raises(SystemExit):
            slot_lifecycle.archive_slot(family, 1)
        captured = capsys.readouterr()
        assert "ERROR=slot_not_landed" in captured.out

    def test_blocks_archive_when_sha_not_on_main(self, tmp_path, capsys):
        family, _, slot, _ = _create_merge_test_repos(tmp_path, ["engine"])
        rc, sha, _ = slot_core.run_cmd(
            ["git", "-C", str(slot / "engine"), "rev-parse", "HEAD"]
        )
        subprocess.run(["git", "-C", str(slot / "engine"), "checkout", "main"], capture_output=True)
        (slot / ".landed").write_text(
            f"branch=issue-42-test\nrepos=engine\nlanded_shas=engine:{sha.strip()}\n"
        )

        with pytest.raises(SystemExit):
            slot_lifecycle.archive_slot(family, 1)
        captured = capsys.readouterr()
        assert "ERROR=sha_not_on_main" in captured.out

    def test_blocks_archive_with_unmerged_content(self, tmp_path, capsys):
        """Unmerged content gate fires before landed/SHA checks — no force override."""
        family, _, slot, _ = _create_merge_test_repos(tmp_path, ["engine"])

        with pytest.raises(SystemExit):
            slot_lifecycle.archive_slot(family, 1, force=True)
        captured = capsys.readouterr()
        assert "ERROR=unmerged_content" in captured.out

    def test_force_bypasses_all_checks(self, tmp_path):
        family, _, slot, _ = _create_merge_test_repos(tmp_path, ["engine"])
        subprocess.run(["git", "-C", str(slot / "engine"), "checkout", "main"], capture_output=True)

        slot_lifecycle.archive_slot(family, 1, force=True)

        assert not (family / "slots" / "1").exists()
        assert (family / "slots" / "attic" / "1").exists()

    def test_writes_pid_file_on_archive(self, tmp_path, monkeypatch):
        family, originals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        slot_lifecycle.merge_slot(family, 1)

        fake_home = tmp_path / "home"
        claude_projects = fake_home / ".claude" / "projects"
        claude_projects.mkdir(parents=True)

        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

        slot_lifecycle.archive_slot(family, 1)

        attic_path = family / "slots" / "attic" / "1"
        pid_file = attic_path / ".archived-by-pid"
        assert pid_file.exists()
        pid = int(pid_file.read_text().strip())
        assert pid > 0

    def test_sweep_renames_after_pid_exits(self, tmp_path, monkeypatch):
        family, originals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        slot_lifecycle.merge_slot(family, 1)

        fake_home = tmp_path / "home"
        claude_projects = fake_home / ".claude" / "projects"
        claude_projects.mkdir(parents=True)
        slot_path_encoded = str(slot / "engine").replace("/", "-")
        proj_dir = claude_projects / slot_path_encoded
        proj_dir.mkdir()
        (proj_dir / "memory.md").write_text("session memory")

        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

        slot_lifecycle.archive_slot(family, 1)

        # Project dir still at old path (not renamed yet)
        assert proj_dir.exists()

        # Write a dead PID to simulate session exit
        attic_path = family / "slots" / "attic" / "1"
        (attic_path / ".archived-by-pid").write_text("99999999")

        # Sweep should rename
        swept = slot_claude.sweep_orphaned_claude_projects(family)
        assert swept >= 1
        assert not proj_dir.exists()
        dest_encoded = str(attic_path / "engine").replace("/", "-")
        moved_dir = claude_projects / dest_encoded
        assert moved_dir.exists()
        assert (moved_dir / "memory.md").read_text() == "session memory"

    def test_not_found_exits(self, tmp_path, capsys):
        family = tmp_path / "family"
        (family / "slots").mkdir(parents=True)
        with pytest.raises(SystemExit):
            slot_lifecycle.archive_slot(family, 99)
        captured = capsys.readouterr()
        assert "ERROR=slot_not_found" in captured.out



class TestResolveOriginalRepoClone:
    def test_resolves_clone_to_original(self, tmp_path):
        original = init_repo_with_remote(tmp_path / "original")
        clone = tmp_path / "clone"
        subprocess.run([
            "git", "clone", "--shared", str(original), str(clone),
        ], capture_output=True, check=True)
        resolved = slot_core.resolve_original_repo(clone)
        assert resolved == original.resolve()

    def test_resolves_worktree_to_original(self, tmp_path):
        family, originals, slot, _ = _create_worktree_test_repos(tmp_path, ["engine"])
        resolved = slot_core.resolve_original_repo(slot / "engine")
        assert resolved == originals["engine"]

    def test_fallback_returns_self(self, tmp_path):
        repo = init_repo(tmp_path / "standalone")
        resolved = slot_core.resolve_original_repo(repo)
        assert resolved == repo



class TestMergeSlotClone:
    def test_clone_merge_pushes_then_merges(self, tmp_path):
        family, originals, slot, branch = _create_clone_test_repos(tmp_path, ["engine"])
        exit_code = slot_lifecycle.merge_slot(family, 1)
        assert exit_code == 0
        assert (originals["engine"] / "feature.py").exists()
        assert (slot / ".landed").exists()

    def test_clone_multi_repo_merge(self, tmp_path):
        family, originals, slot, branch = _create_clone_test_repos(tmp_path, ["engine", "iot"])
        exit_code = slot_lifecycle.merge_slot(family, 1)
        assert exit_code == 0
        for name in ["engine", "iot"]:
            assert (originals[name] / "feature.py").exists()

    def test_clone_stamps_pushed_to_bare(self, tmp_path):
        """Stamps are pushed to origin (bare repo acting as GitHub)."""
        family, originals, slot, branch = _create_clone_test_repos(tmp_path, ["engine"])
        slot_lifecycle.merge_slot(family, 1)
        bare_path = family / ".engine-bare.git"
        rc, log, _ = slot_core.run_cmd(
            ["git", "-C", str(bare_path), "log", "--all", "--oneline", "--grep=branch closed"]
        )
        assert "branch closed" in log



class TestMergeSlotOriginalSafety:
    def test_passes_when_original_not_on_main(self, tmp_path, capsys):
        """Relaxed preflight: original on a feature branch is fine (D7)."""
        family, originals, slot, branch = _create_clone_test_repos(tmp_path, ["engine"])
        subprocess.run(
            ["git", "-C", str(originals["engine"]), "checkout", "-b", "some-other-branch"],
            capture_output=True, check=True,
        )
        exit_code = slot_lifecycle.merge_slot(family, 1)
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "not_on_main" not in out.lower()

    def test_fails_when_original_has_dirty_worktree_on_main(self, tmp_path, capsys):
        family, originals, slot, branch = _create_clone_test_repos(tmp_path, ["engine"])
        (originals["engine"] / "dirty.txt").write_text("uncommitted change\n")
        subprocess.run(
            ["git", "-C", str(originals["engine"]), "add", "dirty.txt"],
            capture_output=True, check=True,
        )
        exit_code = slot_lifecycle.merge_slot(family, 1)
        assert exit_code != 0
        assert not (slot / ".landed").exists()
        out = capsys.readouterr().out
        assert "dirty" in out.lower() or "DIRTY" in out

    def test_dirty_worktree_on_feature_branch_passes(self, tmp_path, capsys):
        """Dirty worktree on non-main branch is fine — push to main still works."""
        family, originals, slot, branch = _create_clone_test_repos(tmp_path, ["engine"])
        subprocess.run(
            ["git", "-C", str(originals["engine"]), "checkout", "-b", "detour"],
            capture_output=True, check=True,
        )
        (originals["engine"] / "dirty.txt").write_text("uncommitted change\n")
        exit_code = slot_lifecycle.merge_slot(family, 1)
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "dirty_worktree" not in out

    def test_passes_when_original_not_on_main_worktree_layout(self, tmp_path, capsys):
        family, originals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        subprocess.run(
            ["git", "-C", str(originals["engine"]), "checkout", "-b", "detour"],
            capture_output=True, check=True,
        )
        exit_code = slot_lifecycle.merge_slot(family, 1)
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "not_on_main" not in out.lower()



class TestArchiveSlotDoubleArchive:
    def test_merges_when_attic_slot_already_exists(self, tmp_path, capsys):
        """archive_slot merges into existing attic entry — handles restore-then-rearchive."""
        family, originals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        slot_lifecycle.merge_slot(family, 1)

        # First archive — should succeed
        slot_lifecycle.archive_slot(family, 1)
        attic = family / "slots" / "attic" / "1"
        assert attic.exists()

        # Recreate slot dir with new content (simulates restore + rework + reland)
        (family / "slots" / "1").mkdir()
        (family / "slots" / "1" / ".slot").write_text("restored")
        (family / "slots" / "1" / ".landed").write_text("re-landed")

        # Second archive — should merge, not error
        slot_lifecycle.archive_slot(family, 1, force=True)
        captured = capsys.readouterr()
        assert "WARN=attic_slot_exists" in captured.out
        assert "ARCHIVING=1" in captured.out
        # New content merged into attic
        assert (attic / ".landed").read_text() == "re-landed"
        assert (attic / ".slot").read_text() == "restored"
        # Original slot dir removed
        assert not (family / "slots" / "1").exists()



class TestArchiveSlotCleanup:
    def test_cleans_remnant_after_move(self, tmp_path):
        """If shutil.move succeeds but source dir reappears, archive cleans it up."""
        family, originals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        slot_lifecycle.merge_slot(family, 1)

        original_move = shutil.move

        def move_then_recreate(src, dst):
            result = original_move(src, dst)
            Path(src).mkdir(parents=True)
            (Path(src) / "engine").mkdir()
            (Path(src) / "engine" / ".idea").mkdir()
            return result

        with patch("slot_lifecycle.shutil.move", side_effect=move_then_recreate):
            slot_lifecycle.archive_slot(family, 1)

        assert not slot.exists(), "remnant directory should be cleaned after archive"
        assert (family / "slots" / "attic" / "1").exists()

    def test_warns_if_remnant_persists(self, tmp_path, capsys):
        """If cleanup can't remove the dir (non-IDE content), warn."""
        family, originals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        slot_lifecycle.merge_slot(family, 1)

        original_move = shutil.move

        def move_then_recreate_with_content(src, dst):
            result = original_move(src, dst)
            Path(src).mkdir(parents=True)
            (Path(src) / "real_file.txt").write_text("not an IDE artifact")
            return result

        with patch("slot_lifecycle.shutil.move", side_effect=move_then_recreate_with_content):
            slot_lifecycle.archive_slot(family, 1)

        captured = capsys.readouterr()
        assert "WARN=remnant_dir_persists" in captured.out



class TestArchiveSlotPromotionGate:
    def test_warns_when_no_promotion_stamp(self, tmp_path, capsys):
        """archive_slot should warn when .artifacts-promoted stamp is missing."""
        family, originals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        slot_lifecycle.merge_slot(family, 1)

        # No .artifacts-promoted stamp — promotion never ran
        slot_lifecycle.archive_slot(family, 1)

        captured = capsys.readouterr()
        assert "WARN=artifacts_not_promoted" in captured.out

    def test_no_warning_when_stamp_exists(self, tmp_path, capsys):
        """No warning when .artifacts-promoted stamp is present."""
        family, originals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        slot_lifecycle.merge_slot(family, 1)

        # Simulate promotion stamp from close_artifacts.py
        ws_dirs = [d for d in slot.iterdir() if d.is_dir() and d.name.startswith("work")]
        # No workspace dir in this test — create a fake design/ with stamp
        # The stamp lives in workspace design/ but for non-workspace slots, we check the slot itself
        stamp_dir = slot / "design"
        stamp_dir.mkdir(exist_ok=True)
        (stamp_dir / ".artifacts-promoted").write_text("timestamp=2026-07-31\n")

        slot_lifecycle.archive_slot(family, 1)

        captured = capsys.readouterr()
        assert "WARN=artifacts_not_promoted" not in captured.out

    def test_force_archive_still_warns_about_promotion(self, tmp_path, capsys):
        """Even --force should warn about missing promotion stamp."""
        family, _, slot, _ = _create_merge_test_repos(tmp_path, ["engine"])
        subprocess.run(["git", "-C", str(slot / "engine"), "checkout", "main"], capture_output=True)

        slot_lifecycle.archive_slot(family, 1, force=True)

        captured = capsys.readouterr()
        assert "WARN=artifacts_not_promoted" in captured.out



class TestMergeSlotIncludesWorkspace:
    def _add_workspace_to_slot(self, family, slot, branch, ws_name="wsp-casehub-engine"):
        """Add a properly set up workspace clone to a slot."""
        ws_orig = init_repo_with_remote(family / ws_name)
        slot_git.configure_update_instead(ws_orig)
        ws_clone = slot / ws_name
        bare_path = family / f".{ws_name}-bare.git"
        subprocess.run(
            ["git", "clone", "--shared", "--branch", "main",
             str(ws_orig), str(ws_clone)],
            capture_output=True, check=True,
        )
        subprocess.run(["git", "-C", str(ws_clone), "config", "user.name", "Test"], capture_output=True)
        subprocess.run(["git", "-C", str(ws_clone), "config", "user.email", "test@test.com"], capture_output=True)
        subprocess.run(["git", "-C", str(ws_clone), "checkout", "-b", branch], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(ws_clone), "remote", "rename", "origin", "local"], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(ws_clone), "remote", "add", "origin", str(bare_path)], capture_output=True)
        subprocess.run(["git", "-C", str(ws_clone), "fetch", "origin"], capture_output=True)
        (ws_clone / ".workspace").touch()
        (ws_clone / "blog.md").write_text("# Blog entry\n")
        subprocess.run(["git", "-C", str(ws_clone), "add", "."], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(ws_clone), "commit", "-m", "blog entry"], capture_output=True, check=True)
        return ws_orig

    def test_workspace_clones_are_merged(self, tmp_path):
        """merge_slot discovers workspace clones and stamps them."""
        family, originals, slot, branch = _create_merge_test_repos(
            tmp_path, ["engine"]
        )
        self._add_workspace_to_slot(family, slot, branch)

        exit_code = slot_lifecycle.merge_slot(family, 1)
        assert exit_code == 0

        landed = (slot / ".landed").read_text()
        assert "engine:" in landed

    def test_workspace_with_marker_is_merged(self, tmp_path):
        """Workspace detected by .workspace marker is processed."""
        family, originals, slot, branch = _create_merge_test_repos(
            tmp_path, ["engine"]
        )
        self._add_workspace_to_slot(family, slot, branch, "custom-ws")

        exit_code = slot_lifecycle.merge_slot(family, 1)
        assert exit_code == 0

    def test_project_repos_still_merge_with_workspace(self, tmp_path):
        """Project repos merge normally alongside workspace repos."""
        family, originals, slot, branch = _create_merge_test_repos(
            tmp_path, ["engine", "iot"]
        )
        self._add_workspace_to_slot(family, slot, branch)

        exit_code = slot_lifecycle.merge_slot(family, 1)
        assert exit_code == 0

        for name in ["engine", "iot"]:
            assert (originals[name] / "feature.py").exists()



class TestRemoveSlotForceArchiveClaude:
    def test_force_writes_pid_and_keeps_project_dir(self, tmp_path, monkeypatch):
        """--force archives to attic, writes PID file, leaves project dir for sweep."""
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

        with patch("slot_core.run_cmd") as mock_cmd:
            mock_cmd.return_value = (0, "", "")
            slot_lifecycle.remove_slot(family, 1, force=True)

        attic = family / "slots" / "attic" / "1"
        assert attic.exists(), "force must archive to attic, never delete"
        assert (attic / ".slot").exists()
        assert (attic / ".archived-by-pid").exists()
        assert proj_dir.exists(), "project dir stays until sweep renames it"



class TestAllocateSlotNumberDB:
    """DB-authoritative slot numbering: reserve-first pattern."""

    def _setup_db(self, tmp_path, monkeypatch):
        scripts_dir = Path(__file__).parent.parent / "scripts"
        sys.path.insert(0, str(scripts_dir))
        import worklog as _wl_mod
        db_path = tmp_path / "test.db"
        monkeypatch.setattr(slot_lifecycle, "_wl", _wl_mod)
        monkeypatch.setattr(_wl_mod, "DEFAULT_DB", str(db_path))
        return _wl_mod

    def test_first_slot_returns_1(self, tmp_path, monkeypatch):
        self._setup_db(tmp_path, monkeypatch)
        num = slot_lifecycle.allocate_slot_number(tmp_path)
        assert num == 1

    def test_increments_from_existing(self, tmp_path, monkeypatch):
        _wl_mod = self._setup_db(tmp_path, monkeypatch)
        num1 = slot_lifecycle.allocate_slot_number(tmp_path)
        # Activate the pending slot so it is not reused by find_reusable_slot
        conn = _wl_mod.connect()
        conn.execute("UPDATE slots SET state='active' WHERE slot_number=?", (num1,))
        conn.commit()
        conn.close()
        num = slot_lifecycle.allocate_slot_number(tmp_path)
        assert num == 2

    def test_hard_fails_without_worklog(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(slot_lifecycle, "_wl", None)
        with pytest.raises(SystemExit):
            slot_lifecycle.allocate_slot_number(tmp_path)
        captured = capsys.readouterr()
        assert "ERROR=worklog_unavailable" in captured.out

    def test_inserts_pending_row(self, tmp_path, monkeypatch):
        _wl_mod = self._setup_db(tmp_path, monkeypatch)
        num = slot_lifecycle.allocate_slot_number(tmp_path)
        conn = _wl_mod.connect()
        row = conn.execute(
            "SELECT state FROM slots WHERE slot_number=?", (num,)
        ).fetchone()
        conn.close()
        assert row["state"] == "pending"

    def test_different_families_independent(self, tmp_path, monkeypatch):
        self._setup_db(tmp_path, monkeypatch)
        family_a = tmp_path / "a"
        family_a.mkdir()
        family_b = tmp_path / "b"
        family_b.mkdir()
        slot_lifecycle.allocate_slot_number(family_a)
        slot_lifecycle.allocate_slot_number(family_a)
        num = slot_lifecycle.allocate_slot_number(family_b)
        assert num == 1



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
        (wt / ".plan").write_text(
            "# Work Plan — slot-72\n\n## State\nbranch: issue-50\nstate: active\ncovers: 83,84\n\n"
            "## Queue\n- [x] #83 — Done\n- [ ] #84 — Active ← active\n"
        )
        (wt / ".phase-a-complete").write_text("branch=issue-50\nrepos=engine\n")
        repo = init_repo(wt / "engine")
        subprocess.run(["git", "-C", str(repo), "checkout", "-b", "issue-50"], capture_output=True)
        (repo / "file.txt").write_text("content")
        subprocess.run(["git", "-C", str(repo), "add", "file.txt"], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "feat: work"], capture_output=True)
        with patch.object(slot_core, "resolve_original_repo", return_value=repo):
            with patch.object(slot_git, "is_worktree", return_value=False):
                result = slot_lifecycle.merge_slot(family, 72)
        out = capsys.readouterr().out
        assert "EPIC_STATUS=" in out



class TestAddRepo:
    def test_adds_repo_to_slot(self, tmp_path):
        family = tmp_path / "family"
        repo1 = init_repo_with_workspace(family / "engine")
        repo2 = init_repo(family / "trellis")
        ws_path = family / f"wsp-{family.name}-engine"
        with patch("slot_lifecycle.resolve_workspace_source", return_value=(ws_path, "wsp-test")):
            result = slot_lifecycle.create_slot(
                family_root=family, repos=["engine"], branch="issue-42-test",
                issue="42", issue_repo="org/repo", covers="42", context="test",
            )
        slot_dir = family / "slots" / str(result["slot_number"])
        slot_lifecycle.add_repo(family, result["slot_number"], "trellis", "issue-42-test")
        assert (slot_dir / "trellis").exists()
        assert (slot_dir / "trellis" / ".git").exists()
        current = subprocess.run(
            ["git", "-C", str(slot_dir / "trellis"), "branch", "--show-current"],
            capture_output=True, text=True,
        ).stdout.strip()
        assert current == "issue-42-test"

    def test_updates_slot_file(self, tmp_path):
        family = tmp_path / "family"
        init_repo_with_workspace(family / "engine")
        init_repo(family / "trellis")
        ws_path = family / f"wsp-{family.name}-engine"
        with patch("slot_lifecycle.resolve_workspace_source", return_value=(ws_path, "wsp-test")):
            result = slot_lifecycle.create_slot(
                family_root=family, repos=["engine"], branch="issue-42-test",
                issue="42", issue_repo="org/repo", covers="42", context="test",
            )
        slot_dir = family / "slots" / str(result["slot_number"])
        slot_lifecycle.add_repo(family, result["slot_number"], "trellis", "issue-42-test")
        content = (slot_dir / ".slot").read_text()
        assert "trellis" in content

    def test_rejects_duplicate_repo(self, tmp_path):
        family = tmp_path / "family"
        init_repo_with_workspace(family / "engine")
        ws_path = family / f"wsp-{family.name}-engine"
        with patch("slot_lifecycle.resolve_workspace_source", return_value=(ws_path, "wsp-test")):
            result = slot_lifecycle.create_slot(
                family_root=family, repos=["engine"], branch="issue-42-test",
                issue="42", issue_repo="org/repo", covers="42", context="test",
            )
        with pytest.raises(SystemExit):
            slot_lifecycle.add_repo(family, result["slot_number"], "engine", "issue-42-test")



class TestRemoveRepo:
    def test_removes_repo_from_slot(self, tmp_path):
        family = tmp_path / "family"
        init_repo_with_workspace(family / "engine")
        init_repo(family / "trellis")
        ws_path = family / f"wsp-{family.name}-engine"
        with patch("slot_lifecycle.resolve_workspace_source", side_effect=[(ws_path, "wsp-test"), None]), \
             patch("slot_lifecycle.discover_workspace", return_value=None):
            result = slot_lifecycle.create_slot(
                family_root=family, repos=["engine", "trellis"], branch="issue-42-test",
                issue="42", issue_repo="org/repo", covers="42", context="test",
            )
        slot_dir = family / "slots" / str(result["slot_number"])
        slot_lifecycle.remove_repo(family, result["slot_number"], "trellis")
        assert not (slot_dir / "trellis").exists()
        content = (slot_dir / ".slot").read_text()
        assert "trellis" not in content

    def test_refuses_to_remove_primary(self, tmp_path):
        family = tmp_path / "family"
        init_repo_with_workspace(family / "engine")
        ws_path = family / f"wsp-{family.name}-engine"
        with patch("slot_lifecycle.resolve_workspace_source", return_value=(ws_path, "wsp-test")):
            result = slot_lifecycle.create_slot(
                family_root=family, repos=["engine"], branch="issue-42-test",
                issue="42", issue_repo="org/repo", covers="42", context="test",
            )
        with pytest.raises(ValueError, match="primary"):
            slot_lifecycle.remove_repo(family, result["slot_number"], "engine")



class TestCreateSlotUsesNewDir:
    def test_creates_under_slots_not_worktrees(self, tmp_path):
        repo = init_repo_with_workspace(tmp_path / "myrepo")
        ws_path = tmp_path / f"wsp-{tmp_path.name}-myrepo"
        with patch("slot_lifecycle.resolve_workspace_source", return_value=(ws_path, "wsp-test")):
            result = slot_lifecycle.create_slot(
                family_root=tmp_path, repos=["myrepo"], branch="test-branch",
                issue="1", issue_repo="org/repo", covers="1", context="test",
            )
        assert (tmp_path / "slots").exists()
        assert not (tmp_path / "worktrees").exists()
        assert (tmp_path / "slots" / "1").exists()



class TestMergeSlotRelaxedPreflight:
    def _setup_slot(self, tmp_path):
        family = tmp_path / "family"
        family.mkdir()
        original = init_repo_with_remote(family / "engine")
        slot_git.configure_update_instead(original)

        slot_dir = family / "slots" / "1"
        slot_dir.mkdir(parents=True)
        clone = slot_dir / "engine"
        bare_path = family / ".engine-bare.git"
        subprocess.run(["git", "clone", "--shared", "--branch", "main",
                        str(original), str(clone)], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(clone), "config", "user.name", "Test"], capture_output=True)
        subprocess.run(["git", "-C", str(clone), "config", "user.email", "test@test.com"], capture_output=True)
        subprocess.run(["git", "-C", str(clone), "checkout", "-b", "feature-1"],
                       capture_output=True, check=True)
        subprocess.run(["git", "-C", str(clone), "remote", "rename", "origin", "local"],
                       capture_output=True, check=True)
        subprocess.run(["git", "-C", str(clone), "remote", "add", "origin",
                        str(bare_path)], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(clone), "fetch", "origin"], capture_output=True)

        (clone / "feature.txt").write_text("new feature")
        subprocess.run(["git", "-C", str(clone), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(clone), "commit", "-m", "feat: feature"],
                       capture_output=True)

        (slot_dir / ".phase-a-complete").write_text("branch=feature-1\n")
        (slot_dir / ".slot").write_text(
            "# Slot 1 — feature-1\n## Repos\n- engine\n")
        return family, slot_dir, original, clone

    def test_original_on_feature_branch_passes_preflight(self, tmp_path):
        family, slot_dir, original, clone = self._setup_slot(tmp_path)
        subprocess.run(["git", "-C", str(original), "checkout", "-b", "other-work"],
                       capture_output=True)

        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            result = slot_lifecycle.merge_slot(family, 1)
        assert "not_on_main" not in captured.getvalue()

    def test_dirty_worktree_on_main_blocks(self, tmp_path):
        family, slot_dir, original, clone = self._setup_slot(tmp_path)
        (original / "dirty.txt").write_text("uncommitted")

        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            result = slot_lifecycle.merge_slot(family, 1)
        assert result == 1
        assert "dirty_worktree" in captured.getvalue()

    def test_unpushed_commits_auto_pushed_in_preflight(self, tmp_path):
        """Original has unpushed commits on main — preflight pushes them."""
        family, slot_dir, original, clone = self._setup_slot(tmp_path)
        (original / "local-work.txt").write_text("local work")
        subprocess.run(["git", "-C", str(original), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(original), "commit", "-m", "local work"], capture_output=True)

        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            result = slot_lifecycle.merge_slot(family, 1)

        assert "SYNC=pushed" in captured.getvalue()
        bare_path = family / ".engine-bare.git"
        rc, bare_log, _ = slot_core.run_cmd(
            ["git", "-C", str(bare_path), "log", "--oneline", "main"])
        assert "local work" in bare_log

    def test_dirty_worktree_on_feature_branch_passes(self, tmp_path):
        family, slot_dir, original, clone = self._setup_slot(tmp_path)
        subprocess.run(["git", "-C", str(original), "checkout", "-b", "other-work"],
                       capture_output=True)
        (original / "dirty.txt").write_text("uncommitted")

        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            result = slot_lifecycle.merge_slot(family, 1)
        assert "dirty_worktree" not in captured.getvalue()



class TestMergeSlotDualPush:
    def _setup_full_slot(self, tmp_path):
        """Create a slot with project + workspace, using real bare repos."""
        family = tmp_path / "family"
        family.mkdir()

        proj_orig = init_repo_with_remote(family / "engine")
        slot_git.configure_update_instead(proj_orig)

        ws_orig = init_repo_with_remote(family / "work-hub")
        slot_git.configure_update_instead(ws_orig)

        slot_dir = family / "slots" / "1"
        slot_dir.mkdir(parents=True)

        for name, orig in [("engine", proj_orig), ("work-hub", ws_orig)]:
            clone = slot_dir / name
            bare_path = family / f".{name}-bare.git"
            subprocess.run(["git", "clone", "--shared", "--branch", "main",
                            str(orig), str(clone)], capture_output=True, check=True)
            subprocess.run(["git", "-C", str(clone), "config", "user.name", "Test"], capture_output=True)
            subprocess.run(["git", "-C", str(clone), "config", "user.email", "test@test.com"], capture_output=True)
            subprocess.run(["git", "-C", str(clone), "checkout", "-b", "feature-1"], capture_output=True, check=True)
            subprocess.run(["git", "-C", str(clone), "remote", "rename", "origin", "local"], capture_output=True, check=True)
            subprocess.run(["git", "-C", str(clone), "remote", "add", "origin", str(bare_path)], capture_output=True, check=True)
            subprocess.run(["git", "-C", str(clone), "fetch", "origin"], capture_output=True)

        (slot_dir / "engine" / "feature.txt").write_text("feature work")
        subprocess.run(["git", "-C", str(slot_dir / "engine"), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(slot_dir / "engine"), "commit", "-m", "feat: add feature"], capture_output=True)

        (slot_dir / "work-hub" / "journal.md").write_text("# Journal")
        subprocess.run(["git", "-C", str(slot_dir / "work-hub"), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(slot_dir / "work-hub"), "commit", "-m", "docs: journal"], capture_output=True)

        (slot_dir / ".phase-a-complete").write_text("branch=feature-1\n")
        (slot_dir / ".slot").write_text(
            "# Slot 1 — feature-1\n## Repos\n- engine\n")

        return family, slot_dir, proj_orig, ws_orig

    def test_workspace_repo_merged_by_slot(self, tmp_path, capsys):
        """Workspace repos are now processed by merge_slot (convergence)."""
        family, slot_dir, proj_orig, ws_orig = self._setup_full_slot(tmp_path)
        result = slot_lifecycle.merge_slot(family, 1)

        assert result == 0
        captured = capsys.readouterr().out
        assert "SKIPPED_WORKSPACE" not in captured

        rc, ws_log, _ = slot_core.run_cmd(
            ["git", "-C", str(ws_orig), "log", "--oneline"])
        assert "journal" in ws_log.lower()

        landed = (slot_dir / ".landed").read_text()
        assert "engine:" in landed

    def test_github_push_failure_is_warning_not_error(self, tmp_path, capsys):
        """If original can't push to GitHub, local push succeeded — warn, don't block."""
        family, slot_dir, proj_orig, ws_orig = self._setup_full_slot(tmp_path)
        import land_flow
        original_git = land_flow._git

        def mock_github_fail(repo, *args):
            repo_str = str(repo)
            if "push" in args and "origin" in args and "main" in args:
                if str(family / "engine") in repo_str or str(family / "work-hub") in repo_str:
                    import subprocess
                    return subprocess.CompletedProcess(
                        args=["git"], returncode=1, stdout="", stderr="network error",
                    )
            return original_git(repo, *args)

        with patch.object(land_flow, "_git", side_effect=mock_github_fail):
            result = slot_lifecycle.merge_slot(family, 1)

        assert result == 0
        captured = capsys.readouterr().out
        assert "github_push_failed" in captured

    def test_local_push_failure_blocks(self, tmp_path):
        """If slot can't push to original, hard stop — work not landed."""
        family, slot_dir, proj_orig, ws_orig = self._setup_full_slot(tmp_path)
        import land_flow
        original_git = land_flow._git

        def mock_local_fail(repo, *args):
            if "push" in args and "local" in args and "main" in args:
                import subprocess
                return subprocess.CompletedProcess(
                    args=["git"], returncode=1, stdout="", stderr="rejected",
                )
            return original_git(repo, *args)

        with patch.object(land_flow, "_git", side_effect=mock_local_fail):
            result = slot_lifecycle.merge_slot(family, 1)

        assert result == 1



class TestCreateSlotRemoteConfig:
    def test_create_slot_configures_remotes_on_project_clone(self, tmp_path):
        family = tmp_path / "family"
        family.mkdir()
        repo = init_repo_with_workspace(family / "engine")
        subprocess.run(["git", "-C", str(repo), "remote", "add", "origin",
                        "https://github.com/user/engine.git"], capture_output=True)

        ws_path = family / f"wsp-{family.name}-engine"
        with patch("slot_lifecycle.sync_main"), \
             patch("slot_lifecycle.resolve_workspace_source", return_value=(ws_path, "wsp-test")):
            result = slot_lifecycle.create_slot(family, ["engine"], "feature-1",
                                              "1", "user/engine", "1", "test")

        clone = family / "slots" / str(result["slot_number"]) / "engine"
        rc, local_url, _ = slot_core.run_cmd(
            ["git", "-C", str(clone), "remote", "get-url", "local"])
        assert rc == 0

        rc, origin_url, _ = slot_core.run_cmd(
            ["git", "-C", str(clone), "remote", "get-url", "origin"])
        assert rc == 0
        assert origin_url.strip() == "https://github.com/user/engine.git"

        rc, value, _ = slot_core.run_cmd(
            ["git", "-C", str(repo), "config", "receive.denyCurrentBranch"])
        assert rc == 0
        assert value.strip() == "updateInstead"



class TestMigrateRemotes:
    def test_migrates_active_slot(self, tmp_path):
        family = tmp_path / "family"
        family.mkdir()
        original = init_repo_with_remote(family / "engine")

        slot_dir = family / "slots" / "1"
        slot_dir.mkdir(parents=True)
        clone = slot_dir / "engine"
        subprocess.run(["git", "clone", "--shared", str(original), str(clone)],
                       capture_output=True, check=True)
        (slot_dir / ".slot").write_text("# Slot 1\n## Repos\n- engine\n")

        count = slot_lifecycle.migrate_remotes(family)
        assert count > 0

        rc, _, _ = slot_core.run_cmd(
            ["git", "-C", str(clone), "remote", "get-url", "local"])
        assert rc == 0

        bare_path = family / ".engine-bare.git"
        rc, url, _ = slot_core.run_cmd(
            ["git", "-C", str(clone), "remote", "get-url", "origin"])
        assert rc == 0
        assert str(bare_path) in url.strip()

    def test_skips_archived_slots(self, tmp_path):
        family = tmp_path / "family"
        family.mkdir()
        original = init_repo_with_remote(family / "engine")

        attic = family / "slots" / "attic" / "1"
        attic.mkdir(parents=True)
        clone = attic / "engine"
        subprocess.run(["git", "clone", "--shared", str(original), str(clone)],
                       capture_output=True, check=True)

        count = slot_lifecycle.migrate_remotes(family)
        assert count == 0

    def test_idempotent(self, tmp_path):
        family = tmp_path / "family"
        family.mkdir()
        original = init_repo_with_remote(family / "engine")

        slot_dir = family / "slots" / "1"
        slot_dir.mkdir(parents=True)
        clone = slot_dir / "engine"
        subprocess.run(["git", "clone", "--shared", str(original), str(clone)],
                       capture_output=True, check=True)
        (slot_dir / ".slot").write_text("# Slot 1\n## Repos\n- engine\n")

        count1 = slot_lifecycle.migrate_remotes(family)
        count2 = slot_lifecycle.migrate_remotes(family)
        assert count1 > 0
        assert count2 == 0



class TestCreateSlotCollisionFamily:
    @patch("slot_lifecycle.run_cmd")
    def test_workspace_name_from_remote_avoids_family_collision(self, mock_cmd, tmp_path):
        """With per-repo workspace naming from remote URL, family repo names
        like 'work' cannot collide — workspace gets 'wsp-casehub-engine'."""
        family = tmp_path / "casehub"
        family.mkdir()
        engine = init_repo(family / "engine")
        init_repo(family / "work")
        ws_engine = init_repo(tmp_path / "public" / "casehub" / "engine")
        (engine / "wksp").symlink_to(ws_engine)

        mock_cmd.return_value = (0, "", "")

        with patch("slot_lifecycle.resolve_workspace_source") as mock_resolve:
            mock_resolve.return_value = (ws_engine, "wsp-casehub-engine")
            result = slot_lifecycle.create_slot(
                family_root=family,
                repos=["engine"],
                branch="issue-99-test",
                issue="99",
                issue_repo="casehubio/parent",
                covers="99",
                context="Test no collision",
            )

        slot_dir = family / "slots" / str(result["slot_number"])
        clone_dests = []
        for c in mock_cmd.call_args_list:
            args = c.args[0] if c.args else c[0]
            if isinstance(args, list) and len(args) >= 2 and args[0] == "git" and "clone" in args:
                dest = Path(args[-1])
                if dest.parent == slot_dir:
                    clone_dests.append(dest.name)
        assert "wsp-casehub-engine" in clone_dests



class TestCreateSlotWkspValidation:
    @patch("slot_lifecycle.validate_slot_wksp")
    @patch("slot_lifecycle.run_cmd")
    def test_create_slot_exits_on_broken_wksp(self, mock_cmd, mock_validate, tmp_path, capsys):
        """create_slot must fail if post-creation validation finds broken wksp/."""
        family = tmp_path / "casehub"
        family.mkdir()
        init_repo(family / "engine")

        mock_cmd.return_value = (0, "", "")
        mock_validate.return_value = ["engine: wksp/ symlink dangling -> /nonexistent"]

        with pytest.raises(slot_core.SlotCreationError, match="wksp_validation_failed"):
            slot_lifecycle.create_slot(
                family_root=family,
                repos=["engine"],
                branch="issue-99-test",
                issue="99",
                issue_repo="casehubio/engine",
                covers="99",
                context="test",
            )

    @patch("slot_lifecycle.validate_slot_wksp")
    @patch("slot_lifecycle.run_cmd")
    def test_create_slot_succeeds_when_wksp_ok(self, mock_cmd, mock_validate, tmp_path):
        """create_slot succeeds when validation passes."""
        family = tmp_path / "casehub"
        family.mkdir()
        init_repo(family / "engine")

        mock_cmd.return_value = (0, "", "")
        mock_validate.return_value = []

        result = slot_lifecycle.create_slot(
            family_root=family,
            repos=["engine"],
            branch="issue-99-test",
            issue="99",
            issue_repo="casehubio/engine",
            covers="99",
            context="test",
        )
        assert result["slot_number"] >= 1



class TestAddRepoWorkspaceRemotes:
    @patch("slot_lifecycle.configure_slot_remotes")
    @patch("slot_lifecycle.run_cmd")
    def test_add_repo_configures_workspace_remotes(self, mock_cmd, mock_configure, tmp_path):
        """add_repo must call configure_slot_remotes on new workspace clones."""
        family = tmp_path / "casehub"
        family.mkdir()
        slot_dir = family / "slots" / "1"
        slot_dir.mkdir(parents=True)
        init_repo(slot_dir / "engine")

        repo_b = init_repo(family / "iot")
        ws_iot = init_repo(tmp_path / "public" / "casehub" / "iot")
        (repo_b / "wksp").symlink_to(ws_iot)

        slot_metadata.write_slot_md(
            slot_dir, 1, ["engine"], "test-branch", "42",
            "Org/repo", "42", "test",
        )

        mock_cmd.return_value = (0, "", "")
        mock_configure.return_value = {"origin": "", "upstream": "", "local": ""}

        with patch("slot_lifecycle.resolve_workspace_source") as mock_resolve:
            mock_resolve.return_value = (ws_iot, "wsp-casehub-iot")
            slot_lifecycle.add_repo(family, 1, "iot", "test-branch")

        ws_calls = [
            c for c in mock_configure.call_args_list
            if "wsp-" in str(c.args[0])
        ]
        assert len(ws_calls) >= 1, (
            "add_repo did not call configure_slot_remotes on workspace clone"
        )



class TestCreateSlotDuplicateGuard:
    def _setup_db(self, tmp_path, monkeypatch):
        scripts_dir = Path(__file__).parent.parent / "scripts"
        sys.path.insert(0, str(scripts_dir))
        import worklog as _wl_mod
        db_path = tmp_path / "guard_test.db"
        monkeypatch.setattr(slot_lifecycle, "_wl", _wl_mod)
        monkeypatch.setattr(_wl_mod, "DEFAULT_DB", str(db_path))
        return _wl_mod

    def test_duplicate_branch_raises(self, tmp_path, monkeypatch):
        self._setup_db(tmp_path, monkeypatch)
        family = tmp_path / "family"
        family.mkdir()
        init_repo(family / "myrepo")
        existing = family / "slots" / "1"
        existing.mkdir(parents=True)
        (existing / ".slot").write_text("# Slot 1 — my-branch\n\n## Repos\n- myrepo\n")
        with pytest.raises(slot_core.SlotCreationError, match="already has branch"):
            slot_lifecycle.create_slot(family, ["myrepo"], "my-branch",
                                     issue="1", issue_repo="org/repo",
                                     covers="1", context="test")

    def test_duplicate_landed_branch_message(self, tmp_path, monkeypatch):
        self._setup_db(tmp_path, monkeypatch)
        family = tmp_path / "family"
        family.mkdir()
        init_repo(family / "myrepo")
        existing = family / "slots" / "1"
        existing.mkdir(parents=True)
        (existing / ".slot").write_text("# Slot 1 — my-branch\n\n## Repos\n- myrepo\n")
        (existing / ".landed").write_text("landed_shas=myrepo:abc\n")
        with pytest.raises(slot_core.SlotCreationError, match="landed.*Archive it"):
            slot_lifecycle.create_slot(family, ["myrepo"], "my-branch",
                                     issue="1", issue_repo="org/repo",
                                     covers="1", context="test")



class TestCreateSlotRollback:
    def _setup_db(self, tmp_path, monkeypatch):
        scripts_dir = Path(__file__).parent.parent / "scripts"
        sys.path.insert(0, str(scripts_dir))
        import worklog as _wl_mod
        db_path = tmp_path / "rollback_test.db"
        monkeypatch.setattr(slot_lifecycle, "_wl", _wl_mod)
        monkeypatch.setattr(_wl_mod, "DEFAULT_DB", str(db_path))
        return _wl_mod

    def test_clone_failure_cleans_up_dir(self, tmp_path, monkeypatch):
        _wl_mod = self._setup_db(tmp_path, monkeypatch)
        family = tmp_path / "family"
        family.mkdir()
        with pytest.raises(slot_core.SlotCreationError):
            slot_lifecycle.create_slot(family, ["nonexistent"], "test-branch",
                                     issue="1", issue_repo="org/repo",
                                     covers="1", context="test")
        slots_dir = family / "slots"
        remaining = [d for d in slots_dir.iterdir() if d.is_dir() and d.name.isdigit()] if slots_dir.exists() else []
        assert len(remaining) == 0

    def test_clone_failure_transitions_db_to_failed(self, tmp_path, monkeypatch):
        _wl_mod = self._setup_db(tmp_path, monkeypatch)
        family = tmp_path / "family"
        family.mkdir()
        with pytest.raises(slot_core.SlotCreationError):
            slot_lifecycle.create_slot(family, ["nonexistent"], "test-branch",
                                     issue="1", issue_repo="org/repo",
                                     covers="1", context="test")
        conn = _wl_mod.connect()
        row = conn.execute(
            "SELECT state FROM slots WHERE family_root=?",
            (_wl_mod._norm(str(family)),)
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["state"] == "failed"



class TestAllocateSlotReuse:
    def _setup_db(self, tmp_path, monkeypatch):
        scripts_dir = Path(__file__).parent.parent / "scripts"
        sys.path.insert(0, str(scripts_dir))
        import worklog as _wl_mod
        db_path = tmp_path / "reuse_test.db"
        monkeypatch.setattr(slot_lifecycle, "_wl", _wl_mod)
        monkeypatch.setattr(_wl_mod, "DEFAULT_DB", str(db_path))
        return _wl_mod

    def test_reuses_pending(self, tmp_path, monkeypatch, capsys):
        _wl_mod = self._setup_db(tmp_path, monkeypatch)
        conn = _wl_mod.connect()
        conn.execute(
            "INSERT INTO slots (slot_number, family_root, state, created_at) "
            "VALUES (5, ?, 'pending', '2026-01-01')",
            (_wl_mod._norm(str(tmp_path)),))
        conn.commit()
        conn.close()
        result = slot_lifecycle.allocate_slot_number(tmp_path)
        assert result == 5
        captured = capsys.readouterr()
        assert "REUSED_PENDING=5" in captured.out

    def test_reuses_failed(self, tmp_path, monkeypatch, capsys):
        _wl_mod = self._setup_db(tmp_path, monkeypatch)
        conn = _wl_mod.connect()
        conn.execute(
            "INSERT INTO slots (slot_number, family_root, state, created_at) "
            "VALUES (7, ?, 'failed', '2026-01-01')",
            (_wl_mod._norm(str(tmp_path)),))
        conn.commit()
        conn.close()
        result = slot_lifecycle.allocate_slot_number(tmp_path)
        assert result == 7

    def test_cleans_debris_on_reuse(self, tmp_path, monkeypatch):
        _wl_mod = self._setup_db(tmp_path, monkeypatch)
        conn = _wl_mod.connect()
        conn.execute(
            "INSERT INTO slots (slot_number, family_root, state, created_at) "
            "VALUES (3, ?, 'pending', '2026-01-01')",
            (_wl_mod._norm(str(tmp_path)),))
        conn.commit()
        conn.close()
        debris = tmp_path / "slots" / "3"
        debris.mkdir(parents=True)
        (debris / ".m2").mkdir()
        slot_lifecycle.allocate_slot_number(tmp_path)
        assert not debris.exists()

    def test_cleans_older_pending_slots(self, tmp_path, monkeypatch):
        _wl_mod = self._setup_db(tmp_path, monkeypatch)
        conn = _wl_mod.connect()
        for n in (1, 3, 5):
            conn.execute(
                "INSERT INTO slots (slot_number, family_root, state, created_at) "
                "VALUES (?, ?, 'pending', '2026-01-01')",
                (n, _wl_mod._norm(str(tmp_path))))
        conn.commit()
        conn.close()
        result = slot_lifecycle.allocate_slot_number(tmp_path)
        assert result == 5
        conn = _wl_mod.connect()
        states = {r["slot_number"]: r["state"] for r in conn.execute(
            "SELECT slot_number, state FROM slots WHERE family_root=?",
            (_wl_mod._norm(str(tmp_path)),)).fetchall()}
        conn.close()
        assert states[5] == "pending"
        assert states[1] == "failed"
        assert states[3] == "failed"

    def test_fresh_when_no_pending(self, tmp_path, monkeypatch):
        _wl_mod = self._setup_db(tmp_path, monkeypatch)
        conn = _wl_mod.connect()
        conn.execute(
            "INSERT INTO slots (slot_number, family_root, state, created_at) "
            "VALUES (10, ?, 'active', '2026-01-01')",
            (_wl_mod._norm(str(tmp_path)),))
        conn.commit()
        conn.close()
        result = slot_lifecycle.allocate_slot_number(tmp_path)
        assert result == 11



class TestCreateSlotInstallsHook:
    @patch("slot_lifecycle.run_cmd")
    def test_create_slot_installs_post_commit_hook(self, mock_cmd, tmp_path):
        """create_slot installs post-commit push hook in each repo clone."""
        family = tmp_path / "casehub"
        family.mkdir()
        init_repo(family / "engine")

        mock_cmd.return_value = (0, "", "")

        result = slot_lifecycle.create_slot(
            family_root=family,
            repos=["engine"],
            branch="issue-42-spi",
            issue="42",
            issue_repo="casehubio/engine",
            covers="42",
            context="Test hook install",
        )

        slot_dir = family / "slots" / str(result["slot_number"])
        hook = slot_dir / "engine" / ".git" / "hooks" / "post-commit"
        assert hook.exists()
        assert "git push" in hook.read_text()


def _create_merge_test_repos(tmp_path, repo_names):
    family = tmp_path / "family"
    family.mkdir()
    slots_dir = family / "slots"
    slots_dir.mkdir()

    originals = {}
    for name in repo_names:
        originals[name] = init_repo_with_remote(family / name)
        slot_git.configure_update_instead(originals[name])

    slot = slots_dir / "1"
    slot.mkdir()
    branch = "issue-42-test"

    for name in repo_names:
        clone_dest = slot / name
        bare_path = family / f".{name}-bare.git"
        subprocess.run([
            "git", "clone", "--shared", "--branch", "main",
            str(originals[name]), str(clone_dest),
        ], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(clone_dest), "config", "user.name", "Test"], capture_output=True)
        subprocess.run(["git", "-C", str(clone_dest), "config", "user.email", "test@test.com"], capture_output=True)
        subprocess.run(["git", "-C", str(clone_dest), "checkout", "-b", branch], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(clone_dest), "remote", "rename", "origin", "local"], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(clone_dest), "remote", "add", "origin", str(bare_path)], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(clone_dest), "fetch", "origin"], capture_output=True)
        (clone_dest / "feature.py").write_text(f"# {name} feature\n")
        subprocess.run(["git", "-C", str(clone_dest), "add", "."], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(clone_dest), "commit", "-m", f"feat: {name} feature"], capture_output=True, check=True)

    (slot / ".phase-a-complete").write_text(
        f"branch={branch}\nrepos={','.join(repo_names)}\ntimestamp=2026-07-18T14:32:00\n"
    )
    (slot / ".slot").write_text(
        f"# Slot 1 — {branch}\n\n## Issue\ntest/repo#42\nCovers: 42\n\n"
        f"## What to do\nTest\n\n## Repos\n" +
        "\n".join(f"- {n}" for n in repo_names) + "\n"
    )
    return family, originals, slot, branch



def _create_worktree_test_repos(tmp_path, repo_names):
    """Create a test family with worktree-based slots (legacy layout for migration tests)."""
    family = tmp_path / "family"
    family.mkdir()
    slots_dir = family / "slots"
    slots_dir.mkdir()

    originals = {}
    for name in repo_names:
        originals[name] = init_repo_with_remote(family / name)
        slot_git.configure_update_instead(originals[name])

    slot = slots_dir / "1"
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



def _create_clone_test_repos(tmp_path, repo_names):
    """Create a test family with clone-based slots (new remote layout)."""
    family = tmp_path / "family"
    family.mkdir()
    slots_dir = family / "slots"
    slots_dir.mkdir()

    originals = {}
    for name in repo_names:
        originals[name] = init_repo_with_remote(family / name)
        slot_git.configure_update_instead(originals[name])

    slot = slots_dir / "1"
    slot.mkdir()
    branch = "issue-42-test"

    for name in repo_names:
        clone_dest = slot / name
        bare_path = family / f".{name}-bare.git"
        subprocess.run([
            "git", "clone", "--shared", "--branch", "main",
            str(originals[name]), str(clone_dest),
        ], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(clone_dest), "config", "user.name", "Test"], capture_output=True)
        subprocess.run(["git", "-C", str(clone_dest), "config", "user.email", "test@test.com"], capture_output=True)
        subprocess.run(["git", "-C", str(clone_dest), "checkout", "-b", branch], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(clone_dest), "remote", "rename", "origin", "local"], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(clone_dest), "remote", "add", "origin", str(bare_path)], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(clone_dest), "fetch", "origin"], capture_output=True)
        (clone_dest / "feature.py").write_text(f"# {name} feature\n")
        subprocess.run(["git", "-C", str(clone_dest), "add", "."], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(clone_dest), "commit", "-m", f"feat: {name} feature"], capture_output=True, check=True)

    (slot / ".phase-a-complete").write_text(
        f"branch={branch}\nrepos={','.join(repo_names)}\ntimestamp=2026-07-18T14:32:00\n"
    )
    (slot / ".slot").write_text(
        f"# Slot 1 — {branch}\n\n## Issue\ntest/repo#42\nCovers: 42\n\n"
        f"## What to do\nTest\n\n## Repos\n" +
        "\n".join(f"- {n}" for n in repo_names) + "\n"
    )
    return family, originals, slot, branch



class TestFindActiveSessions:
    def test_returns_empty_for_inactive_dir(self, tmp_path):
        from slot_claude import find_active_sessions
        result = find_active_sessions(tmp_path)
        assert result == []

    def test_detects_process_in_dir(self, tmp_path):
        import time
        test_file = tmp_path / "hold.txt"
        test_file.write_text("hold")
        proc = subprocess.Popen(
            ["tail", "-f", str(test_file)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            time.sleep(0.5)
            from slot_claude import find_active_sessions
            result = find_active_sessions(tmp_path)
            pids = [r[0] for r in result]
            assert proc.pid in pids, f"Expected pid {proc.pid} in {pids}"
        finally:
            proc.terminate()
            proc.wait()


class TestArchiveSlotSessionGuard:
    def test_blocks_when_active_session(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(
            "slot_claude.find_active_sessions",
            lambda d: [(12345, "claude", str(d / "blocks"))],
        )
        monkeypatch.setattr("slot_lifecycle._has_unmerged_content", lambda d: [])
        monkeypatch.setattr("slot_lifecycle.ensure_clone_layout", lambda d: None)
        monkeypatch.setattr("slot_lifecycle.verify_landed_shas", lambda d, f: (True, []))
        slot_dir = tmp_path / "slots" / "99"
        slot_dir.mkdir(parents=True)
        (slot_dir / ".landed").write_text("landed_shas=abc:123\n")
        (slot_dir / ".slot").write_text("## Repos\n- blocks (primary)\n")
        repo = slot_dir / "blocks"
        repo.mkdir()
        (repo / ".git").mkdir()

        with pytest.raises(SystemExit) as exc_info:
            slot_lifecycle.archive_slot(tmp_path, 99, force=False)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "ERROR=active_sessions" in captured.out

    def test_force_overrides_active_session(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(
            "slot_claude.find_active_sessions",
            lambda d: [(12345, "claude", str(d / "blocks"))],
        )
        monkeypatch.setattr('slot_lifecycle._has_unmerged_content', lambda d: [])
        monkeypatch.setattr('slot_lifecycle.ensure_clone_layout', lambda d: None)
        monkeypatch.setattr('slot_lifecycle.verify_landed_shas', lambda d, f: (True, []))
        monkeypatch.setattr('slot_lifecycle._repack_broken_alternates', lambda d, f: 0)
        monkeypatch.setattr('slot_lifecycle._teardown_isx', lambda d: None)
        monkeypatch.setattr('slot_lifecycle.sweep_orphaned_claude_projects', lambda f: 0)
        monkeypatch.setattr('slot_lifecycle._escape_slot_cwd', lambda d, f: (False, None))
        monkeypatch.setattr('slot_lifecycle.relocate_claude_projects', lambda s, d: 0)

        slot_dir = tmp_path / "slots" / "99"
        slot_dir.mkdir(parents=True)
        (slot_dir / ".landed").write_text("landed_shas=abc:123\n")
        (slot_dir / ".slot").write_text("## Repos\n- blocks (primary)\n")
        repo = slot_dir / "blocks"
        repo.mkdir()
        (repo / ".git").mkdir()
        attic = tmp_path / "slots" / "attic"
        attic.mkdir(parents=True)

        slot_lifecycle.archive_slot(tmp_path, 99, force=True)
        captured = capsys.readouterr()
        assert "WARN=active_sessions_overridden" in captured.out
