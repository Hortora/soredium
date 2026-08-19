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
    """DB-authoritative numbering replaced disk-scan allocation.
    See TestAllocateSlotNumberDB for the primary test class."""

    def _setup_db(self, tmp_path, monkeypatch):
        scripts_dir = Path(__file__).parent.parent / "scripts"
        sys.path.insert(0, str(scripts_dir))
        import worklog as _wl_mod
        db_path = tmp_path / "alloc_test.db"
        monkeypatch.setattr(slot_manager, "_wl", _wl_mod)
        monkeypatch.setattr(_wl_mod, "DEFAULT_DB", str(db_path))
        return _wl_mod

    def test_empty_db_returns_1(self, tmp_path, monkeypatch):
        self._setup_db(tmp_path, monkeypatch)
        assert slot_manager.allocate_slot_number(tmp_path) == 1

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
        assert slot_manager.allocate_slot_number(tmp_path) == 6

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
        assert slot_manager.allocate_slot_number(tmp_path) == 4

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
        assert slot_manager.allocate_slot_number(tmp_path) == 51


class TestResolveWorkspaceSource:
    def test_resolves_to_child_not_parent(self, tmp_path):
        """When child workspace is nested inside a parent git repo,
        resolve to the child (the actual workspace repo)."""
        parent = init_repo(tmp_path / "public" / "casehub")
        child = init_repo(parent / "engine")
        subprocess.run(["git", "-C", str(child), "remote", "add", "origin",
                         "https://github.com/mdproctor/wsp-casehub-engine.git"],
                        capture_output=True, check=True)
        repo = tmp_path / "casehub" / "engine"
        repo.mkdir(parents=True)
        (repo / "wksp").symlink_to(child)

        src, name = slot_manager.resolve_workspace_source(repo)
        assert src == child
        assert name == "wsp-casehub-engine"

    def test_name_from_remote_url(self, tmp_path):
        """Slot name derived from workspace repo's origin remote URL."""
        ws_repo = init_repo(tmp_path / "workspace")
        subprocess.run(["git", "-C", str(ws_repo), "remote", "add", "origin",
                         "https://github.com/mdproctor/wsp-casehub-connectors.git"],
                        capture_output=True, check=True)
        repo = tmp_path / "project"
        repo.mkdir(parents=True)
        (repo / "wksp").symlink_to(ws_repo)

        src, name = slot_manager.resolve_workspace_source(repo)
        assert src == ws_repo
        assert name == "wsp-casehub-connectors"

    def test_fallback_name_when_no_remote(self, tmp_path):
        """When workspace repo has no remote, construct name from path."""
        ws_repo = init_repo(tmp_path / "public" / "casehub" / "connectors")
        repo = tmp_path / "project"
        repo.mkdir(parents=True)
        (repo / "wksp").symlink_to(ws_repo)

        src, name = slot_manager.resolve_workspace_source(repo)
        assert src == ws_repo
        assert name == "wsp-casehub-connectors"

    def test_external_workspace_single_repo(self, tmp_path):
        """External workspace (no parent git repo) resolves directly."""
        ext_ws = init_repo(tmp_path / "public" / "casehub-iot")
        subprocess.run(["git", "-C", str(ext_ws), "remote", "add", "origin",
                         "https://github.com/mdproctor/wsp-casehub-iot.git"],
                        capture_output=True, check=True)
        repo = tmp_path / "casehub" / "iot"
        repo.mkdir(parents=True)
        (repo / "wksp").symlink_to(ext_ws)

        src, name = slot_manager.resolve_workspace_source(repo)
        assert src == ext_ws
        assert name == "wsp-casehub-iot"

    def test_no_wksp_symlink(self, tmp_path):
        repo = tmp_path / "casehub" / "engine"
        repo.mkdir(parents=True)
        result = slot_manager.resolve_workspace_source(repo)
        assert result is None

    def test_wksp_points_to_nonexistent(self, tmp_path):
        repo = tmp_path / "project"
        repo.mkdir(parents=True)
        (repo / "wksp").symlink_to(tmp_path / "nonexistent")
        result = slot_manager.resolve_workspace_source(repo)
        assert result is None


class TestWorkspaceNameCollision:
    @patch("slot_manager.run_cmd")
    def test_collision_detected_when_workspace_name_matches_repo(self, mock_cmd, tmp_path):
        """When resolve_workspace_source returns a name that collides with
        an existing directory (e.g., a repo clone), create_slot errors."""
        family = tmp_path / "casehub"
        family.mkdir()
        work_repo = init_repo(family / "work")
        ws_repo = init_repo(tmp_path / "public" / "casehub" / "work")
        (work_repo / "wksp").symlink_to(ws_repo)

        mock_cmd.return_value = (0, "", "")

        with patch("slot_manager.resolve_workspace_source") as mock_resolve:
            mock_resolve.return_value = (ws_repo, "work")
            with pytest.raises(SystemExit):
                slot_manager.create_slot(
                    family_root=family,
                    repos=["work"],
                    branch="issue-99-test",
                    issue="99",
                    issue_repo="casehubio/parent",
                    covers="99",
                    context="Test collision",
                )


