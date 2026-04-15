#!/usr/bin/env python3
"""Unit, integration, and CLI tests for garden_db_migrate.py."""

import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
from garden_db import init_db, load_checked_pairs, is_discarded, get_schema_version
from garden_db_migrate import migrate_checked_md, migrate_discarded_md, run_migration

CLI = Path(__file__).parent.parent / 'scripts' / 'garden_db_migrate.py'


def run_cli(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI)] + list(args),
        capture_output=True, text=True
    )


CHECKED_MD = """\
# Garden Duplicate Check Log

| Pair | Result | Date | Notes |
|------|--------|------|-------|
| GE-0001 × GE-0002 | distinct | 2026-04-10 | |
| GE-0003 × GE-0004 | related | 2026-04-11 | cross-referenced |
| GE-0005 × GE-0006 | duplicate-discarded | 2026-04-12 | GE-0005 kept |
| invalid-row | bogus | 2026-04-13 | should be skipped |
"""

DISCARDED_MD = """\
# Discarded Submissions

| Discarded | Conflicts With | Date | Reason |
|-----------|----------------|------|--------|
| GE-0006 | GE-0005 | 2026-04-12 | exact duplicate |
| GE-0007 | GE-0008 | 2026-04-13 | subset |
"""


class TestMigrateCheckedMd(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.garden = Path(self.tmp.name)
        init_db(self.garden)

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_file_returns_zero(self):
        self.assertEqual(migrate_checked_md(self.garden), 0)

    def test_empty_table_returns_zero(self):
        (self.garden / 'CHECKED.md').write_text(
            '| Pair | Result | Date | Notes |\n|---|---|---|---|\n')
        self.assertEqual(migrate_checked_md(self.garden), 0)

    def test_migrates_three_valid_rows(self):
        (self.garden / 'CHECKED.md').write_text(CHECKED_MD)
        self.assertEqual(migrate_checked_md(self.garden), 3)

    def test_invalid_result_skipped(self):
        (self.garden / 'CHECKED.md').write_text(CHECKED_MD)
        migrate_checked_md(self.garden)
        self.assertEqual(len(load_checked_pairs(self.garden)), 3)

    def test_pairs_accessible_after_migration(self):
        (self.garden / 'CHECKED.md').write_text(CHECKED_MD)
        migrate_checked_md(self.garden)
        pairs = load_checked_pairs(self.garden)
        self.assertIn('GE-0001 × GE-0002', pairs)
        self.assertIn('GE-0003 × GE-0004', pairs)
        self.assertIn('GE-0005 × GE-0006', pairs)

    def test_dry_run_does_not_write(self):
        (self.garden / 'CHECKED.md').write_text(CHECKED_MD)
        count = migrate_checked_md(self.garden, dry_run=True)
        self.assertEqual(count, 3)
        self.assertEqual(load_checked_pairs(self.garden), set())

    def test_idempotent_migration(self):
        (self.garden / 'CHECKED.md').write_text(CHECKED_MD)
        migrate_checked_md(self.garden)
        migrate_checked_md(self.garden)
        self.assertEqual(len(load_checked_pairs(self.garden)), 3)


class TestMigrateDiscardedMd(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.garden = Path(self.tmp.name)
        init_db(self.garden)

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_file_returns_zero(self):
        self.assertEqual(migrate_discarded_md(self.garden), 0)

    def test_empty_table_returns_zero(self):
        (self.garden / 'DISCARDED.md').write_text(
            '| Discarded | Conflicts With | Date | Reason |\n|---|---|---|---|\n')
        self.assertEqual(migrate_discarded_md(self.garden), 0)

    def test_migrates_two_valid_rows(self):
        (self.garden / 'DISCARDED.md').write_text(DISCARDED_MD)
        self.assertEqual(migrate_discarded_md(self.garden), 2)

    def test_entries_accessible_after_migration(self):
        (self.garden / 'DISCARDED.md').write_text(DISCARDED_MD)
        migrate_discarded_md(self.garden)
        self.assertTrue(is_discarded(self.garden, 'GE-0006'))
        self.assertTrue(is_discarded(self.garden, 'GE-0007'))

    def test_dry_run_does_not_write(self):
        (self.garden / 'DISCARDED.md').write_text(DISCARDED_MD)
        migrate_discarded_md(self.garden, dry_run=True)
        self.assertFalse(is_discarded(self.garden, 'GE-0006'))

    def test_header_row_skipped(self):
        (self.garden / 'DISCARDED.md').write_text(DISCARDED_MD)
        migrate_discarded_md(self.garden)
        self.assertFalse(is_discarded(self.garden, 'Discarded'))


class TestRunMigration(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.garden = Path(self.tmp.name)
        (self.garden / 'CHECKED.md').write_text(CHECKED_MD)
        (self.garden / 'DISCARDED.md').write_text(DISCARDED_MD)

    def tearDown(self):
        self.tmp.cleanup()

    def test_returns_correct_counts(self):
        result = run_migration(self.garden)
        self.assertEqual(result['checked'], 3)
        self.assertEqual(result['discarded'], 2)

    def test_creates_garden_db(self):
        run_migration(self.garden)
        self.assertTrue((self.garden / 'garden.db').exists())

    def test_renames_checked_md_to_bak(self):
        run_migration(self.garden)
        self.assertFalse((self.garden / 'CHECKED.md').exists())
        self.assertTrue((self.garden / 'CHECKED.md.bak').exists())

    def test_renames_discarded_md_to_bak(self):
        run_migration(self.garden)
        self.assertFalse((self.garden / 'DISCARDED.md').exists())
        self.assertTrue((self.garden / 'DISCARDED.md.bak').exists())

    def test_dry_run_no_db_created(self):
        run_migration(self.garden, dry_run=True)
        self.assertFalse((self.garden / 'garden.db').exists())

    def test_dry_run_no_rename(self):
        run_migration(self.garden, dry_run=True)
        self.assertTrue((self.garden / 'CHECKED.md').exists())
        self.assertTrue((self.garden / 'DISCARDED.md').exists())

    def test_schema_version_set(self):
        run_migration(self.garden)
        from garden_db import SCHEMA_VERSION
        self.assertEqual(get_schema_version(self.garden), SCHEMA_VERSION)

    def test_missing_source_files_ok(self):
        garden2 = Path(self.tmp.name) / 'empty'
        garden2.mkdir()
        result = run_migration(garden2)
        self.assertEqual(result['checked'], 0)
        self.assertEqual(result['discarded'], 0)
        self.assertTrue((garden2 / 'garden.db').exists())


class TestGardenDbMigrateCLI(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.garden = Path(self.tmp.name)
        (self.garden / 'CHECKED.md').write_text(CHECKED_MD)
        (self.garden / 'DISCARDED.md').write_text(DISCARDED_MD)

    def tearDown(self):
        self.tmp.cleanup()

    def test_exits_0(self):
        result = run_cli(str(self.garden))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_output_shows_counts(self):
        result = run_cli(str(self.garden))
        self.assertIn('3', result.stdout)
        self.assertIn('2', result.stdout)

    def test_dry_run_flag_no_writes(self):
        result = run_cli(str(self.garden), '--dry-run')
        self.assertEqual(result.returncode, 0)
        self.assertFalse((self.garden / 'garden.db').exists())

    def test_dry_run_output_mentions_dry_run(self):
        result = run_cli(str(self.garden), '--dry-run')
        self.assertIn('dry', result.stdout.lower())

    def test_invalid_path_exits_1(self):
        result = run_cli('/nonexistent/garden/path')
        self.assertEqual(result.returncode, 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
