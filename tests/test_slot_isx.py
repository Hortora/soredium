"""Tests for work-slot/slot_isx.py"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

skill_dir = Path(__file__).parent.parent / "work-slot"
sys.path.insert(0, str(skill_dir))

import slot_isx
from slot_test_helpers import init_repo


class TestIsxHelpers:
    def test_check_isx_available_found(self):
        with patch("shutil.which", return_value="/opt/homebrew/bin/isx"):
            assert slot_isx._check_isx_available() is True

    def test_check_isx_available_missing(self):
        with patch("shutil.which", return_value=None):
            assert slot_isx._check_isx_available() is False

    def test_truncate_short_name(self):
        assert slot_isx._truncate_instance_name("issue-42-fix") == "issue-42-fix"

    def test_truncate_long_name(self):
        long_name = "issue-223-isx-isolation-for-slots-with-very-long-description-that-exceeds-limit"
        result = slot_isx._truncate_instance_name(long_name, max_len=63)
        assert len(result) <= 63
        assert result.startswith("issue-223-isx-isolation")

    def test_truncate_strips_trailing_hyphens(self):
        name = "a" * 60 + "---bcd"
        result = slot_isx._truncate_instance_name(name, max_len=63)
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
        with patch("slot_isx.run_cmd", return_value=(0, "", "")) as mock:
            slot_isx._teardown_isx(tmp_path)
            mock.assert_called_once_with(["isx", "destroy", "test-instance"])

    def test_teardown_non_isx_slot(self, tmp_path):
        (tmp_path / ".slot").write_text(
            "# Slot 1 — test\n\n## Repos\n- soredium\n\n"
            "## Created\n2026-08-12, branch: test\n"
        )
        with patch("slot_isx.run_cmd") as mock:
            slot_isx._teardown_isx(tmp_path)
            mock.assert_not_called()

    def test_teardown_destroy_fails_warns(self, tmp_path, capsys):
        (tmp_path / ".slot").write_text(
            "# Slot 1 — test\n\n## Issue\nOrg/repo#42\nCovers: 42\n\n"
            "## Repos\n- engine (primary)\n\n"
            "## Isolation\ntype: isx\n"
            "instance: gone-instance\ntemplate: tpl-java\n\n"
            "## Created\n2026-08-12, branch: test\n"
        )
        with patch("slot_isx.run_cmd", return_value=(1, "", "not found")):
            slot_isx._teardown_isx(tmp_path)
            out = capsys.readouterr().out
            assert "WARN" in out


class TestWireIsxRemotes:
    def test_wire_remotes_adds_per_repo(self, tmp_path):
        repos = ["engine", "iot"]
        for r in repos:
            repo_dir = tmp_path / r
            repo_dir.mkdir()
            (repo_dir / ".git").mkdir()
        with patch("slot_isx.run_cmd", return_value=(0, "", "")) as mock:
            slot_isx._wire_isx_remotes(tmp_path, repos, "test-instance")
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
        with patch("slot_isx.run_cmd") as mock:
            slot_isx._wire_isx_remotes(tmp_path, ["nonexistent"], "test-instance")
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
        with patch("slot_isx.run_cmd") as mock:
            mock.return_value = (0, "", "")
            result = slot_isx.sync_isx(slot_dir)
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
        result = slot_isx.sync_isx(slot_dir)
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
        with patch("slot_isx.run_cmd", side_effect=side_effect):
            result = slot_isx.sync_isx(slot_dir)
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
        with patch("slot_isx.run_cmd", side_effect=side_effect):
            result = slot_isx.sync_isx(slot_dir)
        assert result == 0