class TestCrossOrgWorkspaceWiring:
    @patch("slot_manager.run_cmd")
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

        with patch("slot_manager.resolve_workspace_source") as mock_resolve:
            mock_resolve.side_effect = [
                (ws_trellis, "wsp-hortora-trellis"),
                (ws_pages, "wsp-casehub-pages"),
            ]
            result = slot_manager.create_slot(
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


class TestSetupSlotRepo:
    def test_creates_new_config_with_repo_local_and_settings(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        repo_wt = slot_dir / "engine"
        repo_wt.mkdir()
        m2 = slot_dir / ".m2"
        slot_manager.setup_slot_repo(repo_wt, m2)
        config = (repo_wt / ".mvn" / "maven.config").read_text()
        assert f"-Dmaven.repo.local={m2}" in config
        assert "--settings=.mvn/slot-settings.xml" in config

    def test_generates_slot_settings_xml(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        repo_wt = slot_dir / "engine"
        repo_wt.mkdir()
        m2 = slot_dir / ".m2"
        slot_manager.setup_slot_repo(repo_wt, m2)
        assert (slot_dir / "slot-settings.xml").exists()

    def test_copies_settings_into_mvn_dir(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        repo_wt = slot_dir / "engine"
        repo_wt.mkdir()
        m2 = slot_dir / ".m2"
        slot_manager.setup_slot_repo(repo_wt, m2)
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
        slot_manager.setup_slot_repo(repo_wt, m2)
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
        slot_manager.setup_slot_repo(repo_wt, m2)
        config = (mvn_dir / "maven.config").read_text()
        assert "-s " not in config
        assert "--settings=.mvn/slot-settings.xml" in config

    def test_idempotent(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        repo_wt = slot_dir / "engine"
        repo_wt.mkdir()
        m2 = slot_dir / ".m2"
        slot_manager.setup_slot_repo(repo_wt, m2)
        slot_manager.setup_slot_repo(repo_wt, m2)
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
        slot_manager.setup_slot_repo(repo_a, m2)
        slot_manager.setup_slot_repo(repo_b, m2)
        config_a = (repo_a / ".mvn" / "maven.config").read_text()
        config_b = (repo_b / ".mvn" / "maven.config").read_text()
        assert "--settings=.mvn/slot-settings.xml" in config_a
        assert "--settings=.mvn/slot-settings.xml" in config_b
        assert (slot_dir / "slot-settings.xml").exists()
        assert (repo_a / ".mvn" / "slot-settings.xml").exists()
        assert (repo_b / ".mvn" / "slot-settings.xml").exists()


    def test_creates_gitignore_with_all_baseline_patterns(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        repo_wt = slot_dir / "engine"
        repo_wt.mkdir()
        m2 = slot_dir / ".m2"
        changed = slot_manager.setup_slot_repo(repo_wt, m2)
        assert changed is True
        gitignore = (repo_wt / ".gitignore").read_text()
        for pattern in [".mvn/maven.config", ".mvn/slot-settings.xml",
                        ".worktrees", ".worktrees/", ".claude", ".claude/"]:
            assert pattern in gitignore.splitlines()

    def test_appends_missing_baseline_patterns(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        repo_wt = slot_dir / "engine"
        repo_wt.mkdir()
        m2 = slot_dir / ".m2"
        (repo_wt / ".gitignore").write_text("target/\n.mvn/maven.config\n.claude/\n")
        changed = slot_manager.setup_slot_repo(repo_wt, m2)
        assert changed is True
        lines = (repo_wt / ".gitignore").read_text().splitlines()
        assert "target/" in lines
        assert ".mvn/maven.config" in lines
        assert ".mvn/slot-settings.xml" in lines
        assert ".worktrees" in lines
        assert ".worktrees/" in lines
        assert ".claude" in lines
        assert ".claude/" in lines

    def test_all_patterns_present_returns_false(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        repo_wt = slot_dir / "engine"
        repo_wt.mkdir()
        m2 = slot_dir / ".m2"
        (repo_wt / ".gitignore").write_text(
            ".mvn/maven.config\n.mvn/slot-settings.xml\n"
            ".worktrees\n.worktrees/\n.claude\n.claude/\n"
        )
        changed = slot_manager.setup_slot_repo(repo_wt, m2)
        assert changed is False

    def test_gitignore_baseline_idempotent(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        repo_wt = slot_dir / "engine"
        repo_wt.mkdir()
        m2 = slot_dir / ".m2"
        slot_manager.setup_slot_repo(repo_wt, m2)
        content_after_first = (repo_wt / ".gitignore").read_text()
        changed = slot_manager.setup_slot_repo(repo_wt, m2)
        assert changed is False
        assert (repo_wt / ".gitignore").read_text() == content_after_first

    def test_preserves_existing_gitignore_content(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        repo_wt = slot_dir / "engine"
        repo_wt.mkdir()
        m2 = slot_dir / ".m2"
        (repo_wt / ".gitignore").write_text("target/\n*.pyc\n__pycache__\n")
        slot_manager.setup_slot_repo(repo_wt, m2)
        lines = (repo_wt / ".gitignore").read_text().splitlines()
        assert lines[0] == "target/"
        assert lines[1] == "*.pyc"
        assert lines[2] == "__pycache__"

    def test_adds_bare_form_when_slash_form_exists(self, tmp_path):
        slot_dir = tmp_path / "slot"
        slot_dir.mkdir()
        repo_wt = slot_dir / "engine"
        repo_wt.mkdir()
        m2 = slot_dir / ".m2"
        (repo_wt / ".gitignore").write_text(
            ".mvn/maven.config\n.mvn/slot-settings.xml\n"
            ".claude/\n.worktrees/\n"
        )
        changed = slot_manager.setup_slot_repo(repo_wt, m2)
        assert changed is True
        lines = (repo_wt / ".gitignore").read_text().splitlines()
        assert ".claude" in lines
        assert ".claude/" in lines
        assert ".worktrees" in lines
        assert ".worktrees/" in lines


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


class TestWriteSlotMdIsolation:
    def test_write_with_isolation(self, tmp_path):
        slot_manager.write_slot_md(
            tmp_path, 7, ["soredium"], "issue-42-fix", "42",
            "Hortora/soredium", "42", "Fix scoring",
            isolation_type="isx", isx_instance="issue-42-fix",
            isx_template="tpl-java",
        )
        content = (tmp_path / ".slot").read_text()
        assert "## Isolation" in content
        assert "type: isx" in content
        assert "instance: issue-42-fix" in content
        assert "template: tpl-java" in content

    def test_write_without_isolation(self, tmp_path):
        slot_manager.write_slot_md(
            tmp_path, 7, ["soredium"], "issue-42-fix", "42",
            "Hortora/soredium", "42", "Fix scoring",
        )
        content = (tmp_path / ".slot").read_text()
        assert "## Isolation" not in content

    def test_write_isolation_roundtrip(self, tmp_path):
        slot_manager.write_slot_md(
            tmp_path, 7, ["soredium"], "issue-42-fix", "42",
            "Hortora/soredium", "42", "Fix scoring",
            isolation_type="isx", isx_instance="issue-42-fix",
            isx_template="tpl-java",
        )
        result = slot_manager.parse_slot_md(tmp_path)
        assert result["isolation_type"] == "isx"
        assert result["isx_instance"] == "issue-42-fix"
        assert result["isx_template"] == "tpl-java"
        assert result["repos"] == ["soredium"]


class TestCreateSlot:
    @patch("slot_manager.run_cmd")
    def test_creates_single_repo_slot(self, mock_cmd, tmp_path):
        family = tmp_path / "casehub"
        family.mkdir()
        engine = init_repo(family / "engine")
        ws_engine = init_repo(tmp_path / "public" / "casehub" / "engine")
        (engine / "wksp").symlink_to(ws_engine)

        mock_cmd.return_value = (0, "", "")

        with patch("slot_manager.resolve_workspace_source") as mock_resolve:
            mock_resolve.return_value = (ws_engine, "wsp-casehub-engine")
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
        family.mkdir(parents=True)
        engine = init_repo(family / "engine")
        ws_engine = init_repo(tmp_path / "public" / "casehub" / "engine")
        (engine / "wksp").symlink_to(ws_engine)

        mock_cmd.return_value = (0, "", "")

        with patch("slot_manager.resolve_workspace_source") as mock_resolve:
            mock_resolve.return_value = (ws_engine, "wsp-casehub-engine")
            result1 = slot_manager.create_slot(
                family_root=family,
                repos=["engine"],
                branch="issue-42-spi",
                issue="42",
                issue_repo="casehubio/engine",
                covers="42",
                context="First slot",
            )
            assert result1["slot_number"] == 1

            result2 = slot_manager.create_slot(
                family_root=family,
                repos=["engine"],
                branch="issue-55-ledger",
                issue="55",
                issue_repo="casehubio/engine",
                covers="55",
                context="Fix ledger",
            )
            assert result2["slot_number"] == 2

    @patch("slot_manager.run_cmd")
    def test_clone_failure_exits(self, mock_cmd, tmp_path, capsys):
        family = tmp_path / "casehub"
        engine = init_repo(family / "engine")
        ws_engine = init_repo(tmp_path / "public" / "casehub" / "engine")
        (engine / "wksp").symlink_to(ws_engine)

        mock_cmd.side_effect = [
            (0, "", ""),  # fetch
            (0, "", ""),  # remote get-url upstream check
            (0, "", ""),  # fetch upstream
            (0, "", ""),  # rebase upstream
            (0, "", ""),  # push origin
            (1, "", "fatal: clone failed"),  # clone fails
        ]

        with patch("slot_manager.resolve_workspace_source") as mock_resolve:
            mock_resolve.return_value = (ws_engine, "wsp-casehub-engine")
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


class TestCreateSlotIsx:
    @patch("slot_manager.run_cmd")
    def test_create_isx_slot_preflight_fails(self, mock_cmd, tmp_path, capsys):
        family = tmp_path / "casehub"
        family.mkdir()
        init_repo(family / "engine")
        mock_cmd.return_value = (0, "", "")
        with patch("shutil.which", return_value=None):
            with pytest.raises(SystemExit):
                slot_manager.create_slot(
                    family_root=family, repos=["engine"],
                    branch="issue-42-fix", issue="42",
                    issue_repo="Hortora/soredium", covers="42",
                    context="test", isx=True, isx_template="tpl-java",
                )
        captured = capsys.readouterr()
        assert "ERROR=isx_not_found" in captured.out

    @patch("slot_manager.run_cmd")
    def test_create_isx_slot_writes_isolation(self, mock_cmd, tmp_path):
        family = tmp_path / "casehub"
        family.mkdir()
        init_repo(family / "engine")
        mock_cmd.return_value = (0, "", "")
        with patch("shutil.which", return_value="/opt/homebrew/bin/isx"):
            result = slot_manager.create_slot(
                family_root=family, repos=["engine"],
                branch="issue-42-fix", issue="42",
                issue_repo="Hortora/soredium", covers="42",
                context="test", isx=True, isx_template="tpl-java",
            )
        slot_dir = family / "slots" / str(result["slot_number"])
        info = slot_manager.parse_slot_md(slot_dir)
        assert info["isolation_type"] == "isx"
        assert info["isx_template"] == "tpl-java"
        assert info["isx_instance"] == "issue-42-fix"

    @patch("slot_manager.run_cmd")
    def test_create_non_isx_unchanged(self, mock_cmd, tmp_path):
        family = tmp_path / "casehub"
        family.mkdir()
        init_repo(family / "engine")
        mock_cmd.return_value = (0, "", "")
        result = slot_manager.create_slot(
            family_root=family, repos=["engine"],
            branch="issue-42-fix", issue="42",
            issue_repo="Hortora/soredium", covers="42",
            context="test",
        )
        slot_dir = family / "slots" / str(result["slot_number"])
        info = slot_manager.parse_slot_md(slot_dir)
        assert info["isolation_type"] == ""

    @patch("slot_manager.run_cmd")
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
            with pytest.raises(SystemExit):
                slot_manager.create_slot(
                    family_root=family, repos=["engine"],
                    branch="issue-42-fix", issue="42",
                    issue_repo="Hortora/soredium", covers="42",
                    context="test", isx=True, isx_template="tpl-java",
                )
        captured = capsys.readouterr()
        assert "ERROR=isx_branch_failed" in captured.out


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

    def test_force_archives_without_landed_check(self, tmp_path):
        """--force skips .landed check but still archives to attic."""
        family = tmp_path / "casehub"
        slot = family / "slots" / "1"
        slot.mkdir(parents=True)
        (slot / ".slot").write_text("test")

        with patch("slot_manager.run_cmd") as mock_cmd:
            mock_cmd.return_value = (0, "", "")
            slot_manager.remove_slot(family, 1, force=True)

        assert not slot.exists()
        attic = family / "slots" / "attic" / "1"
        assert attic.exists(), "force must archive to attic, never delete"
        assert (attic / ".slot").exists()

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


class TestParseSlotMdIsolation:
    def test_parse_with_isolation_section(self, tmp_path):
        (tmp_path / ".slot").write_text(
            "# Slot 7 — issue-42-fix\n\n"
            "## Issue\nHortora/soredium#42\nCovers: 42\n\n"
            "## What to do\nFix scoring\n\n"
            "## Repos\n- soredium (primary)\n\n"
            "## Isolation\ntype: isx\ninstance: issue-42-fix\n"
            "template: tpl-java\n\n"
            "## Created\n2026-08-12, branch: issue-42-fix\n"
        )
        result = slot_manager.parse_slot_md(tmp_path)
        assert result["isolation_type"] == "isx"
        assert result["isx_instance"] == "issue-42-fix"
        assert result["isx_template"] == "tpl-java"

    def test_parse_without_isolation_section(self, tmp_path):
        (tmp_path / ".slot").write_text(
            "# Slot 7 — issue-42-fix\n\n"
            "## Issue\nHortora/soredium#42\nCovers: 42\n\n"
            "## Repos\n- soredium (primary)\n\n"
            "## Created\n2026-08-12, branch: issue-42-fix\n"
        )
        result = slot_manager.parse_slot_md(tmp_path)
        assert result["isolation_type"] == ""
        assert result["isx_instance"] == ""
        assert result["isx_template"] == ""

    def test_parse_isolation_preserves_existing_fields(self, tmp_path):
        (tmp_path / ".slot").write_text(
            "# Slot 7 — issue-42-fix\n\n"
            "## Issue\nHortora/soredium#42\nCovers: 42\n\n"
            "## What to do\nFix scoring\n\n"
            "## Repos\n- soredium (primary)\n\n"
            "## Isolation\ntype: isx\ninstance: issue-42-fix\n"
            "template: tpl-java\n\n"
            "## Created\n2026-08-12, branch: issue-42-fix\n"
        )
        result = slot_manager.parse_slot_md(tmp_path)
        assert result["repos"] == ["soredium"]
        assert result["issue"] == "42"
        assert result["covers"] == "42"
        assert result["context"] == "Fix scoring"


class TestIsxHelpers:
    def test_check_isx_available_found(self):
        with patch("shutil.which", return_value="/opt/homebrew/bin/isx"):
            assert slot_manager._check_isx_available() is True

    def test_check_isx_available_missing(self):
        with patch("shutil.which", return_value=None):
            assert slot_manager._check_isx_available() is False

    def test_truncate_short_name(self):
        assert slot_manager._truncate_instance_name("issue-42-fix") == "issue-42-fix"

    def test_truncate_long_name(self):
        long_name = "issue-223-isx-isolation-for-slots-with-very-long-description-that-exceeds-limit"
        result = slot_manager._truncate_instance_name(long_name, max_len=63)
        assert len(result) <= 63
        assert result.startswith("issue-223-isx-isolation")

    def test_truncate_strips_trailing_hyphens(self):
        name = "a" * 60 + "---bcd"
        result = slot_manager._truncate_instance_name(name, max_len=63)
        assert not result.endswith("-")


class TestTeardownIsx:
    def test_teardown_isx_slot(self, tmp_path):
        (tmp_path / ".slot").write_text(
            "# Slot 1 — test\n\n## Issue\nOrg/repo#42\nCovers: 42\n\n"
            "## Repos\n- engine (primary)\n\n"
            "## Isolation\ntype: isx\n"
            "instance: test-instance\ntemplate: tpl-java\n\n"
            "## Created\n2026-08-12, branch: test\n"
        )
        with patch("slot_manager.run_cmd", return_value=(0, "", "")) as mock:
            slot_manager._teardown_isx(tmp_path)
            mock.assert_called_once_with(["isx", "destroy", "test-instance"])

    def test_teardown_non_isx_slot(self, tmp_path):
        (tmp_path / ".slot").write_text(
            "# Slot 1 — test\n\n## Repos\n- soredium\n\n"
            "## Created\n2026-08-12, branch: test\n"
        )
        with patch("slot_manager.run_cmd") as mock:
            slot_manager._teardown_isx(tmp_path)
            mock.assert_not_called()

    def test_teardown_destroy_fails_warns(self, tmp_path, capsys):
        (tmp_path / ".slot").write_text(
            "# Slot 1 — test\n\n## Issue\nOrg/repo#42\nCovers: 42\n\n"
            "## Repos\n- engine (primary)\n\n"
            "## Isolation\ntype: isx\n"
            "instance: gone-instance\ntemplate: tpl-java\n\n"
            "## Created\n2026-08-12, branch: test\n"
        )
        with patch("slot_manager.run_cmd", return_value=(1, "", "not found")):
            slot_manager._teardown_isx(tmp_path)
            out = capsys.readouterr().out
            assert "WARN" in out


class TestWireIsxRemotes:
    def test_wire_remotes_adds_per_repo(self, tmp_path):
        repos = ["engine", "iot"]
        for r in repos:
            repo_dir = tmp_path / r
            repo_dir.mkdir()
            (repo_dir / ".git").mkdir()
        with patch("slot_manager.run_cmd", return_value=(0, "", "")) as mock:
            slot_manager._wire_isx_remotes(tmp_path, repos, "test-instance")
            assert mock.call_count == 2
            mock.assert_any_call([
                "git", "-C", str(tmp_path / "engine"),
                "remote", "add", "isx",
                "isx://test-instance/home/agentuser/engine",
            ])
            mock.assert_any_call([
                "git", "-C", str(tmp_path / "iot"),
                "remote", "add", "isx",
                "isx://test-instance/home/agentuser/iot",
            ])

    def test_wire_skips_missing_repo_dir(self, tmp_path):
        with patch("slot_manager.run_cmd") as mock:
            slot_manager._wire_isx_remotes(tmp_path, ["nonexistent"], "test-instance")
            mock.assert_not_called()


class TestSyncIsx:
    def test_sync_happy_path(self, tmp_path):
        slot_dir = tmp_path / "slots" / "1"
        slot_dir.mkdir(parents=True)
        init_repo(slot_dir / "engine")
        (slot_dir / ".slot").write_text(
            "# Slot 1 — test\n\n## Issue\nOrg/repo#42\nCovers: 42\n\n"
            "## Repos\n- engine (primary)\n\n"
            "## Isolation\ntype: isx\ninstance: test-inst\n"
            "template: tpl-java\n\n## Created\n2026-08-12, branch: test\n"
        )
        with patch("slot_manager.run_cmd") as mock:
            mock.return_value = (0, "", "")
            result = slot_manager.sync_isx(slot_dir)
        assert result == 0
        call_args_list = [c[0][0] for c in mock.call_args_list]
        assert any("fetch" in args for args in call_args_list)
        assert any("merge" in args for args in call_args_list)

    def test_sync_non_isx_slot(self, tmp_path, capsys):
        slot_dir = tmp_path / "slots" / "1"
        slot_dir.mkdir(parents=True)
        (slot_dir / ".slot").write_text(
            "# Slot 1 — test\n\n## Repos\n- engine\n\n"
            "## Created\n2026-08-12, branch: test\n"
        )
        result = slot_manager.sync_isx(slot_dir)
        assert result == 1
        captured = capsys.readouterr()
        assert "ERROR=not_isx_slot" in captured.out

    def test_sync_diverged_stops(self, tmp_path):
        slot_dir = tmp_path / "slots" / "1"
        slot_dir.mkdir(parents=True)
        init_repo(slot_dir / "engine")
        (slot_dir / ".slot").write_text(
            "# Slot 1 — test\n\n## Issue\nOrg/repo#42\nCovers: 42\n\n"
            "## Repos\n- engine (primary)\n\n"
            "## Isolation\ntype: isx\ninstance: test-inst\n"
            "template: tpl-java\n\n## Created\n2026-08-12, branch: test\n"
        )
        def side_effect(args, cwd=None):
            if "merge" in args and "--ff-only" in args:
                return (1, "", "fatal: Not possible to fast-forward")
            return (0, "", "")
        with patch("slot_manager.run_cmd", side_effect=side_effect):
            result = slot_manager.sync_isx(slot_dir)
        assert result == 1

    def test_sync_no_isx_remote_skips(self, tmp_path):
        slot_dir = tmp_path / "slots" / "1"
        slot_dir.mkdir(parents=True)
        init_repo(slot_dir / "engine")
        (slot_dir / ".slot").write_text(
            "# Slot 1 — test\n\n## Issue\nOrg/repo#42\nCovers: 42\n\n"
            "## Repos\n- engine (primary)\n\n"
            "## Isolation\ntype: isx\ninstance: test-inst\n"
            "template: tpl-java\n\n## Created\n2026-08-12, branch: test\n"
        )
        def side_effect(args, cwd=None):
            if "get-url" in args:
                return (1, "", "fatal: No such remote 'isx'")
            return (0, "", "")
        with patch("slot_manager.run_cmd", side_effect=side_effect):
            result = slot_manager.sync_isx(slot_dir)
        assert result == 0


class TestAddRepoIsx:
    @patch("slot_manager.run_cmd")
    def test_add_repo_wires_isx_remote(self, mock_cmd, tmp_path):
        family = tmp_path / "casehub"
        family.mkdir()
        slot_dir = family / "slots" / "1"
        slot_dir.mkdir(parents=True)
        init_repo(slot_dir / "engine")
        init_repo(family / "iot")
        slot_manager.write_slot_md(
            slot_dir, 1, ["engine"], "test-branch", "42",
            "Org/repo", "42", "test",
            isolation_type="isx", isx_instance="test-inst",
            isx_template="tpl-java",
        )
        mock_cmd.return_value = (0, "", "")
        slot_manager.add_repo(family, 1, "iot", "test-branch")
        isx_calls = [c for c in mock_cmd.call_args_list
                    if len(c[0][0]) > 5 and "isx://" in str(c[0][0])]
        assert len(isx_calls) >= 1

    @patch("slot_manager.run_cmd")
    def test_add_repo_non_isx_no_remote(self, mock_cmd, tmp_path):
        family = tmp_path / "casehub"
        family.mkdir()
        slot_dir = family / "slots" / "1"
        slot_dir.mkdir(parents=True)
        init_repo(slot_dir / "engine")
        init_repo(family / "iot")
        slot_manager.write_slot_md(
            slot_dir, 1, ["engine"], "test-branch", "42",
            "Org/repo", "42", "test",
        )
        mock_cmd.return_value = (0, "", "")
        slot_manager.add_repo(family, 1, "iot", "test-branch")
        isx_calls = [c for c in mock_cmd.call_args_list
                    if any("isx://" in str(a) for a in c[0][0])]
        assert len(isx_calls) == 0


class TestRemoveSlotIsx:
    def test_remove_destroys_isx(self, tmp_path):
        family = tmp_path / "casehub"
        slot_dir = family / "slots" / "1"
        slot_dir.mkdir(parents=True)
        init_repo(slot_dir / "engine")
        slot_manager.write_slot_md(
            slot_dir, 1, ["engine"], "test-branch", "42",
            "Org/repo", "42", "test",
            isolation_type="isx", isx_instance="test-inst",
            isx_template="tpl-java",
        )
        (slot_dir / ".landed").write_text("landed")
        with patch("slot_manager.run_cmd", return_value=(0, "", "")):
            with patch("slot_manager._teardown_isx") as mock_teardown:
                slot_manager.remove_slot(family, 1)
                mock_teardown.assert_called_once()


class TestListSlotsIsolation:
    def test_list_shows_isx_isolation(self, tmp_path):
        slot_dir = tmp_path / "slots" / "1"
        slot_dir.mkdir(parents=True)
        init_repo(slot_dir / "engine")
        slot_manager.write_slot_md(
            slot_dir, 1, ["engine"], "test-branch", "42",
            "Org/repo", "42", "test",
            isolation_type="isx", isx_instance="test-inst",
            isx_template="tpl-java",
        )
        slots = slot_manager.list_slots(tmp_path)
        assert slots[0]["isolation"] == "isx"

    def test_list_shows_none_isolation(self, tmp_path):
        slot_dir = tmp_path / "slots" / "1"
        slot_dir.mkdir(parents=True)
        init_repo(slot_dir / "engine")
        slot_manager.write_slot_md(
            slot_dir, 1, ["engine"], "test-branch", "42",
            "Org/repo", "42", "test",
        )
        slots = slot_manager.list_slots(tmp_path)
        assert slots[0]["isolation"] == "none"


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
    slots_dir = family / "slots"
    slots_dir.mkdir()

    originals = {}
    for name in repo_names:
        originals[name] = _init_repo_with_remote(family / name)
        slot_manager.configure_update_instead(originals[name])

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
        originals[name] = _init_repo_with_remote(family / name)
        slot_manager.configure_update_instead(originals[name])

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


class TestResolveOriginalRepo:
    def test_resolves_worktree_to_original(self, tmp_path):
        family, originals, slot, _ = _create_worktree_test_repos(tmp_path, ["engine"])
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
        subprocess.run(["git", "-C", str(originals["engine"]), "push", "origin", "main"], capture_output=True)
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
        subprocess.run(["git", "-C", str(originals["engine"]), "push", "origin", "main"], capture_output=True)

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
    """Create a test family with clone-based slots (new remote layout)."""
    family = tmp_path / "family"
    family.mkdir()
    slots_dir = family / "slots"
    slots_dir.mkdir()

    originals = {}
    for name in repo_names:
        originals[name] = _init_repo_with_remote(family / name)
        slot_manager.configure_update_instead(originals[name])

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
        family, originals, slot, _ = _create_worktree_test_repos(tmp_path, ["engine"])
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

    def test_clone_stamps_pushed_to_bare(self, tmp_path):
        """Stamps are pushed to origin (bare repo acting as GitHub)."""
        family, originals, slot, branch = _create_clone_test_repos(tmp_path, ["engine"])
        slot_manager.merge_slot(family, 1)
        bare_path = family / ".engine-bare.git"
        rc, log, _ = slot_manager.run_cmd(
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
        exit_code = slot_manager.merge_slot(family, 1)
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
        exit_code = slot_manager.merge_slot(family, 1)
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
        exit_code = slot_manager.merge_slot(family, 1)
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "dirty_worktree" not in out

    def test_passes_when_original_not_on_main_worktree_layout(self, tmp_path, capsys):
        family, originals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        subprocess.run(
            ["git", "-C", str(originals["engine"]), "checkout", "-b", "detour"],
            capture_output=True, check=True,
        )
        exit_code = slot_manager.merge_slot(family, 1)
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "not_on_main" not in out.lower()


class TestEnsureCloneLayout:
    def test_migrates_worktree_to_clone(self, tmp_path):
        family, originals, slot, branch = _create_worktree_test_repos(tmp_path, ["engine"])
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
        family, originals, slot, branch = _create_worktree_test_repos(tmp_path, ["engine"])
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
        family, originals, slot, branch = _create_worktree_test_repos(tmp_path, ["engine"])
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
    def test_merges_when_attic_slot_already_exists(self, tmp_path, capsys):
        """archive_slot merges into existing attic entry — handles restore-then-rearchive."""
        family, originals, slot, branch = _create_merge_test_repos(tmp_path, ["engine"])
        slot_manager.merge_slot(family, 1)

        # First archive — should succeed
        slot_manager.archive_slot(family, 1)
        attic = family / "slots" / "attic" / "1"
        assert attic.exists()

        # Recreate slot dir with new content (simulates restore + rework + reland)
        (family / "slots" / "1").mkdir()
        (family / "slots" / "1" / ".slot").write_text("restored")
        (family / "slots" / "1" / ".landed").write_text("re-landed")

        # Second archive — should merge, not error
        slot_manager.archive_slot(family, 1, force=True)
        captured = capsys.readouterr()
        assert "WARN=attic_slot_exists" in captured.out
        assert "ARCHIVED=1" in captured.out
        # New content merged into attic
        assert (attic / ".landed").read_text() == "re-landed"
        assert (attic / ".slot").read_text() == "restored"
        # Original slot dir removed
        assert not (family / "slots" / "1").exists()


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
            escaped, _ = slot_manager._escape_slot_cwd(slot, escape_to)
            assert escaped is True
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
            escaped, relative = slot_manager._escape_slot_cwd(slot, escape_to)
            assert escaped is True
            assert relative == Path("engine")
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
            escaped, _ = slot_manager._escape_slot_cwd(slot, escape_to)
            assert escaped is False
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


class TestIsWorkspaceClone:
    def test_detects_workspace_marker(self, tmp_path):
        ws = tmp_path / "work-casehub"
        ws.mkdir()
        (ws / ".workspace").write_text("project: /path/to/project\n")
        assert slot_manager.is_workspace_clone(ws) is True

    def test_detects_proj_symlink(self, tmp_path):
        ws = tmp_path / "custom-ws-name"
        ws.mkdir()
        (ws / "proj").symlink_to("/path/to/project")
        assert slot_manager.is_workspace_clone(ws) is True

    def test_detects_work_prefix_name(self, tmp_path):
        ws = tmp_path / "work-casehub"
        ws.mkdir()
        assert slot_manager.is_workspace_clone(ws) is True

    def test_detects_work_name(self, tmp_path):
        ws = tmp_path / "work"
        ws.mkdir()
        assert slot_manager.is_workspace_clone(ws) is True

    def test_project_repo_not_workspace(self, tmp_path):
        repo = tmp_path / "engine"
        repo.mkdir()
        assert slot_manager.is_workspace_clone(repo) is False

    def test_worker_named_repo_not_workspace(self, tmp_path):
        repo = tmp_path / "worker"
        repo.mkdir()
        assert slot_manager.is_workspace_clone(repo) is False

    def test_nonexistent_path(self, tmp_path):
        assert slot_manager.is_workspace_clone(tmp_path / "nope") is False

    def test_workspace_marker_overrides_project_name(self, tmp_path):
        """A repo named like a project but with .workspace is still a workspace."""
        ws = tmp_path / "engine"
        ws.mkdir()
        (ws / ".workspace").write_text("project: /path/to/engine\n")
        assert slot_manager.is_workspace_clone(ws) is True

    def test_proj_symlink_overrides_project_name(self, tmp_path):
        """A repo with a proj symlink is a workspace even with a project-like name."""
        ws = tmp_path / "platform"
        ws.mkdir()
        (ws / "proj").symlink_to("/path/to/platform")
        assert slot_manager.is_workspace_clone(ws) is True

    def test_wsp_prefix_without_marker_is_project(self, tmp_path):
        """wsp-casehub-connectors without .workspace marker is a project repo
        (name alone is not a detection signal)."""
        repo = tmp_path / "wsp-casehub-connectors"
        repo.mkdir()
        assert slot_manager.is_workspace_clone(repo) is False

    def test_wsp_prefix_with_marker_is_workspace(self, tmp_path):
        """wsp-casehub-connectors with .workspace marker is detected."""
        ws = tmp_path / "wsp-casehub-connectors"
        ws.mkdir()
        (ws / ".workspace").touch()
        assert slot_manager.is_workspace_clone(ws) is True


class TestGetSlotReposFiltersWorkspaces:
    def test_excludes_workspace_by_name(self, tmp_path):
        slot = tmp_path / "slot"
        slot.mkdir()
        init_repo(slot / "engine")
        init_repo(slot / "work-casehub")
        repos = slot_manager.get_slot_repos(slot)
        assert "engine" in repos
        assert "work-casehub" not in repos

    def test_excludes_workspace_by_marker(self, tmp_path):
        slot = tmp_path / "slot"
        slot.mkdir()
        init_repo(slot / "engine")
        ws = init_repo(slot / "custom-ws")
        (ws / ".workspace").write_text("project: /path\n")
        repos = slot_manager.get_slot_repos(slot)
        assert "engine" in repos
        assert "custom-ws" not in repos

    def test_excludes_workspace_by_proj_symlink(self, tmp_path):
        slot = tmp_path / "slot"
        slot.mkdir()
        init_repo(slot / "engine")
        ws = init_repo(slot / "my-workspace")
        (ws / "proj").symlink_to(str(slot / "engine"))
        repos = slot_manager.get_slot_repos(slot)
        assert "engine" in repos
        assert "my-workspace" not in repos

    def test_excludes_wsp_prefix_workspace_by_marker(self, tmp_path):
        """New naming: wsp-casehub-connectors with .workspace marker is excluded."""
        slot = tmp_path / "slot"
        slot.mkdir()
        init_repo(slot / "connectors")
        ws = init_repo(slot / "wsp-casehub-connectors")
        (ws / ".workspace").touch()
        repos = slot_manager.get_slot_repos(slot)
        assert "connectors" in repos
        assert "wsp-casehub-connectors" not in repos

    def test_wsp_prefix_without_marker_included_as_project(self, tmp_path):
        """Without .workspace marker, wsp-prefixed dir passes as project repo."""
        slot = tmp_path / "slot"
        slot.mkdir()
        init_repo(slot / "connectors")
        init_repo(slot / "wsp-casehub-connectors")  # no marker
        repos = slot_manager.get_slot_repos(slot)
        assert "connectors" in repos
        assert "wsp-casehub-connectors" in repos

    def test_get_all_still_returns_workspaces(self, tmp_path):
        slot = tmp_path / "slot"
        slot.mkdir()
        init_repo(slot / "engine")
        init_repo(slot / "work-casehub")
        all_repos = slot_manager.get_all_slot_repos(slot)
        assert "engine" in all_repos
        assert "work-casehub" in all_repos


class TestMergeSlotSkipsWorkspace:
    def test_skips_workspace_clones(self, tmp_path, capsys):
        """merge_slot must not process workspace clones through merge/push."""
        family, originals, slot, branch = _create_merge_test_repos(
            tmp_path, ["engine"]
        )
        ws_clone = init_repo(slot / "work-casehub")
        subprocess.run(
            ["git", "-C", str(ws_clone), "checkout", "-b", branch],
            capture_output=True, check=True,
        )
        (ws_clone / "blog.md").write_text("# Blog entry\n")
        subprocess.run(
            ["git", "-C", str(ws_clone), "add", "."],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(ws_clone), "commit", "-m", "blog entry"],
            capture_output=True, check=True,
        )

        exit_code = slot_manager.merge_slot(family, 1)
        assert exit_code == 0

        captured = capsys.readouterr().out
        assert "SKIPPED_WORKSPACE=work-casehub" in captured

        landed = (slot / ".landed").read_text()
        assert "work-casehub" not in landed
        assert "engine:" in landed

    def test_skips_workspace_with_marker(self, tmp_path, capsys):
        """Workspace detected by .workspace marker is skipped."""
        family, originals, slot, branch = _create_merge_test_repos(
            tmp_path, ["engine"]
        )
        ws_clone = init_repo(slot / "custom-ws")
        (ws_clone / ".workspace").write_text("project: /path/to/proj\n")
        subprocess.run(
            ["git", "-C", str(ws_clone), "checkout", "-b", branch],
            capture_output=True, check=True,
        )

        exit_code = slot_manager.merge_slot(family, 1)
        assert exit_code == 0

        captured = capsys.readouterr().out
        assert "custom-ws" in captured
        landed = (slot / ".landed").read_text()
        assert "custom-ws" not in landed

    def test_project_repos_still_merge(self, tmp_path):
        """Project repos still merge normally after workspace filtering."""
        family, originals, slot, branch = _create_merge_test_repos(
            tmp_path, ["engine", "iot"]
        )
        init_repo(slot / "work-casehub")

        exit_code = slot_manager.merge_slot(family, 1)
        assert exit_code == 0

        for name in ["engine", "iot"]:
            assert (originals[name] / "feature.py").exists()


class TestRemoveSlotForceArchiveClaude:
    def test_force_relocates_claude_projects_to_attic(self, tmp_path, monkeypatch):
        """--force archives to attic and relocates Claude session dirs."""
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
            slot_manager.remove_slot(family, 1, force=True)

        attic = family / "slots" / "attic" / "1"
        assert attic.exists(), "force must archive to attic, never delete"
        assert (attic / ".slot").exists()
        assert not proj_dir.exists(), "Claude session dir should be relocated"


class TestListSlotsDriftDetection:
    """Inline drift detection comparing DB vs disk state."""

    def _setup_db(self, tmp_path, monkeypatch):
        scripts_dir = Path(__file__).parent.parent / "scripts"
        sys.path.insert(0, str(scripts_dir))
        import worklog as _wl_mod
        db_path = tmp_path / "drift_test.db"
        monkeypatch.setattr(slot_manager, "_wl", _wl_mod)
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
        slot_manager.list_slots(family)
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
        slot_manager.list_slots(family)
        captured = capsys.readouterr()
        assert "WARN=db_drift type=db-only slot=99" in captured.out

    def test_warns_on_disk_only(self, tmp_path, monkeypatch, capsys):
        _wl_mod = self._setup_db(tmp_path, monkeypatch)
        family = tmp_path / "family"
        slot_dir = family / "slots" / "1"
        slot_dir.mkdir(parents=True)
        (slot_dir / ".slot").write_text("# Slot 1 — test\n")
        _wl_mod.connect().close()
        slot_manager.list_slots(family)
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
        slot_manager.list_slots(family, include_archived=True)
        captured = capsys.readouterr()
        assert "WARN=db_drift type=state-mismatch slot=1" in captured.out

    def test_warns_on_ghost(self, tmp_path, monkeypatch, capsys):
        _wl_mod = self._setup_db(tmp_path, monkeypatch)
        family = tmp_path / "family"
        ghost = family / "slots" / "1"
        ghost.mkdir(parents=True)
        (ghost / ".m2").mkdir()
        _wl_mod.connect().close()
        slot_manager.list_slots(family)
        captured = capsys.readouterr()
        assert "WARN=db_drift type=ghost slot=1" in captured.out

    def test_no_drift_check_without_worklog(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(slot_manager, "_wl", None)
        family = tmp_path / "family"
        slot_dir = family / "slots" / "1"
        slot_dir.mkdir(parents=True)
        (slot_dir / ".slot").write_text("# Slot 1 — test\n")
        slot_manager.list_slots(family)
        captured = capsys.readouterr()
        assert "WARN=db_drift" not in captured.out


class TestAllocateSlotNumberDB:
    """DB-authoritative slot numbering: reserve-first pattern."""

    def _setup_db(self, tmp_path, monkeypatch):
        scripts_dir = Path(__file__).parent.parent / "scripts"
        sys.path.insert(0, str(scripts_dir))
        import worklog as _wl_mod
        db_path = tmp_path / "test.db"
        monkeypatch.setattr(slot_manager, "_wl", _wl_mod)
        monkeypatch.setattr(_wl_mod, "DEFAULT_DB", str(db_path))
        return _wl_mod

    def test_first_slot_returns_1(self, tmp_path, monkeypatch):
        self._setup_db(tmp_path, monkeypatch)
        num = slot_manager.allocate_slot_number(tmp_path)
        assert num == 1

    def test_increments_from_existing(self, tmp_path, monkeypatch):
        self._setup_db(tmp_path, monkeypatch)
        slot_manager.allocate_slot_number(tmp_path)
        num = slot_manager.allocate_slot_number(tmp_path)
        assert num == 2

    def test_hard_fails_without_worklog(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(slot_manager, "_wl", None)
        with pytest.raises(SystemExit):
            slot_manager.allocate_slot_number(tmp_path)
        captured = capsys.readouterr()
        assert "ERROR=worklog_unavailable" in captured.out

    def test_inserts_pending_row(self, tmp_path, monkeypatch):
        _wl_mod = self._setup_db(tmp_path, monkeypatch)
        num = slot_manager.allocate_slot_number(tmp_path)
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
        slot_manager.allocate_slot_number(family_a)
        slot_manager.allocate_slot_number(family_a)
        num = slot_manager.allocate_slot_number(family_b)
        assert num == 1


class TestRelocateClaudeProjectsRelativePath:
    """Regression: relative slot_dir paths must resolve to absolute before encoding."""

    def test_relocate_matches_when_slot_dir_is_relative(self, tmp_path, monkeypatch):
        slot_abs = tmp_path / "family" / "slots" / "1"
        slot_abs.mkdir(parents=True)
        repo = slot_abs / "engine"
        repo.mkdir()

        fake_home = tmp_path / "home"
        claude_projects = fake_home / ".claude" / "projects"
        claude_projects.mkdir(parents=True)
        proj_dir = claude_projects / str(slot_abs / "engine").replace("/", "-")
        proj_dir.mkdir()
        (proj_dir / "memory.md").write_text("data")

        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

        slot_rel = Path("family") / "slots" / "1"
        dest_rel = Path("family") / "slots" / "attic" / "1"
        monkeypatch.chdir(tmp_path)

        moved = slot_manager.relocate_claude_projects(slot_rel, dest_rel)

        assert moved == 1, "relative path must still find the Claude project dir"
        assert not proj_dir.exists()
        dest_encoded = str((tmp_path / dest_rel / "engine").resolve()).replace("/", "-")
        assert (claude_projects / dest_encoded).exists()

    def test_remove_matches_when_slot_dir_is_relative(self, tmp_path, monkeypatch):
        slot_abs = tmp_path / "family" / "slots" / "1"
        slot_abs.mkdir(parents=True)
        repo = slot_abs / "engine"
        repo.mkdir()

        fake_home = tmp_path / "home"
        claude_projects = fake_home / ".claude" / "projects"
        claude_projects.mkdir(parents=True)
        proj_dir = claude_projects / str(slot_abs / "engine").replace("/", "-")
        proj_dir.mkdir()
        (proj_dir / "session.jsonl").write_text("[]")

        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

        slot_rel = Path("family") / "slots" / "1"
        monkeypatch.chdir(tmp_path)

        removed = slot_manager.remove_claude_projects(slot_rel)

        assert removed == 1, "relative path must still find the Claude project dir"
        assert not proj_dir.exists()


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


class TestGetAllSlotRepos:
    def test_includes_workspace_dirs(self, tmp_path):
        slot = tmp_path / "slot1"
        slot.mkdir()
        for name in ["engine", "pages", "work-casehub"]:
            d = slot / name
            d.mkdir()
            (d / ".git").mkdir()
        (slot / ".m2").mkdir()
        result = slot_manager.get_all_slot_repos(slot)
        assert result == ["engine", "pages", "work-casehub"]

    def test_excludes_m2_and_attic(self, tmp_path):
        slot = tmp_path / "slot1"
        slot.mkdir()
        for name in ["engine", ".m2", "attic"]:
            d = slot / name
            d.mkdir()
            (d / ".git").mkdir()
        result = slot_manager.get_all_slot_repos(slot)
        assert result == ["engine"]

    def test_excludes_non_git_dirs(self, tmp_path):
        slot = tmp_path / "slot1"
        slot.mkdir()
        (slot / "engine").mkdir()
        (slot / "engine" / ".git").mkdir()
        (slot / "random-dir").mkdir()
        result = slot_manager.get_all_slot_repos(slot)
        assert result == ["engine"]

    def test_get_slot_repos_still_excludes_workspace(self, tmp_path):
        slot = tmp_path / "slot1"
        slot.mkdir()
        for name in ["engine", "work-casehub"]:
            d = slot / name
            d.mkdir()
            (d / ".git").mkdir()
        result = slot_manager.get_slot_repos(slot)
        assert result == ["engine"]


class TestConfigureSlotRemotes:
    def test_direct_model_renames_origin_adds_github(self, tmp_path):
        original = init_repo(tmp_path / "original")
        subprocess.run(["git", "-C", str(original), "remote", "add", "origin",
                        "https://github.com/user/repo.git"], capture_output=True)
        clone = tmp_path / "clone"
        subprocess.run(["git", "clone", str(original), str(clone)], capture_output=True)

        result = slot_manager.configure_slot_remotes(clone, original)

        rc, local_url, _ = slot_manager.run_cmd(
            ["git", "-C", str(clone), "remote", "get-url", "local"])
        assert rc == 0
        assert str(original) in local_url.strip()

        rc, origin_url, _ = slot_manager.run_cmd(
            ["git", "-C", str(clone), "remote", "get-url", "origin"])
        assert rc == 0
        assert origin_url.strip() == "https://github.com/user/repo.git"

        assert result["upstream"] == ""

    def test_fork_model_adds_upstream(self, tmp_path):
        original = init_repo(tmp_path / "original")
        subprocess.run(["git", "-C", str(original), "remote", "add", "origin",
                        "https://github.com/mdproctor/repo.git"], capture_output=True)
        subprocess.run(["git", "-C", str(original), "remote", "add", "upstream",
                        "https://github.com/casehubio/repo.git"], capture_output=True)
        clone = tmp_path / "clone"
        subprocess.run(["git", "clone", str(original), str(clone)], capture_output=True)

        result = slot_manager.configure_slot_remotes(clone, original)

        rc, origin_url, _ = slot_manager.run_cmd(
            ["git", "-C", str(clone), "remote", "get-url", "origin"])
        assert origin_url.strip() == "https://github.com/mdproctor/repo.git"

        rc, upstream_url, _ = slot_manager.run_cmd(
            ["git", "-C", str(clone), "remote", "get-url", "upstream"])
        assert rc == 0
        assert upstream_url.strip() == "https://github.com/casehubio/repo.git"

        assert result["upstream"] == "https://github.com/casehubio/repo.git"

    def test_no_remotes_on_original_skips(self, tmp_path):
        original = init_repo(tmp_path / "original")
        clone = tmp_path / "clone"
        subprocess.run(["git", "clone", str(original), str(clone)], capture_output=True)

        result = slot_manager.configure_slot_remotes(clone, original)
        assert result["origin"] == ""


class TestConfigureUpdateInstead:
    def test_sets_config_on_original(self, tmp_path):
        original = init_repo(tmp_path / "original")
        slot_manager.configure_update_instead(original)
        rc, value, _ = slot_manager.run_cmd(
            ["git", "-C", str(original), "config", "receive.denyCurrentBranch"])
        assert rc == 0
        assert value.strip() == "updateInstead"

    def test_idempotent(self, tmp_path):
        original = init_repo(tmp_path / "original")
        slot_manager.configure_update_instead(original)
        slot_manager.configure_update_instead(original)
        rc, value, _ = slot_manager.run_cmd(
            ["git", "-C", str(original), "config", "receive.denyCurrentBranch"])
        assert value.strip() == "updateInstead"


class TestMergeSlotRelaxedPreflight:
    def _setup_slot(self, tmp_path):
        family = tmp_path / "family"
        family.mkdir()
        original = _init_repo_with_remote(family / "engine")
        slot_manager.configure_update_instead(original)

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
            result = slot_manager.merge_slot(family, 1)
        assert "not_on_main" not in captured.getvalue()

    def test_dirty_worktree_on_main_blocks(self, tmp_path):
        family, slot_dir, original, clone = self._setup_slot(tmp_path)
        (original / "dirty.txt").write_text("uncommitted")

        import io
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            result = slot_manager.merge_slot(family, 1)
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
            result = slot_manager.merge_slot(family, 1)

        assert "SYNC=pushed" in captured.getvalue()
        bare_path = family / ".engine-bare.git"
        rc, bare_log, _ = slot_manager.run_cmd(
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
            result = slot_manager.merge_slot(family, 1)
        assert "dirty_worktree" not in captured.getvalue()


class TestMergeSlotDualPush:
    def _setup_full_slot(self, tmp_path):
        """Create a slot with project + workspace, using real bare repos."""
        family = tmp_path / "family"
        family.mkdir()

        proj_orig = _init_repo_with_remote(family / "engine")
        slot_manager.configure_update_instead(proj_orig)

        ws_orig = _init_repo_with_remote(family / "work-hub")
        slot_manager.configure_update_instead(ws_orig)

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

    def test_workspace_repo_skipped_by_merge(self, tmp_path, capsys):
        """Workspace repos are skipped — artifacts promoted via close_artifacts, not merge-slot."""
        family, slot_dir, proj_orig, ws_orig = self._setup_full_slot(tmp_path)
        result = slot_manager.merge_slot(family, 1)

        assert result == 0
        captured = capsys.readouterr().out
        assert "SKIPPED_WORKSPACE=work-hub" in captured

        rc, ws_log, _ = slot_manager.run_cmd(
            ["git", "-C", str(ws_orig), "log", "--oneline"])
        assert "journal" not in ws_log.lower()

        landed = (slot_dir / ".landed").read_text()
        assert "work-hub" not in landed
        assert "engine:" in landed

    def test_github_push_failure_is_warning_not_error(self, tmp_path):
        """If original can't push to GitHub, local push succeeded — warn, don't block."""
        family, slot_dir, proj_orig, ws_orig = self._setup_full_slot(tmp_path)
        original_run_cmd = slot_manager.run_cmd

        def mock_github_fail(args, cwd=None):
            if "push" in args and "origin" in args and "main" in args:
                path = args[2] if len(args) > 2 else ""
                if str(family / "engine") in path or str(family / "work-hub") in path:
                    return (1, "", "network error")
            return original_run_cmd(args, cwd)

        with patch("slot_manager.run_cmd", side_effect=mock_github_fail):
            result = slot_manager.merge_slot(family, 1)

        assert result == 0
        rc, log, _ = original_run_cmd(
            ["git", "-C", str(proj_orig), "log", "--oneline"])
        assert "feature" in log.lower()

    def test_local_push_failure_blocks(self, tmp_path):
        """If slot can't push to original, hard stop — work not landed."""
        family, slot_dir, proj_orig, ws_orig = self._setup_full_slot(tmp_path)
        original_run_cmd = slot_manager.run_cmd

        def mock_local_fail(args, cwd=None):
            if "push" in args and "local" in args and "main" in args:
                return (1, "", "rejected")
            return original_run_cmd(args, cwd)

        with patch("slot_manager.run_cmd", side_effect=mock_local_fail):
            result = slot_manager.merge_slot(family, 1)

        assert result == 1


class TestCreateSlotRemoteConfig:
    def test_create_slot_configures_remotes_on_project_clone(self, tmp_path):
        family = tmp_path / "family"
        family.mkdir()
        repo = init_repo(family / "engine")
        subprocess.run(["git", "-C", str(repo), "remote", "add", "origin",
                        "https://github.com/user/engine.git"], capture_output=True)

        with patch("slot_manager.sync_main"):
            result = slot_manager.create_slot(family, ["engine"], "feature-1",
                                              "1", "user/engine", "1", "test")

        clone = family / "slots" / str(result["slot_number"]) / "engine"
        rc, local_url, _ = slot_manager.run_cmd(
            ["git", "-C", str(clone), "remote", "get-url", "local"])
        assert rc == 0

        rc, origin_url, _ = slot_manager.run_cmd(
            ["git", "-C", str(clone), "remote", "get-url", "origin"])
        assert rc == 0
        assert origin_url.strip() == "https://github.com/user/engine.git"

        rc, value, _ = slot_manager.run_cmd(
            ["git", "-C", str(repo), "config", "receive.denyCurrentBranch"])
        assert rc == 0
        assert value.strip() == "updateInstead"


class TestMigrateRemotes:
    def test_migrates_active_slot(self, tmp_path):
        family = tmp_path / "family"
        family.mkdir()
        original = _init_repo_with_remote(family / "engine")

        slot_dir = family / "slots" / "1"
        slot_dir.mkdir(parents=True)
        clone = slot_dir / "engine"
        subprocess.run(["git", "clone", "--shared", str(original), str(clone)],
                       capture_output=True, check=True)
        (slot_dir / ".slot").write_text("# Slot 1\n## Repos\n- engine\n")

        count = slot_manager.migrate_remotes(family)
        assert count > 0

        rc, _, _ = slot_manager.run_cmd(
            ["git", "-C", str(clone), "remote", "get-url", "local"])
        assert rc == 0

        bare_path = family / ".engine-bare.git"
        rc, url, _ = slot_manager.run_cmd(
            ["git", "-C", str(clone), "remote", "get-url", "origin"])
        assert rc == 0
        assert str(bare_path) in url.strip()

    def test_skips_archived_slots(self, tmp_path):
        family = tmp_path / "family"
        family.mkdir()
        original = _init_repo_with_remote(family / "engine")

        attic = family / "slots" / "attic" / "1"
        attic.mkdir(parents=True)
        clone = attic / "engine"
        subprocess.run(["git", "clone", "--shared", str(original), str(clone)],
                       capture_output=True, check=True)

        count = slot_manager.migrate_remotes(family)
        assert count == 0

    def test_idempotent(self, tmp_path):
        family = tmp_path / "family"
        family.mkdir()
        original = _init_repo_with_remote(family / "engine")

        slot_dir = family / "slots" / "1"
        slot_dir.mkdir(parents=True)
        clone = slot_dir / "engine"
        subprocess.run(["git", "clone", "--shared", str(original), str(clone)],
                       capture_output=True, check=True)
        (slot_dir / ".slot").write_text("# Slot 1\n## Repos\n- engine\n")

        count1 = slot_manager.migrate_remotes(family)
        count2 = slot_manager.migrate_remotes(family)
        assert count1 > 0
        assert count2 == 0


class TestGetFamilyRepoNames:
    def test_finds_git_repos(self, tmp_path):
        family = tmp_path / "casehub"
        family.mkdir()
        init_repo(family / "engine")
        init_repo(family / "work")
        (family / "not-a-repo").mkdir()
        result = slot_manager._get_family_repo_names(family)
        assert result == {"engine", "work"}

    def test_excludes_slots_and_m2(self, tmp_path):
        family = tmp_path / "casehub"
        family.mkdir()
        init_repo(family / "engine")
        (family / "slots").mkdir()
        (family / ".m2").mkdir()
        result = slot_manager._get_family_repo_names(family)
        assert "slots" not in result
        assert ".m2" not in result
        assert "engine" in result

    def test_empty_family(self, tmp_path):
        family = tmp_path / "casehub"
        family.mkdir()
        result = slot_manager._get_family_repo_names(family)
        assert result == set()


class TestCreateSlotCollisionFamily:
    @patch("slot_manager.run_cmd")
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

        with patch("slot_manager.resolve_workspace_source") as mock_resolve:
            mock_resolve.return_value = (ws_engine, "wsp-casehub-engine")
            result = slot_manager.create_slot(
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


class TestValidateSlotWksp:
    def test_passes_when_symlinks_resolve(self, tmp_path):
        """All repo clones have working wksp/ symlinks."""
        family = tmp_path / "casehub"
        family.mkdir()
        original = init_repo(family / "engine")
        ws_dir = tmp_path / "workspace"
        ws_dir.mkdir()
        (ws_dir / "engine").mkdir()
        (original / "wksp").symlink_to(ws_dir / "engine")

        slot_dir = tmp_path / "slots" / "1"
        slot_dir.mkdir(parents=True)
        clone = init_repo(slot_dir / "engine")
        ws_slot = slot_dir / "work" / "engine"
        ws_slot.mkdir(parents=True)
        (clone / "wksp").symlink_to(os.path.relpath(ws_slot, clone))

        failures = slot_manager.validate_slot_wksp(slot_dir)
        assert failures == []

    def test_fails_when_symlink_dangling(self, tmp_path):
        """wksp/ points to a non-existent directory."""
        family = tmp_path / "casehub"
        family.mkdir()
        original = init_repo(family / "engine")
        (original / "wksp").symlink_to("/nonexistent/path")

        slot_dir = tmp_path / "slots" / "1"
        slot_dir.mkdir(parents=True)
        clone = init_repo(slot_dir / "engine")
        (clone / "wksp").symlink_to("/nonexistent/path")

        failures = slot_manager.validate_slot_wksp(slot_dir)
        assert len(failures) == 1
        assert "engine" in failures[0]

    def test_fails_when_symlink_missing(self, tmp_path):
        """Original has wksp/ but clone doesn't."""
        family = tmp_path / "casehub"
        family.mkdir()
        original = init_repo(family / "engine")
        ws_dir = tmp_path / "workspace"
        ws_dir.mkdir()
        (original / "wksp").symlink_to(ws_dir)

        slot_dir = tmp_path / "slots" / "1"
        slot_dir.mkdir(parents=True)
        clone = init_repo(slot_dir / "engine")

        subprocess.run(["git", "-C", str(clone), "remote", "add", "local", str(original)], capture_output=True)

        failures = slot_manager.validate_slot_wksp(slot_dir)
        assert len(failures) == 1
        assert "missing" in failures[0].lower()

    def test_passes_when_original_has_no_wksp(self, tmp_path):
        """Original repo has no wksp/ — nothing to validate."""
        slot_dir = tmp_path / "slots" / "1"
        slot_dir.mkdir(parents=True)
        init_repo(slot_dir / "engine")

        failures = slot_manager.validate_slot_wksp(slot_dir)
        assert failures == []

    def test_scoped_to_specific_repos(self, tmp_path):
        """When repo_names is provided, only those repos are checked."""
        slot_dir = tmp_path / "slots" / "1"
        slot_dir.mkdir(parents=True)
        init_repo(slot_dir / "engine")
        bad = init_repo(slot_dir / "iot")
        (bad / "wksp").symlink_to("/nonexistent")

        failures = slot_manager.validate_slot_wksp(slot_dir, repo_names=["engine"])
        assert failures == []


class TestCreateSlotWkspValidation:
    @patch("slot_manager.validate_slot_wksp")
    @patch("slot_manager.run_cmd")
    def test_create_slot_exits_on_broken_wksp(self, mock_cmd, mock_validate, tmp_path, capsys):
        """create_slot must fail if post-creation validation finds broken wksp/."""
        family = tmp_path / "casehub"
        family.mkdir()
        init_repo(family / "engine")

        mock_cmd.return_value = (0, "", "")
        mock_validate.return_value = ["engine: wksp/ symlink dangling -> /nonexistent"]

        with pytest.raises(SystemExit):
            slot_manager.create_slot(
                family_root=family,
                repos=["engine"],
                branch="issue-99-test",
                issue="99",
                issue_repo="casehubio/engine",
                covers="99",
                context="test",
            )
        captured = capsys.readouterr()
        assert "ERROR=wksp_validation_failed" in captured.out

    @patch("slot_manager.validate_slot_wksp")
    @patch("slot_manager.run_cmd")
    def test_create_slot_succeeds_when_wksp_ok(self, mock_cmd, mock_validate, tmp_path):
        """create_slot succeeds when validation passes."""
        family = tmp_path / "casehub"
        family.mkdir()
        init_repo(family / "engine")

        mock_cmd.return_value = (0, "", "")
        mock_validate.return_value = []

        result = slot_manager.create_slot(
            family_root=family,
            repos=["engine"],
            branch="issue-99-test",
            issue="99",
            issue_repo="casehubio/engine",
            covers="99",
            context="test",
        )
        assert result["slot_number"] >= 1


class TestListSlotsWkspHealth:
    def test_wksp_ok_true_when_no_wksp(self, tmp_path):
        """Repos without workspace integration are wksp_ok=True."""
        slot_dir = tmp_path / "slots" / "1"
        slot_dir.mkdir(parents=True)
        (slot_dir / ".slot").write_text("# Slot 1 — test\n")
        init_repo(slot_dir / "engine")
        slots = slot_manager.list_slots(tmp_path)
        assert len(slots) == 1
        assert slots[0]["wksp_ok"] is True

    def test_wksp_ok_false_when_dangling(self, tmp_path):
        """Broken wksp/ symlink surfaces as wksp_ok=False."""
        slot_dir = tmp_path / "slots" / "1"
        slot_dir.mkdir(parents=True)
        (slot_dir / ".slot").write_text("# Slot 1 — test\n")
        clone = init_repo(slot_dir / "engine")
        (clone / "wksp").symlink_to("/nonexistent")
        slots = slot_manager.list_slots(tmp_path)
        assert len(slots) == 1
        assert slots[0]["wksp_ok"] is False


class TestAddRepoWorkspaceRemotes:
    @patch("slot_manager.configure_slot_remotes")
    @patch("slot_manager.run_cmd")
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

        slot_manager.write_slot_md(
            slot_dir, 1, ["engine"], "test-branch", "42",
            "Org/repo", "42", "test",
        )

        mock_cmd.return_value = (0, "", "")
        mock_configure.return_value = {"origin": "", "upstream": "", "local": ""}

        with patch("slot_manager.resolve_workspace_source") as mock_resolve:
            mock_resolve.return_value = (ws_iot, "wsp-casehub-iot")
            slot_manager.add_repo(family, 1, "iot", "test-branch")

        ws_calls = [
            c for c in mock_configure.call_args_list
            if "wsp-" in str(c.args[0])
        ]
        assert len(ws_calls) >= 1, (
            "add_repo did not call configure_slot_remotes on workspace clone"
        )