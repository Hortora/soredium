#!/usr/bin/env python3
"""
Unit tests for scripts/claude-skill

Tests sync-local, uninstall, and list commands.
Uses temporary directories — never touches the real ~/.claude/skills/.
"""

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from tests.test_base import DualTempDirTestCase
from importlib.machinery import SourceFileLoader

_script_path = Path(__file__).parent.parent / "scripts" / "claude-skill"
cs = SourceFileLoader("claude_skill", str(_script_path)).load_module()


def make_args(**kwargs) -> SimpleNamespace:
    defaults = {"all": False, "yes": True, "skills": None}
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def make_skill(directory: Path, name: str) -> Path:
    """Create a minimal skill directory with SKILL.md."""
    skill_dir = directory / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: >\n  Use when testing.\n---\n# {name}\n"
    )
    return skill_dir


# ---------------------------------------------------------------------------
# sync-local: updates installed skills
# ---------------------------------------------------------------------------

class TestSyncLocalUpdatesInstalled(DualTempDirTestCase):

    def _patch(self):
        return patch.multiple(cs, get_repo_root=lambda: self.repo,
                              SKILLS_DIR=self.skills)

    def test_updated_file_is_synced(self):
        make_skill(self.repo, "forage")
        installed = self.skills / "forage"
        installed.mkdir()
        (installed / "SKILL.md").write_text("old")

        with self._patch():
            cs.cmd_sync_local(make_args())

        self.assertNotEqual((self.skills / "forage" / "SKILL.md").read_text(), "old")

    def test_multiple_skills_all_updated(self):
        for name in ("forage", "harvest"):
            make_skill(self.repo, name)
            (self.skills / name).mkdir()
            (self.skills / name / "SKILL.md").write_text("old")

        with self._patch():
            cs.cmd_sync_local(make_args())

        for name in ("forage", "harvest"):
            self.assertNotEqual((self.skills / name / "SKILL.md").read_text(), "old")

    def test_supporting_files_are_synced(self):
        """submission-formats.md alongside SKILL.md is included in sync."""
        skill_dir = make_skill(self.repo, "forage")
        (skill_dir / "submission-formats.md").write_text("# formats")
        installed = self.skills / "forage"
        installed.mkdir()
        (installed / "SKILL.md").write_text("old")

        with self._patch():
            cs.cmd_sync_local(make_args())

        self.assertTrue((self.skills / "forage" / "submission-formats.md").exists())


# ---------------------------------------------------------------------------
# sync-local: skips uninstalled without --all
# ---------------------------------------------------------------------------

class TestSyncLocalSkipsUninstalled(DualTempDirTestCase):

    def _patch(self):
        return patch.multiple(cs, get_repo_root=lambda: self.repo,
                              SKILLS_DIR=self.skills)

    def test_uninstalled_skill_not_created(self):
        make_skill(self.repo, "forage")

        with self._patch():
            cs.cmd_sync_local(make_args())

        self.assertFalse((self.skills / "forage").exists())

    def test_installed_updated_uninstalled_skipped(self):
        make_skill(self.repo, "forage")
        make_skill(self.repo, "harvest")
        (self.skills / "forage").mkdir()
        (self.skills / "forage" / "SKILL.md").write_text("old")

        with self._patch():
            cs.cmd_sync_local(make_args())

        self.assertNotEqual((self.skills / "forage" / "SKILL.md").read_text(), "old")
        self.assertFalse((self.skills / "harvest").exists())


# ---------------------------------------------------------------------------
# sync-local: --all installs new skills
# ---------------------------------------------------------------------------

class TestSyncLocalAllFlag(DualTempDirTestCase):

    def _patch(self):
        return patch.multiple(cs, get_repo_root=lambda: self.repo,
                              SKILLS_DIR=self.skills)

    def test_new_skill_installed_with_all(self):
        make_skill(self.repo, "forage")

        with self._patch():
            cs.cmd_sync_local(make_args(**{"all": True}))

        self.assertTrue((self.skills / "forage" / "SKILL.md").exists())

    def test_all_updates_existing_and_installs_new(self):
        make_skill(self.repo, "forage")
        make_skill(self.repo, "harvest")
        (self.skills / "forage").mkdir()
        (self.skills / "forage" / "SKILL.md").write_text("old")

        with self._patch():
            cs.cmd_sync_local(make_args(**{"all": True}))

        self.assertNotEqual((self.skills / "forage" / "SKILL.md").read_text(), "old")
        self.assertTrue((self.skills / "harvest" / "SKILL.md").exists())


# ---------------------------------------------------------------------------
# sync-local: excluded directories are not synced as skills
# ---------------------------------------------------------------------------

