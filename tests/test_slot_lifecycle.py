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
import slot_io
import slot_git
import slot_claude
import slot_isx
from slot_test_helpers import init_repo, init_repo_with_workspace, init_repo_with_remote, land_slot


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path_factory, monkeypatch):
    """Slot code looks up ~/claude/public/<family>/<repo> and ~/.claude/projects.
    Point home at an empty directory so no test reads or fetches a real repo."""
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))


@pytest.fixture(autouse=True)
def _no_stray_sessions(request, monkeypatch):
    """A git hook can leave a short-lived child process inside a test repo. Only the
    tests of session detection itself should see real processes."""
    if request.cls is not None and request.cls.__name__ in ("TestFindActiveSessions", "TestSessionSlotBoundary"):
        return
    monkeypatch.setattr("slot_claude.find_active_sessions", lambda d: [])


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
        init_repo_with_workspace(family / "engine")
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
        init_repo_with_workspace(family / "engine")
        mock_cmd.return_value = (0, "", "")
        with patch("shutil.which", return_value="/opt/homebrew/bin/isx"):
            result = slot_lifecycle.create_slot(
                family_root=family, repos=["engine"],
                branch="issue-42-fix", issue="42",
                issue_repo="Hortora/soredium", covers="42",
                context="test", isx=True, isx_template="tpl-java",
            )
        slot_dir = family / "slots" / str(result["slot_number"])
        info = slot_io.parse_slot(slot_dir)
        assert info.isolation_type == "isx"
        assert info.isx_template == "tpl-java"
        assert info.isx_instance == "issue-42-fix"

    @patch("slot_lifecycle.run_cmd")
    def test_create_non_isx_unchanged(self, mock_cmd, tmp_path):
        family = tmp_path / "casehub"
        family.mkdir()
        init_repo_with_workspace(family / "engine")
        mock_cmd.return_value = (0, "", "")
        result = slot_lifecycle.create_slot(
            family_root=family, repos=["engine"],
            branch="issue-42-fix", issue="42",
            issue_repo="Hortora/soredium", covers="42",
            context="test",
        )
        slot_dir = family / "slots" / str(result["slot_number"])
        info = slot_io.parse_slot(slot_dir)
        assert info.isolation_type == ""

    @patch("slot_lifecycle.run_cmd")
    def test_create_isx_slot_isx_branch_fails(self, mock_cmd, tmp_path, capsys):
        family = tmp_path / "casehub"
        family.mkdir()
        init_repo_with_workspace(family / "engine")
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
        slot_io.write_slot(
            slot_dir, slot_number=1, repos=["engine"], branch="test-branch",
            issue="42", issue_repo="Org/repo", covers="42", context="test",
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
        slot_io.write_slot(
            slot_dir, slot_number=1, repos=["engine"], branch="test-branch",
            issue="42", issue_repo="Org/repo", covers="42", context="test",
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
        slot_io.write_slot(
            slot_dir, slot_number=1, repos=["engine"], branch="test-branch",
            issue="42", issue_repo="Org/repo", covers="42", context="test",
            isolation_type="isx", isx_instance="test-inst",
            isx_template="tpl-java",
        )
        (slot_dir / ".landed").write_text("landed")
        with patch("slot_core.run_cmd", return_value=(0, "", "")):
            with patch("slot_lifecycle._teardown_isx") as mock_teardown:
                slot_lifecycle.remove_slot(family, 1)
                mock_teardown.assert_called_once()



class TestResolveCanonicalRepo:
    def test_resolves_worktree_to_canonical(self, tmp_path):
        family, canonicals, slot, _ = _create_worktree_test_repos(tmp_path, ["engine"])
        resolved = slot_core.resolve_canonical_repo(slot / "engine")
        assert resolved == canonicals["engine"]



class TestArchiveSlot:
    def test_moves_to_attic_after_verified_merge(self, tmp_path):
        family, canonicals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        land_slot(family, slot, branch)

        slot_lifecycle.archive_slot(family, 1)

        assert not (family / "slots" / "1").exists()
        attic_slot = family / "slots" / "attic" / "1"
        assert attic_slot.exists()
        assert (attic_slot / ".slot").exists()
        assert (attic_slot / ".landed").exists()

    def test_preserves_repos_in_attic(self, tmp_path):
        """Archived slot must retain repo directories — attic is the recovery safety net."""
        family, canonicals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        land_slot(family, slot, branch)

        assert (slot / "engine").is_dir()
        slot_lifecycle.archive_slot(family, 1)

        attic_slot = family / "slots" / "attic" / "1"
        assert (attic_slot / "engine").exists(), "repo deleted during archive — attic is useless without it"

    def test_blocks_archive_without_landed_marker(self, tmp_path, capsys):
        family, _, slot, _ = _create_merge_test_repos(tmp_path, ["engine"])
        subprocess.run(["git", "-C", str(slot / "engine"), "checkout", "main"], capture_output=True)
        subprocess.run(["git", "-C", str(slot / "engine"), "branch", "-D", "issue-42-test"], capture_output=True)

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
        subprocess.run(["git", "-C", str(slot / "engine"), "branch", "-D", "issue-42-test"], capture_output=True)
        (slot / ".landed").write_text(
            f"branch=issue-42-test\nrepos=engine\nlanded_shas=engine:{sha.strip()}\n"
        )

        with pytest.raises(SystemExit):
            slot_lifecycle.archive_slot(family, 1)
        captured = capsys.readouterr()
        assert "ERROR=sha_not_on_main" in captured.out

    def test_blocks_archive_with_unmerged_content(self, tmp_path, capsys):
        """Unmerged content blocks archive without force or verified SHAs."""
        family, _, slot, _ = _create_merge_test_repos(tmp_path, ["engine"])

        with pytest.raises(SystemExit):
            slot_lifecycle.archive_slot(family, 1)
        captured = capsys.readouterr()
        assert "ERROR=unmerged_content" in captured.out

    def test_force_bypasses_unmerged_content(self, tmp_path, capsys):
        """Force bypasses unmerged content check."""
        family, _, slot, _ = _create_merge_test_repos(tmp_path, ["engine"])

        slot_lifecycle.archive_slot(family, 1, force=True)

        captured = capsys.readouterr()
        assert "NOTE=unmerged_content_bypassed" in captured.out
        assert (family / "slots" / "attic" / "1").exists()

    def test_force_bypasses_all_checks(self, tmp_path):
        family, _, slot, _ = _create_merge_test_repos(tmp_path, ["engine"])
        subprocess.run(["git", "-C", str(slot / "engine"), "checkout", "main"], capture_output=True)

        slot_lifecycle.archive_slot(family, 1, force=True)

        assert not (family / "slots" / "1").exists()
        assert (family / "slots" / "attic" / "1").exists()

    def test_writes_pid_file_on_archive(self, tmp_path, monkeypatch):
        family, canonicals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        land_slot(family, slot, branch)

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
        family, canonicals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        land_slot(family, slot, branch)

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

    def test_blocks_when_occupant_pid_alive(self, tmp_path, capsys):
        """#362: archive must fail when .occupant-pid contains a live PID."""
        family = tmp_path / "family"
        slot_dir = family / "slots" / "1"
        slot_dir.mkdir(parents=True)
        (slot_dir / ".slot").write_text("## Repos\n- engine (primary)\n")
        (slot_dir / ".occupant-pid").write_text(str(os.getpid()))
        repo = slot_dir / "engine"
        repo.mkdir()
        (repo / ".git").mkdir()

        with pytest.raises(SystemExit):
            slot_lifecycle.archive_slot(family, 1)
        captured = capsys.readouterr()
        assert "ERROR=occupant_pid_alive" in captured.out
        assert str(os.getpid()) in captured.out

    def test_dead_occupant_pid_falls_through(self, tmp_path, capsys):
        """#362: dead .occupant-pid does not block — falls through to next check."""
        family = tmp_path / "family"
        slot_dir = family / "slots" / "1"
        slot_dir.mkdir(parents=True)
        (slot_dir / ".slot").write_text("## Repos\n- engine (primary)\n")
        (slot_dir / ".occupant-pid").write_text("99999999")
        repo = slot_dir / "engine"
        repo.mkdir()
        (repo / ".git").mkdir()

        with pytest.raises(SystemExit):
            slot_lifecycle.archive_slot(family, 1)
        captured = capsys.readouterr()
        assert "ERROR=occupant_pid_alive" not in captured.out

    def test_force_does_not_override_occupant_pid(self, tmp_path, monkeypatch, capsys):
        """#447: --force must not bypass the active PID guard."""
        family = tmp_path / "family"
        slot_dir = family / "slots" / "1"
        slot_dir.mkdir(parents=True)
        (family / "slots" / "attic").mkdir(parents=True)
        (slot_dir / ".slot").write_text("## Repos\n- engine (primary)\n\n## State\nstate: landed\n")
        (slot_dir / ".occupant-pid").write_text(str(os.getpid()))
        repo = slot_dir / "engine"
        repo.mkdir()
        subprocess.run(["git", "-C", str(repo), "init"], capture_output=True)
        (repo / "f.txt").write_text("x")
        subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"], capture_output=True)

        fake_home = tmp_path / "home"
        (fake_home / ".claude" / "projects").mkdir(parents=True)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

        with pytest.raises(SystemExit):
            slot_lifecycle.archive_slot(family, 1, force=True)
        captured = capsys.readouterr()
        assert "ERROR=occupant_pid_alive" in captured.out
        assert slot_dir.exists(), "Slot should NOT be archived when PID is alive"


class TestResolveCanonicalRepoClone:
    def test_resolves_clone_to_canonical(self, tmp_path):
        canonical = init_repo_with_remote(tmp_path / "canonical")
        clone = tmp_path / "clone"
        subprocess.run([
            "git", "clone", "--shared", str(canonical), str(clone),
        ], capture_output=True, check=True)
        resolved = slot_core.resolve_canonical_repo(clone)
        assert resolved == canonical.resolve()

    def test_resolves_worktree_to_canonical(self, tmp_path):
        family, canonicals, slot, _ = _create_worktree_test_repos(tmp_path, ["engine"])
        resolved = slot_core.resolve_canonical_repo(slot / "engine")
        assert resolved == canonicals["engine"]

    def test_fallback_returns_self(self, tmp_path):
        repo = init_repo(tmp_path / "standalone")
        resolved = slot_core.resolve_canonical_repo(repo)
        assert resolved == repo



class TestArchiveSlotDoubleArchive:
    def test_merges_when_attic_slot_already_exists(self, tmp_path, capsys):
        """archive_slot merges into existing attic entry — handles restore-then-rearchive."""
        family, canonicals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        land_slot(family, slot, branch)

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
        assert "ARCHIVED=1" in captured.out
        # New content merged into attic
        assert (attic / ".landed").read_text() == "re-landed"
        slot_content = (attic / ".slot").read_text()
        assert "restored" in slot_content
        assert "state: archived" in slot_content
        # Original slot dir removed
        assert not (family / "slots" / "1").exists()



class TestArchiveSlotCleanup:
    def test_cleans_remnant_after_move(self, tmp_path):
        """If shutil.move succeeds but source dir reappears, archive cleans it up."""
        family, canonicals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        land_slot(family, slot, branch)

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
        family, canonicals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        land_slot(family, slot, branch)

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
        family, canonicals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        land_slot(family, slot, branch)

        # No .artifacts-promoted stamp — promotion never ran
        slot_lifecycle.archive_slot(family, 1)

        captured = capsys.readouterr()
        assert "WARN=artifacts_not_promoted" in captured.out

    def test_no_warning_when_stamp_exists(self, tmp_path, capsys):
        """No warning when .artifacts-promoted stamp is present."""
        family, canonicals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        land_slot(family, slot, branch)

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



class TestArchiveSlotIdempotent:
    def test_already_archived_returns_success(self, tmp_path, capsys):
        """Calling archive on a slot already in attic returns success."""
        family = tmp_path / "family"
        (family / "slots" / "attic" / "1").mkdir(parents=True)
        (family / "slots" / "attic" / "1" / ".slot").write_text("state: archived\n")

        slot_lifecycle.archive_slot(family, 1)

        captured = capsys.readouterr()
        assert "NOTE=already_archived" in captured.out
        assert "ARCHIVED=1" in captured.out

    def test_not_found_and_not_in_attic_errors(self, tmp_path, capsys):
        """Slot not in slots/ or attic/ exits with error."""
        family = tmp_path / "family"
        (family / "slots").mkdir(parents=True)

        with pytest.raises(SystemExit):
            slot_lifecycle.archive_slot(family, 1)
        captured = capsys.readouterr()
        assert "ERROR=slot_not_found" in captured.out


class TestArchiveSlotStateConvergence:
    def test_converges_active_to_landed_when_landed_marker_exists(self, tmp_path, capsys):
        """State converges from active to landed when .landed file is present."""
        family, canonicals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        land_slot(family, slot, branch)

        slot_lifecycle.archive_slot(family, 1)

        captured = capsys.readouterr()
        assert "ARCHIVED=1" in captured.out
        attic = family / "slots" / "attic" / "1"
        assert attic.exists()
        slot_content = (attic / ".slot").read_text()
        assert "state: archived" in slot_content

    def test_converges_active_to_ready_when_phase_a_complete(self, tmp_path, capsys):
        """State converges from active to ready when .phase-a-complete exists."""
        family, _, slot, _ = _create_merge_test_repos(tmp_path, ["engine"])
        subprocess.run(["git", "-C", str(slot / "engine"), "checkout", "main"], capture_output=True)
        subprocess.run(["git", "-C", str(slot / "engine"), "branch", "-D", "issue-42-test"], capture_output=True)

        slot_lifecycle.archive_slot(family, 1, force=True)

        captured = capsys.readouterr()
        assert "STATE_CONVERGED=ready" in captured.out
        assert "ARCHIVED=1" in captured.out


class TestArchiveSlotTransitionBeforeMove:
    def test_slot_state_set_before_physical_move(self, tmp_path):
        """Slot .slot file has state: archived even if _transition would fail."""
        family, canonicals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        land_slot(family, slot, branch)

        slot_lifecycle.archive_slot(family, 1)

        attic_slot = family / "slots" / "attic" / "1"
        slot_content = (attic_slot / ".slot").read_text()
        assert "state: archived" in slot_content

    def test_state_rollback_on_move_failure(self, tmp_path, capsys):
        """If shutil.move fails, .slot state rolls back to prior value."""
        family, canonicals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        land_slot(family, slot, branch)

        def fail_move(src, dst):
            raise OSError("simulated move failure")

        with patch("slot_lifecycle.shutil.move", side_effect=fail_move):
            with pytest.raises(OSError, match="simulated move failure"):
                slot_lifecycle.archive_slot(family, 1)

        slot_content = (slot / ".slot").read_text()
        assert "state: landed" in slot_content


class TestArchiveSlotUnmergedBypass:
    def test_unmerged_bypassed_when_shas_verified(self, tmp_path, capsys):
        """Unmerged content is bypassed when .landed SHAs are verified on main."""
        family, canonicals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        land_slot(family, slot, branch)

        subprocess.run(["git", "-C", str(slot / "engine"), "checkout", "-b", "leftover-branch"], capture_output=True)
        (slot / "engine" / "leftover.txt").write_text("extra")
        subprocess.run(["git", "-C", str(slot / "engine"), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(slot / "engine"), "commit", "-m", "extra"], capture_output=True)
        subprocess.run(["git", "-C", str(slot / "engine"), "checkout", "main"], capture_output=True)

        slot_lifecycle.archive_slot(family, 1)

        captured = capsys.readouterr()
        assert "NOTE=unmerged_content_bypassed" in captured.out
        assert "shas_verified" in captured.out
        assert "ARCHIVED=1" in captured.out

    def test_unmerged_blocks_without_shas_or_force(self, tmp_path, capsys):
        """Unmerged content blocks when no .landed SHAs and no force."""
        family, _, slot, _ = _create_merge_test_repos(tmp_path, ["engine"])

        with pytest.raises(SystemExit):
            slot_lifecycle.archive_slot(family, 1)
        captured = capsys.readouterr()
        assert "ERROR=unmerged_content" in captured.out


class TestVerifyLandedShasWorkspace:
    def test_resolves_workspace_via_local_remote(self, tmp_path):
        """verify_landed_shas finds workspace repos via git remote get-url local."""
        family = tmp_path / "family"
        family.mkdir()

        ws_orig = init_repo_with_remote(tmp_path / "workspace-repo")
        rc, sha, _ = slot_core.run_cmd(["git", "-C", str(ws_orig), "rev-parse", "HEAD"])
        sha = sha.strip()

        slot = family / "slots" / "1"
        slot.mkdir(parents=True)

        ws_clone = slot / "workspace-repo"
        subprocess.run(["git", "clone", "--shared", str(ws_orig), str(ws_clone)], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(ws_clone), "remote", "rename", "origin", "local"], capture_output=True, check=True)

        (slot / ".landed").write_text(f"branch=test\nrepos=workspace-repo\nlanded_shas=workspace-repo:{sha}\n")

        verified, failures = slot_metadata.verify_landed_shas(slot, family)
        assert verified, f"Expected verified but got failures: {failures}"

    def test_fails_when_no_local_remote_and_not_in_family(self, tmp_path):
        """verify_landed_shas fails for unknown repos not resolvable via local remote."""
        family = tmp_path / "family"
        family.mkdir()
        slot = family / "slots" / "1"
        slot.mkdir(parents=True)

        (slot / ".landed").write_text("branch=test\nrepos=ghost-repo\nlanded_shas=ghost-repo:abc123\n")

        verified, failures = slot_metadata.verify_landed_shas(slot, family)
        assert not verified
        assert any("not found" in f for f in failures)


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

        # #515 stage 2: the clone's only remote is its canonical repo.
        rc, names, _ = slot_core.run_cmd(["git", "-C", str(clone), "remote"])
        assert names.split() == ["local"]

        rc, value, _ = slot_core.run_cmd(
            ["git", "-C", str(repo), "config", "receive.denyCurrentBranch"])
        assert rc == 0
        assert value.strip() == "updateInstead"



class TestMigrateRemotes:
    def test_migrates_active_slot(self, tmp_path):
        family = tmp_path / "family"
        family.mkdir()
        canonical = init_repo_with_remote(family / "engine")

        slot_dir = family / "slots" / "1"
        slot_dir.mkdir(parents=True)
        clone = slot_dir / "engine"
        subprocess.run(["git", "clone", "--shared", str(canonical), str(clone)],
                       capture_output=True, check=True)
        (slot_dir / ".slot").write_text("# Slot 1\n## Repos\n- engine\n")

        count = slot_lifecycle.migrate_remotes(family)
        assert count > 0

        rc, _, _ = slot_core.run_cmd(
            ["git", "-C", str(clone), "remote", "get-url", "local"])
        assert rc == 0

        rc, url, _ = slot_core.run_cmd(
            ["git", "-C", str(clone), "remote", "get-url", "local"])
        assert Path(url.strip()).resolve() == canonical.resolve()
        rc, names, _ = slot_core.run_cmd(["git", "-C", str(clone), "remote"])
        assert names.split() == ["local"]      # no GitHub remote is added

    def test_skips_archived_slots(self, tmp_path):
        family = tmp_path / "family"
        family.mkdir()
        canonical = init_repo_with_remote(family / "engine")

        attic = family / "slots" / "attic" / "1"
        attic.mkdir(parents=True)
        clone = attic / "engine"
        subprocess.run(["git", "clone", "--shared", str(canonical), str(clone)],
                       capture_output=True, check=True)

        count = slot_lifecycle.migrate_remotes(family)
        assert count == 0

    def test_idempotent(self, tmp_path):
        family = tmp_path / "family"
        family.mkdir()
        canonical = init_repo_with_remote(family / "engine")

        slot_dir = family / "slots" / "1"
        slot_dir.mkdir(parents=True)
        clone = slot_dir / "engine"
        subprocess.run(["git", "clone", "--shared", str(canonical), str(clone)],
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
    def test_create_slot_warns_on_broken_wksp(self, mock_cmd, mock_validate, tmp_path, capsys):
        """Post-creation validation warns and never destroys the slot it just built."""
        family = tmp_path / "casehub"
        init_repo_with_workspace(family / "engine")

        mock_cmd.return_value = (0, "", "")
        mock_validate.return_value = ["engine: wksp/ symlink dangling -> /nonexistent"]

        result = slot_lifecycle.create_slot(
            family_root=family,
            repos=["engine"],
            branch="issue-99-test",
            issue="99",
            issue_repo="casehubio/engine",
            covers="99",
            context="test",
        )

        out = capsys.readouterr().out
        assert "WARN=wksp_validation engine: wksp/ symlink dangling" in out
        assert (family / "slots" / str(result["slot_number"])).is_dir()
        assert "claude/public" not in out, "must not discover a real workspace"

    @patch("slot_lifecycle.validate_slot_wksp")
    @patch("slot_lifecycle.run_cmd")
    def test_create_slot_succeeds_when_wksp_ok(self, mock_cmd, mock_validate, tmp_path):
        """create_slot succeeds when validation passes."""
        family = tmp_path / "casehub"
        init_repo_with_workspace(family / "engine")

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

        slot_io.write_slot(
            slot_dir, slot_number=1, repos=["engine"], branch="test-branch",
            issue="42", issue_repo="Org/repo", covers="42", context="test",
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



class TestCreateSlotClosedCovers:
    """#363: create_slot should warn when covers includes closed issues."""

    @patch("slot_lifecycle.run_cmd")
    def test_warns_on_closed_covers(self, mock_cmd, tmp_path, monkeypatch, capsys):
        family = tmp_path / "casehub"
        family.mkdir()
        engine = init_repo(family / "engine")
        ws_engine = init_repo(tmp_path / "public" / "casehub" / "engine")
        (engine / "wksp").symlink_to(ws_engine)

        mock_cmd.return_value = (0, "", "")
        monkeypatch.setattr("plan_manager._check_issue_state", lambda repo, num: "CLOSED")

        with patch("slot_lifecycle.resolve_workspace_source") as mock_resolve:
            mock_resolve.return_value = (ws_engine, "wsp-casehub-engine")
            result = slot_lifecycle.create_slot(
                family_root=family,
                repos=["engine"],
                branch="issue-99-test",
                issue="99",
                issue_repo="casehubio/engine",
                covers="99,100",
                context="Test closed covers",
            )
        captured = capsys.readouterr()
        assert "WARN=" in captured.out and "closed" in captured.out.lower()
        assert result["slot_number"] == 1


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
        """create_slot installs the post-commit backup hook in each repo clone."""
        family = tmp_path / "casehub"
        family.mkdir()
        init_repo_with_workspace(family / "engine")

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
        assert "canonical_sync.py" in hook.read_text()
        assert "git push" not in hook.read_text()


def _create_merge_test_repos(tmp_path, repo_names):
    family = tmp_path / "family"
    family.mkdir()
    slots_dir = family / "slots"
    slots_dir.mkdir()

    canonicals = {}
    for name in repo_names:
        canonicals[name] = init_repo_with_remote(family / name)
        slot_git.configure_update_instead(canonicals[name])

    slot = slots_dir / "1"
    slot.mkdir()
    branch = "issue-42-test"

    for name in repo_names:
        clone_dest = slot / name
        bare_path = family / f".{name}-bare.git"
        subprocess.run([
            "git", "clone", "--shared", "--branch", "main",
            str(canonicals[name]), str(clone_dest),
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
    return family, canonicals, slot, branch



def _create_worktree_test_repos(tmp_path, repo_names):
    """Create a test family with worktree-based slots (legacy layout for migration tests)."""
    family = tmp_path / "family"
    family.mkdir()
    slots_dir = family / "slots"
    slots_dir.mkdir()

    canonicals = {}
    for name in repo_names:
        canonicals[name] = init_repo_with_remote(family / name)
        slot_git.configure_update_instead(canonicals[name])

    slot = slots_dir / "1"
    slot.mkdir()
    branch = "issue-42-test"

    for name in repo_names:
        subprocess.run([
            "git", "-C", str(canonicals[name]),
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
    return family, canonicals, slot, branch



def _create_clone_test_repos(tmp_path, repo_names):
    """Create a test family with clone-based slots (new remote layout)."""
    family = tmp_path / "family"
    family.mkdir()
    slots_dir = family / "slots"
    slots_dir.mkdir()

    canonicals = {}
    for name in repo_names:
        canonicals[name] = init_repo_with_remote(family / name)
        slot_git.configure_update_instead(canonicals[name])

    slot = slots_dir / "1"
    slot.mkdir()
    branch = "issue-42-test"

    for name in repo_names:
        clone_dest = slot / name
        bare_path = family / f".{name}-bare.git"
        subprocess.run([
            "git", "clone", "--shared", "--branch", "main",
            str(canonicals[name]), str(clone_dest),
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
    return family, canonicals, slot, branch



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

    def _slot(self, tmp_path, monkeypatch, cmd):
        monkeypatch.setattr(
            "slot_claude.find_active_sessions",
            lambda d: [(12345, cmd, str(d / "blocks"))],
        )
        monkeypatch.setattr("slot_lifecycle._has_unmerged_content", lambda d: [])
        monkeypatch.setattr("slot_lifecycle.verify_landed_shas", lambda d, f: (True, []))
        monkeypatch.setattr("slot_lifecycle._repack_broken_alternates", lambda d, f: 0)
        monkeypatch.setattr("slot_lifecycle._teardown_isx", lambda d: None)
        monkeypatch.setattr("slot_lifecycle.sweep_orphaned_claude_projects", lambda f: 0)
        monkeypatch.setattr("slot_lifecycle._escape_slot_cwd", lambda d, f: (False, None))
        monkeypatch.setattr("slot_lifecycle.relocate_claude_projects", lambda s, d: 0)
        slot_dir = tmp_path / "slots" / "99"
        slot_dir.mkdir(parents=True)
        (slot_dir / ".landed").write_text("landed_shas=abc:123\n")
        (slot_dir / ".slot").write_text("## Repos\n- blocks (primary)\n")
        repo = slot_dir / "blocks"
        repo.mkdir()
        (repo / ".git").mkdir()
        (tmp_path / "slots" / "attic").mkdir(parents=True)
        return slot_dir

    def test_blocks_when_active_session(self, tmp_path, monkeypatch, capsys):
        slot_dir = self._slot(tmp_path, monkeypatch, "node")

        with pytest.raises(SystemExit) as exc_info:
            slot_lifecycle.archive_slot(tmp_path, 99, force=False)

        assert exc_info.value.code == 1
        assert "ERROR=active_sessions" in capsys.readouterr().out
        assert slot_dir.exists()

    def test_force_overrides_active_session(self, tmp_path, monkeypatch, capsys):
        self._slot(tmp_path, monkeypatch, "node")

        slot_lifecycle.archive_slot(tmp_path, 99, force=True)

        assert "WARN=active_sessions_overridden" in capsys.readouterr().out

    @pytest.mark.parametrize("force", [False, True])
    @pytest.mark.parametrize("cmd", ["claude", "2.1.325"])
    def test_claude_session_is_a_hard_stop_even_with_force(
            self, tmp_path, monkeypatch, capsys, cmd, force):
        slot_dir = self._slot(tmp_path, monkeypatch, cmd)

        with pytest.raises(SystemExit) as exc_info:
            slot_lifecycle.archive_slot(tmp_path, 99, force=force)

        assert exc_info.value.code == 1
        out = capsys.readouterr().out
        assert "ERROR=active_claude_sessions" in out
        assert "active_sessions_overridden" not in out
        assert slot_dir.exists(), "slot must not be moved while a Claude session is running"
        assert not (tmp_path / "slots" / "attic" / "99").exists()


class TestIsClaudeSession:

    @pytest.mark.parametrize("cmd", ["claude", "Claude", "claude-code", "2.1.325", "10.0.1"])
    def test_recognises_claude_code(self, cmd):
        assert slot_claude.is_claude_session(cmd)

    @pytest.mark.parametrize("cmd", ["node", "zsh", "python3.14", "git", "", "claudette", "2.1", "v2.1.325"])
    def test_ignores_other_processes(self, cmd):
        assert not slot_claude.is_claude_session(cmd)


class TestRestoreSlot:

    def test_restores_from_attic_and_marks_active(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr("slot_lifecycle.relocate_claude_projects", lambda s, d: 0)
        transitions = []
        monkeypatch.setattr("slot_lifecycle._transition",
                            lambda d, state, **kw: transitions.append((d, state)))
        attic = tmp_path / "slots" / "attic" / "7"
        attic.mkdir(parents=True)
        (attic / ".slot").write_text("## Repos\n- engine (primary)\n")
        (attic / "engine").mkdir()
        (attic / "engine" / "kept.txt").write_text("work")

        slot_lifecycle.restore_slot(tmp_path, 7)

        dest = tmp_path / "slots" / "7"
        assert (dest / "engine" / "kept.txt").read_text() == "work"
        assert not attic.exists()
        assert transitions == [(dest, "active")]
        assert "RESTORED=7" in capsys.readouterr().out

    def test_refuses_to_restore_over_an_active_slot(self, tmp_path, capsys):
        (tmp_path / "slots" / "attic" / "7").mkdir(parents=True)
        (tmp_path / "slots" / "7").mkdir(parents=True)

        with pytest.raises(SystemExit):
            slot_lifecycle.restore_slot(tmp_path, 7)

        assert "ERROR=active_slot_exists" in capsys.readouterr().out
        assert (tmp_path / "slots" / "attic" / "7").exists()


class TestPostCreationChecksSoftFail:
    """Refs #347, #348: validation failures after slot construction must warn, not destroy."""

    @patch("slot_lifecycle.run_cmd")
    def test_validation_failure_preserves_slot(self, mock_cmd, tmp_path, capsys):
        """When _run_post_creation_checks raises, the slot directory must survive."""
        family = tmp_path / "casehub"
        family.mkdir()
        engine = init_repo(family / "engine")
        ws_engine = init_repo(tmp_path / "public" / "casehub" / "engine")
        (engine / "wksp").symlink_to(ws_engine)

        mock_cmd.return_value = (0, "", "")

        with patch("slot_lifecycle.resolve_workspace_source") as mock_resolve, \
             patch("slot_lifecycle.validate_slot_wksp", side_effect=RuntimeError("boom")):
            mock_resolve.return_value = (ws_engine, "wsp-casehub-engine")
            result = slot_lifecycle.create_slot(
                family_root=family,
                repos=["engine"],
                branch="issue-99-test",
                issue="99",
                issue_repo="casehubio/engine",
                covers="99",
                context="validation test",
            )

        slot_dir = family / "slots" / str(result["slot_number"])
        assert slot_dir.is_dir(), "Slot directory was destroyed by validation failure"
        assert (slot_dir / ".slot").exists()
        captured = capsys.readouterr()
        assert "WARN=wksp_validation_error" in captured.out

    @patch("slot_lifecycle.run_cmd")
    def test_missing_verification_module_warns(self, mock_cmd, tmp_path, capsys):
        """Missing verification module prints warning, doesn't crash."""
        family = tmp_path / "casehub"
        family.mkdir()
        engine = init_repo(family / "engine")
        ws_engine = init_repo(tmp_path / "public" / "casehub" / "engine")
        (engine / "wksp").symlink_to(ws_engine)

        mock_cmd.return_value = (0, "", "")

        orig_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

        def mock_import(name, *args, **kwargs):
            if name == "verification.postconditions":
                raise ImportError("No module named 'verification.postconditions'")
            return orig_import(name, *args, **kwargs)

        with patch("slot_lifecycle.resolve_workspace_source") as mock_resolve, \
             patch("builtins.__import__", side_effect=mock_import):
            mock_resolve.return_value = (ws_engine, "wsp-casehub-engine")
            result = slot_lifecycle.create_slot(
                family_root=family,
                repos=["engine"],
                branch="issue-98-test",
                issue="98",
                issue_repo="casehubio/engine",
                covers="98",
                context="import test",
            )

        slot_dir = family / "slots" / str(result["slot_number"])
        assert slot_dir.is_dir(), "Slot destroyed by missing verification module"
        captured = capsys.readouterr()
        assert "WARN=verification_module_unavailable" in captured.out

    @patch("slot_git.run_cmd")
    @patch("slot_lifecycle.run_cmd")
    def test_construction_failure_still_cleans_up(self, mock_cmd, mock_git_cmd, tmp_path):
        """Clone failures (construction phase) must still destroy the slot."""
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
                    branch="issue-97-test",
                    issue="97",
                    issue_repo="casehubio/engine",
                    covers="97",
                    context="clone fail test",
                )

        slots_dir = family / "slots"
        slot_dirs = list(slots_dir.iterdir()) if slots_dir.exists() else []
        for d in slot_dirs:
            assert not d.is_dir() or d.name == "attic", \
                f"Slot dir {d} should have been cleaned up after construction failure"


class TestRunPostCreationChecks:
    """Unit tests for _run_post_creation_checks in isolation."""

    def test_wksp_validation_warns(self, tmp_path, capsys):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        with patch("slot_lifecycle.validate_slot_wksp", return_value=["missing .workspace marker"]):
            slot_lifecycle._run_post_creation_checks(slot_dir)
        captured = capsys.readouterr()
        assert "WARN=wksp_validation missing .workspace marker" in captured.out

    def test_wksp_validation_exception_caught(self, tmp_path, capsys):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        with patch("slot_lifecycle.validate_slot_wksp", side_effect=OSError("permission denied")):
            slot_lifecycle._run_post_creation_checks(slot_dir)
        captured = capsys.readouterr()
        assert "WARN=wksp_validation_error" in captured.out

    def test_postcondition_import_error_caught(self, tmp_path, capsys):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        with patch("slot_lifecycle.validate_slot_wksp", return_value=[]), \
             patch("builtins.__import__", side_effect=ImportError("no verification")):
            slot_lifecycle._run_post_creation_checks(slot_dir)
        captured = capsys.readouterr()
        assert "WARN=verification_module_unavailable" in captured.out


class TestBuildEpicPlanCrossRepo:
    """Refs #349: _build_epic_plan must use per-issue repos for cross-repo covers."""

    @patch("slot_lifecycle.run_cmd")
    def test_qualified_cover_refs_use_own_repo(self, mock_cmd):
        from plan_io import CoverRef

        mock_cmd.side_effect = [
            (0, "Platform fix\n", ""),
            (0, "Engine update\n", ""),
        ]

        result = slot_lifecycle._build_epic_plan(
            branch="issue-100-epic",
            issue_repo="casehubio/parent",
            cover_refs=[
                CoverRef(number=276, repo="casehubio/platform"),
                CoverRef(number=1049, repo="casehubio/engine"),
            ],
            date="2026-09-07",
        )

        assert result is not None
        gh_calls = [c.args[0] for c in mock_cmd.call_args_list]
        assert any("casehubio/platform" in str(c) for c in gh_calls), \
            f"Expected gh call with casehubio/platform, got {gh_calls}"
        assert any("casehubio/engine" in str(c) for c in gh_calls), \
            f"Expected gh call with casehubio/engine, got {gh_calls}"
        assert not any("casehubio/parent" in str(c) for c in gh_calls), \
            "Should NOT use parent epic's repo for cross-repo children"

    @patch("slot_lifecycle.run_cmd")
    def test_bare_cover_refs_fall_back_to_parent_repo(self, mock_cmd):
        from plan_io import CoverRef

        mock_cmd.side_effect = [
            (0, "Fix A\n", ""),
            (0, "Fix B\n", ""),
        ]

        result = slot_lifecycle._build_epic_plan(
            branch="issue-200-epic",
            issue_repo="casehubio/engine",
            cover_refs=[
                CoverRef(number=42),
                CoverRef(number=43),
            ],
            date="2026-09-07",
        )

        assert result is not None
        gh_calls = [c.args[0] for c in mock_cmd.call_args_list]
        assert all("casehubio/engine" in str(c) for c in gh_calls), \
            f"Bare refs should use parent repo, got {gh_calls}"

    @patch("slot_lifecycle.run_cmd")
    def test_legacy_string_refs_still_work(self, mock_cmd):
        mock_cmd.side_effect = [
            (0, "Fix A\n", ""),
            (0, "Fix B\n", ""),
        ]

        result = slot_lifecycle._build_epic_plan(
            branch="issue-300-epic",
            issue_repo="casehubio/engine",
            cover_refs=["42", "43"],
            date="2026-09-07",
        )

        assert result is not None
        gh_calls = [c.args[0] for c in mock_cmd.call_args_list]
        assert all("casehubio/engine" in str(c) for c in gh_calls)


class TestStripInheritedLifecycle:
    """Refs #356: workspace clones must not inherit lifecycle files from main."""

    def test_strips_plan_file(self, tmp_path):
        ws = tmp_path / "wsp"
        ws.mkdir()
        (ws / ".git").mkdir()
        (ws / ".plan").write_text("# Plan\n## State\nstate: active\n")
        stripped = slot_lifecycle._strip_inherited_lifecycle(ws)
        assert ".plan" in stripped
        assert not (ws / ".plan").exists()

    def test_strips_journal(self, tmp_path):
        ws = tmp_path / "wsp"
        ws.mkdir()
        (ws / ".git").mkdir()
        (ws / "JOURNAL.md").write_text("# Journal\n")
        stripped = slot_lifecycle._strip_inherited_lifecycle(ws)
        assert "JOURNAL.md" in stripped
        assert not (ws / "JOURNAL.md").exists()

    def test_strips_meta(self, tmp_path):
        ws = tmp_path / "wsp"
        ws.mkdir()
        (ws / ".git").mkdir()
        (ws / ".meta").write_text("meta content\n")
        stripped = slot_lifecycle._strip_inherited_lifecycle(ws)
        assert ".meta" in stripped

    def test_strips_handoff_variants(self, tmp_path):
        ws = tmp_path / "wsp"
        ws.mkdir()
        (ws / ".git").mkdir()
        (ws / "HANDOFF.md").write_text("# Handoff\n")
        (ws / "HANDOFF-2026-09-07.md").write_text("# Old handoff\n")
        stripped = slot_lifecycle._strip_inherited_lifecycle(ws)
        assert "HANDOFF.md" in stripped
        assert "HANDOFF-2026-09-07.md" in stripped
        assert not (ws / "HANDOFF.md").exists()
        assert not (ws / "HANDOFF-2026-09-07.md").exists()

    def test_no_lifecycle_files_returns_empty(self, tmp_path):
        ws = tmp_path / "wsp"
        ws.mkdir()
        (ws / ".git").mkdir()
        (ws / "README.md").write_text("# Readme\n")
        stripped = slot_lifecycle._strip_inherited_lifecycle(ws)
        assert stripped == []

    def test_preserves_non_lifecycle_files(self, tmp_path):
        ws = tmp_path / "wsp"
        ws.mkdir()
        (ws / ".git").mkdir()
        (ws / "README.md").write_text("# Readme\n")
        (ws / ".plan").write_text("stale\n")
        slot_lifecycle._strip_inherited_lifecycle(ws)
        assert (ws / "README.md").exists()
        assert (ws / "README.md").read_text() == "# Readme\n"

    def test_scaffold_plan_survives_strip(self, tmp_path):
        """Simulates the full sequence: stale .plan stripped, then scaffold writes fresh .plan."""
        ws = tmp_path / "wsp"
        ws.mkdir()
        (ws / ".git").mkdir()
        (ws / ".plan").write_text("# Work Plan — old-issue\n\n## State\nstate: drained\n")
        (ws / "HANDOFF.md").write_text("# Old handoff\n")

        stripped = slot_lifecycle._strip_inherited_lifecycle(ws)
        assert ".plan" in stripped
        assert not (ws / ".plan").exists()

        fresh_plan = "# Work Plan — issue-304\n\n## State\nbranch: issue-304-new\nstate: active\ncovers: 304\n\n## Queue\n- [ ] org/repo#304 — New work\n"
        (ws / ".plan").write_text(fresh_plan)

        assert (ws / ".plan").exists()
        content = (ws / ".plan").read_text()
        assert "issue-304-new" in content
        assert "old-issue" not in content

    @patch("slot_lifecycle.run_cmd")
    def test_create_slot_strips_before_scaffold(self, mock_cmd, tmp_path):
        """In create_slot, _strip_inherited_lifecycle must run before scaffold.py."""
        family = tmp_path / "casehub"
        family.mkdir()
        engine = init_repo(family / "engine")
        ws_engine = init_repo(tmp_path / "public" / "casehub" / "engine")
        (ws_engine / ".plan").write_text("stale plan from prior work\n")
        subprocess.run(["git", "-C", str(ws_engine), "add", ".plan"], capture_output=True)
        subprocess.run(["git", "-C", str(ws_engine), "commit", "-m", "stale plan"], capture_output=True)
        (engine / "wksp").symlink_to(ws_engine)

        mock_cmd.return_value = (0, "", "")

        with patch("slot_lifecycle.resolve_workspace_source") as mock_resolve:
            mock_resolve.return_value = (ws_engine, "wsp-casehub-engine")
            result = slot_lifecycle.create_slot(
                family_root=family,
                repos=["engine"],
                branch="issue-304-new",
                issue="304",
                issue_repo="casehubio/engine",
                covers="304",
                context="Fresh work",
            )

        slot_dir = family / "slots" / str(result["slot_number"])
        ws_clone = slot_dir / "wsp-casehub-engine"
        assert not (ws_clone / ".plan").exists() or "stale" not in (ws_clone / ".plan").read_text(), \
            "Stale .plan from main survived into slot workspace clone"


class TestProcessArchiveRequests:
    """process_archive_requests processes .archive-requested markers."""

    def test_archives_slot_with_marker_and_no_sessions(self, tmp_path, monkeypatch):
        monkeypatch.setattr("slot_claude.find_active_sessions", lambda d: [])
        monkeypatch.setattr("slot_claude.check_occupant_pid", lambda d: (False, None))
        monkeypatch.setattr("slot_lifecycle._has_unmerged_content", lambda d: [])
        monkeypatch.setattr("slot_lifecycle.verify_landed_shas", lambda d, f: (True, []))
        monkeypatch.setattr("slot_lifecycle._repack_broken_alternates", lambda d, f: 0)
        monkeypatch.setattr("slot_lifecycle._teardown_isx", lambda d: None)
        monkeypatch.setattr("slot_lifecycle.sweep_orphaned_claude_projects", lambda f: 0)
        monkeypatch.setattr("slot_lifecycle._escape_slot_cwd", lambda d, f: (False, None))
        monkeypatch.setattr("slot_lifecycle.relocate_claude_projects", lambda s, d: 0)

        slot_dir = tmp_path / "slots" / "50"
        slot_dir.mkdir(parents=True)
        (slot_dir / ".landed").write_text("landed_shas=abc:123\n")
        (slot_dir / ".slot").write_text("## Repos\n- blocks (primary)\n\n## State\nstate: landed\n")
        (slot_dir / ".archive-requested").write_text("requested_by=test\n")
        repo = slot_dir / "blocks"
        repo.mkdir()
        (repo / ".git").mkdir()

        results = slot_lifecycle.process_archive_requests(tmp_path)
        assert len(results) == 1
        assert results[0]["slot"] == 50
        assert results[0]["action"] == "archived"
        assert not slot_dir.exists()
        assert (tmp_path / "slots" / "attic" / "50").is_dir()

    def test_defers_when_active_session(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "slot_claude.find_active_sessions",
            lambda d: [(99999, "claude", str(d))],
        )
        monkeypatch.setattr("slot_claude.check_occupant_pid", lambda d: (False, None))

        slot_dir = tmp_path / "slots" / "51"
        slot_dir.mkdir(parents=True)
        (slot_dir / ".archive-requested").write_text("requested_by=test\n")

        results = slot_lifecycle.process_archive_requests(tmp_path)
        assert len(results) == 1
        assert results[0]["action"] == "deferred"
        assert slot_dir.exists()
        assert (slot_dir / ".archive-requested").exists()

    def test_skips_slots_without_marker(self, tmp_path, monkeypatch):
        slot_dir = tmp_path / "slots" / "52"
        slot_dir.mkdir(parents=True)
        (slot_dir / ".slot").write_text("test\n")

        results = slot_lifecycle.process_archive_requests(tmp_path)
        assert len(results) == 0

    def test_defers_when_occupant_pid_alive(self, tmp_path, monkeypatch):
        monkeypatch.setattr("slot_claude.check_occupant_pid", lambda d: (True, 12345))

        slot_dir = tmp_path / "slots" / "53"
        slot_dir.mkdir(parents=True)
        (slot_dir / ".archive-requested").write_text("requested_by=test\n")

        results = slot_lifecycle.process_archive_requests(tmp_path)
        assert len(results) == 1
        assert results[0]["action"] == "deferred"
        assert "12345" in results[0]["reason"]


# --- #521: archive purges build outputs; session detection respects slot boundaries ---

def _maven_module(path: Path, built: bool = True) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "pom.xml").write_text("<project/>")
    if built:
        (path / "target" / "classes").mkdir(parents=True)
        (path / "target" / "classes" / "A.class").write_bytes(b"x" * 100)
    return path


class TestPurgeBuildOutputs:

    def test_removes_slot_m2_and_maven_targets_at_any_depth(self, tmp_path):
        slot = tmp_path / "slots" / "5"
        repo = init_repo(slot / "engine")
        _maven_module(repo)
        _maven_module(repo / "modules" / "core")
        (slot / ".m2" / "repository" / "g").mkdir(parents=True)
        (slot / ".m2" / "repository" / "g" / "a.jar").write_bytes(b"j" * 50)

        removed, freed = slot_lifecycle._purge_build_outputs(slot)

        assert not (slot / ".m2").exists()
        assert not (repo / "target").exists()
        assert not (repo / "modules" / "core" / "target").exists()
        assert (repo / "pom.xml").exists() and (repo / "modules" / "core" / "pom.xml").exists()
        assert removed == 3
        assert freed >= 250

    def test_keeps_source_and_git_data(self, tmp_path):
        slot = tmp_path / "slots" / "5"
        repo = init_repo(slot / "engine")
        _maven_module(repo)
        (repo / "src").mkdir()
        (repo / "src" / "Main.java").write_text("class Main {}")
        head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout

        slot_lifecycle._purge_build_outputs(slot)

        assert (repo / "src" / "Main.java").read_text() == "class Main {}"
        assert subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout == head
        assert subprocess.run(["git", "-C", str(repo), "fsck"], capture_output=True).returncode == 0

    def test_keeps_target_without_a_pom(self, tmp_path):
        """A directory that merely happens to be called target is not a build output."""
        slot = tmp_path / "slots" / "5"
        repo = init_repo(slot / "engine")
        (repo / "src" / "target").mkdir(parents=True)
        (repo / "src" / "target" / "Aim.java").write_text("class Aim {}")

        removed, _ = slot_lifecycle._purge_build_outputs(slot)

        assert (repo / "src" / "target" / "Aim.java").exists()
        assert removed == 0

    def test_keeps_target_holding_tracked_files(self, tmp_path, capsys):
        slot = tmp_path / "slots" / "5"
        repo = init_repo(slot / "engine")
        _maven_module(repo)
        (repo / "target" / "kept.txt").write_text("tracked")
        subprocess.run(["git", "-C", str(repo), "add", "-f", "target/kept.txt"], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "track"], capture_output=True, check=True)

        removed, _ = slot_lifecycle._purge_build_outputs(slot)

        assert (repo / "target" / "kept.txt").exists()
        assert removed == 0
        assert "WARN=target_has_tracked_files" in capsys.readouterr().out

    def test_never_follows_a_symlink_out_of_the_slot(self, tmp_path):
        outside_m2 = tmp_path / "host-m2"
        (outside_m2 / "repository").mkdir(parents=True)
        (outside_m2 / "repository" / "keep.jar").write_bytes(b"k")
        outside_target = tmp_path / "shared-target"
        outside_target.mkdir()
        (outside_target / "keep.class").write_bytes(b"k")
        slot = tmp_path / "slots" / "5"
        repo = init_repo(slot / "engine")
        _maven_module(repo, built=False)
        (slot / ".m2").symlink_to(outside_m2)
        (repo / "target").symlink_to(outside_target)

        slot_lifecycle._purge_build_outputs(slot)

        assert (outside_m2 / "repository" / "keep.jar").exists()
        assert (outside_target / "keep.class").exists()
        assert not (slot / ".m2").exists() and not (slot / ".m2").is_symlink()
        assert not (repo / "target").is_symlink()

    def test_does_not_touch_other_slots(self, tmp_path):
        slot = tmp_path / "slots" / "5"
        other = tmp_path / "slots" / "55"
        _maven_module(init_repo(slot / "engine"))
        other_repo = _maven_module(init_repo(other / "engine"))
        (other / ".m2").mkdir()

        slot_lifecycle._purge_build_outputs(slot)

        assert (other_repo / "target" / "classes" / "A.class").exists()
        assert (other / ".m2").exists()

    def test_archive_slot_purges_before_moving(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr("slot_lifecycle._has_unmerged_content", lambda d: [])
        monkeypatch.setattr("slot_lifecycle.verify_landed_shas", lambda d, f: (True, []))
        monkeypatch.setattr("slot_lifecycle._repack_broken_alternates", lambda d, f: 0)
        monkeypatch.setattr("slot_lifecycle._teardown_isx", lambda d: None)
        monkeypatch.setattr("slot_lifecycle.sweep_orphaned_claude_projects", lambda f: 0)
        monkeypatch.setattr("slot_lifecycle._escape_slot_cwd", lambda d, f: (False, None))
        monkeypatch.setattr("slot_lifecycle.relocate_claude_projects", lambda s, d: 0)
        slot = tmp_path / "slots" / "99"
        repo = init_repo(slot / "blocks")
        _maven_module(repo)
        (slot / ".m2" / "repository").mkdir(parents=True)
        (slot / ".landed").write_text("landed_shas=abc:123\n")
        (slot / ".slot").write_text("## Repos\n- blocks (primary)\n")

        slot_lifecycle.archive_slot(tmp_path, 99, force=True)

        dest = tmp_path / "slots" / "attic" / "99"
        assert (dest / "blocks" / "pom.xml").exists()
        assert not (dest / "blocks" / "target").exists()
        assert not (dest / ".m2").exists()
        assert "BUILD_OUTPUTS_PURGED=2" in capsys.readouterr().out

    def test_blocked_archive_purges_nothing(self, tmp_path, monkeypatch):
        monkeypatch.setattr("slot_claude.find_active_sessions",
                            lambda d: [(1, "claude", str(d))])
        monkeypatch.setattr("slot_lifecycle._has_unmerged_content", lambda d: [])
        monkeypatch.setattr("slot_lifecycle.verify_landed_shas", lambda d, f: (True, []))
        slot = tmp_path / "slots" / "99"
        repo = init_repo(slot / "blocks")
        _maven_module(repo)
        (slot / ".m2").mkdir()
        (slot / ".landed").write_text("landed_shas=abc:123\n")
        (slot / ".slot").write_text("## Repos\n- blocks (primary)\n")

        with pytest.raises(SystemExit):
            slot_lifecycle.archive_slot(tmp_path, 99, force=True)

        assert (repo / "target" / "classes" / "A.class").exists()
        assert (slot / ".m2").exists()


class TestSessionSlotBoundary:

    LSOF_CWD = (
        "COMMAND   PID USER   FD   TYPE DEVICE SIZE/OFF NODE NAME\n"
        "2.1.325   101 me    cwd    DIR   1,4      640  111 {root}/slots/21/engine\n"
        "2.1.325   102 me    cwd    DIR   1,4      640  112 {root}/slots/211/engine\n"
        "2.1.325   103 me    cwd    DIR   1,4      640  113 {root}/slots/21\n"
        "node      104 me    cwd    DIR   1,4      640  114 {root}/slots/21-old/x\n"
    )

    def test_cwd_match_stops_at_the_slot_directory(self, tmp_path):
        slot = tmp_path / "slots" / "21"
        slot.mkdir(parents=True)
        cwd_out = self.LSOF_CWD.format(root=tmp_path)

        def fake_run(args, **kw):
            out = cwd_out if args[:3] == ["lsof", "-d", "cwd"] else ""
            return subprocess.CompletedProcess(args, 0, stdout=out, stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            found = slot_claude.find_active_sessions(slot)

        assert sorted(pid for pid, _, _ in found) == [101, 103]


class TestMergeSlotRemoved:
    """#515: merge-slot was a second landing path with hard resets. It is a stub now."""

    def test_refuses_and_points_to_work_end(self, tmp_path, capsys):
        family, canonicals, slot, branch = _create_clone_test_repos(tmp_path, ["engine"])
        main_before = subprocess.run(
            ["git", "-C", str(canonicals["engine"]), "rev-parse", "main"],
            capture_output=True, text=True).stdout

        assert slot_lifecycle.merge_slot(family, 1) == 1

        out = capsys.readouterr().out
        assert "ERROR=merge_slot_removed" in out
        assert "work end" in out
        assert not (slot / ".landed").exists()
        assert subprocess.run(
            ["git", "-C", str(canonicals["engine"]), "rev-parse", "main"],
            capture_output=True, text=True).stdout == main_before

    def test_land_flow_module_is_gone(self):
        assert not (skill_dir.parent / "work-end" / "land_flow.py").exists()