class TestSyncLocalExclusions(DualTempDirTestCase):

    def _patch(self):
        return patch.multiple(cs, get_repo_root=lambda: self.repo,
                              SKILLS_DIR=self.skills)

    def test_scripts_dir_not_treated_as_skill(self):
        make_skill(self.repo, "forage")
        (self.skills / "forage").mkdir()
        (self.skills / "forage" / "SKILL.md").write_text("old")
        scripts = self.repo / "scripts"
        scripts.mkdir()
        (scripts / "SKILL.md").write_text("fake")  # scripts/ has SKILL.md but is excluded

        with self._patch():
            cs.cmd_sync_local(make_args(**{"all": True}))

        self.assertFalse((self.skills / "scripts").exists())

    def test_claude_plugin_dir_not_treated_as_skill(self):
        make_skill(self.repo, "forage")
        (self.skills / "forage").mkdir()
        (self.skills / "forage" / "SKILL.md").write_text("old")
        plugin = self.repo / ".claude-plugin"
        plugin.mkdir()
        (plugin / "SKILL.md").write_text("fake")

        with self._patch():
            cs.cmd_sync_local(make_args(**{"all": True}))

        self.assertFalse((self.skills / ".claude-plugin").exists())

    def test_empty_repo_exits_cleanly(self):
        with self._patch():
            cs.cmd_sync_local(make_args())  # should not raise

    def test_skills_dir_created_if_missing(self):
        nested = Path(self.skills_tmp.name) / "nested" / "path"
        make_skill(self.repo, "forage")

        with patch.multiple(cs, get_repo_root=lambda: self.repo,
                            SKILLS_DIR=nested):
            cs.cmd_sync_local(make_args(**{"all": True}))

        self.assertTrue(nested.exists())


# ---------------------------------------------------------------------------
# sync-local: --skills flag
# ---------------------------------------------------------------------------

class TestSyncLocalSkillsFlag(DualTempDirTestCase):

    def _patch(self):
        return patch.multiple(cs, get_repo_root=lambda: self.repo,
                              SKILLS_DIR=self.skills)

    def test_specific_skill_synced(self):
        make_skill(self.repo, "forage")
        make_skill(self.repo, "harvest")

        with self._patch():
            cs.cmd_sync_local(make_args(**{"skills": ["forage"]}))

        self.assertTrue((self.skills / "forage" / "SKILL.md").exists())
        self.assertFalse((self.skills / "harvest").exists())

    def test_unknown_skill_exits(self):
        make_skill(self.repo, "forage")

        with self._patch():
            with self.assertRaises(SystemExit) as ctx:
                cs.cmd_sync_local(make_args(**{"skills": ["nonexistent"]}))
        self.assertNotEqual(ctx.exception.code, 0)


# ---------------------------------------------------------------------------
# cmd_list
# ---------------------------------------------------------------------------

class TestCmdList(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.skills = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_lists_installed_skills(self):
        for name in ("forage", "harvest"):
            d = self.skills / name
            d.mkdir()
            (d / "SKILL.md").write_text("---\nname: x\n---\n")

        buf = io.StringIO()
        with patch.object(cs, "SKILLS_DIR", self.skills), redirect_stdout(buf):
            cs.cmd_list(SimpleNamespace())

        out = buf.getvalue()
        self.assertIn("forage", out)
        self.assertIn("harvest", out)

    def test_dirs_without_skill_md_not_listed(self):
        (self.skills / "random-dir").mkdir()

        buf = io.StringIO()
        with patch.object(cs, "SKILLS_DIR", self.skills), redirect_stdout(buf):
            cs.cmd_list(SimpleNamespace())

        self.assertIn("No skills installed", buf.getvalue())

    def test_no_skills_installed(self):
        buf = io.StringIO()
        with patch.object(cs, "SKILLS_DIR", self.skills), redirect_stdout(buf):
            cs.cmd_list(SimpleNamespace())

        self.assertIn("No skills installed", buf.getvalue())


# ---------------------------------------------------------------------------
# cmd_uninstall
# ---------------------------------------------------------------------------

class TestCmdUninstall(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.skills = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_removes_skill_directory(self):
        skill = self.skills / "forage"
        skill.mkdir()
        (skill / "SKILL.md").write_text("content")

        with patch.object(cs, "SKILLS_DIR", self.skills):
            cs.cmd_uninstall(SimpleNamespace(skill="forage"))

        self.assertFalse(skill.exists())

    def test_nonexistent_skill_exits(self):
        with patch.object(cs, "SKILLS_DIR", self.skills):
            with self.assertRaises(SystemExit) as ctx:
                cs.cmd_uninstall(SimpleNamespace(skill="nonexistent"))
        self.assertNotEqual(ctx.exception.code, 0)

    def test_removes_symlinked_skill(self):
        target = Path(self.tmp.name + "_target")
        target.mkdir()
        link = self.skills / "forage"
        link.symlink_to(target)

        with patch.object(cs, "SKILLS_DIR", self.skills):
            cs.cmd_uninstall(SimpleNamespace(skill="forage"))

        self.assertFalse(link.exists())
        target.rmdir()


# ---------------------------------------------------------------------------
# get_repo_root
# ---------------------------------------------------------------------------

class TestGetRepoRoot(unittest.TestCase):

    def test_is_parent_of_scripts(self):
        root = cs.get_repo_root()
        self.assertEqual(root, _script_path.parent.parent)
        self.assertTrue((root / "scripts").is_dir())


if __name__ == "__main__":
    unittest.main(verbosity=2)
