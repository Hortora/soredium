#!/usr/bin/env python3
"""Unit, integration, and CLI tests for augment_entry.py."""

import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
from augment_entry import (
    create_augmentation, list_augmentations, validate_augmentation,
)

CLI = Path(__file__).parent.parent / 'scripts' / 'augment_entry.py'
VALID_TYPES = ('context', 'correction', 'update')


def run_cli(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI)] + list(args),
        capture_output=True, text=True
    )


class TestCreateAugmentation(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.augment_dir = Path(self.tmp.name) / '_augment'
        self.augment_dir.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_creates_file(self):
        path = create_augmentation(
            self.augment_dir, 'GE-20260414-aabbcc',
            'jvm-garden', 'context', 'Some private context'
        )
        self.assertTrue(path.exists())

    def test_file_contains_target_id(self):
        path = create_augmentation(
            self.augment_dir, 'GE-20260414-aabbcc',
            'jvm-garden', 'context', 'Some private context'
        )
        self.assertIn('GE-20260414-aabbcc', path.read_text())

    def test_file_contains_target_garden(self):
        path = create_augmentation(
            self.augment_dir, 'GE-20260414-aabbcc',
            'jvm-garden', 'context', 'Some private context'
        )
        self.assertIn('jvm-garden', path.read_text())

    def test_file_contains_augment_type(self):
        path = create_augmentation(
            self.augment_dir, 'GE-20260414-aabbcc',
            'jvm-garden', 'correction', 'Fix to parent entry'
        )
        self.assertIn('correction', path.read_text())

    def test_file_contains_content(self):
        path = create_augmentation(
            self.augment_dir, 'GE-20260414-aabbcc',
            'jvm-garden', 'context', 'Secret internal note'
        )
        self.assertIn('Secret internal note', path.read_text())

    def test_filename_includes_target_id(self):
        path = create_augmentation(
            self.augment_dir, 'GE-20260414-aabbcc',
            'jvm-garden', 'context', 'Note'
        )
        self.assertIn('GE-20260414-aabbcc', path.name)

    def test_all_valid_augment_types_accepted(self):
        for i, aug_type in enumerate(VALID_TYPES):
            path = create_augmentation(
                self.augment_dir, f'GE-20260414-id{i:04d}',
                'jvm-garden', aug_type, f'Content for {aug_type}'
            )
            self.assertTrue(path.exists())

    def test_has_yaml_frontmatter(self):
        path = create_augmentation(
            self.augment_dir, 'GE-20260414-aabbcc',
            'jvm-garden', 'context', 'Note'
        )
        content = path.read_text()
        self.assertTrue(content.startswith('---\n'))
        self.assertIn('\n---\n', content)


class TestListAugmentations(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.augment_dir = Path(self.tmp.name) / '_augment'
        self.augment_dir.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_empty_dir_returns_empty_list(self):
        self.assertEqual(list_augmentations(self.augment_dir), [])

    def test_single_augmentation(self):
        create_augmentation(self.augment_dir, 'GE-20260414-aabbcc',
                            'jvm-garden', 'context', 'Note')
        result = list_augmentations(self.augment_dir)
        self.assertEqual(len(result), 1)

    def test_returns_target_field(self):
        create_augmentation(self.augment_dir, 'GE-20260414-aabbcc',
                            'jvm-garden', 'context', 'Note')
        result = list_augmentations(self.augment_dir)
        self.assertEqual(result[0]['target'], 'GE-20260414-aabbcc')

    def test_returns_target_garden_field(self):
        create_augmentation(self.augment_dir, 'GE-20260414-aabbcc',
                            'jvm-garden', 'context', 'Note')
        result = list_augmentations(self.augment_dir)
        self.assertEqual(result[0]['target_garden'], 'jvm-garden')

    def test_returns_augment_type_field(self):
        create_augmentation(self.augment_dir, 'GE-20260414-aabbcc',
                            'jvm-garden', 'correction', 'Note')
        result = list_augmentations(self.augment_dir)
        self.assertEqual(result[0]['augment_type'], 'correction')

    def test_multiple_augmentations(self):
        for i in range(3):
            create_augmentation(self.augment_dir, f'GE-20260414-id{i:04d}',
                                'jvm-garden', 'context', f'Note {i}')
        self.assertEqual(len(list_augmentations(self.augment_dir)), 3)

    def test_skips_readme(self):
        (self.augment_dir / 'README.md').write_text('# README\n')
        self.assertEqual(list_augmentations(self.augment_dir), [])


class TestValidateAugmentation(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.augment_dir = Path(self.tmp.name) / '_augment'
        self.augment_dir.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_valid_file_no_errors(self):
        path = create_augmentation(self.augment_dir, 'GE-20260414-aabbcc',
                                   'jvm-garden', 'context', 'Valid note')
        errors, _ = validate_augmentation(path)
        self.assertEqual(errors, [])

    def test_missing_target_field(self):
        p = self.augment_dir / 'bad.md'
        p.write_text('---\ntarget_garden: jvm-garden\naugment_type: context\n---\n\nNote\n')
        errors, _ = validate_augmentation(p)
        self.assertTrue(any('target' in e for e in errors))

    def test_missing_target_garden_field(self):
        p = self.augment_dir / 'bad2.md'
        p.write_text('---\ntarget: GE-20260414-aabbcc\naugment_type: context\n---\n\nNote\n')
        errors, _ = validate_augmentation(p)
        self.assertTrue(any('target_garden' in e for e in errors))

    def test_invalid_augment_type(self):
        p = self.augment_dir / 'bad3.md'
        p.write_text('---\ntarget: GE-20260414-aabbcc\ntarget_garden: jvm-garden\n'
                     'augment_type: bogus\n---\n\nNote\n')
        errors, _ = validate_augmentation(p)
        self.assertTrue(any('augment_type' in e for e in errors))

    def test_no_frontmatter_returns_error(self):
        p = self.augment_dir / 'bad4.md'
        p.write_text('Just plain text, no frontmatter\n')
        errors, _ = validate_augmentation(p)
        self.assertGreater(len(errors), 0)


class TestAugmentEntryCLI(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.augment_dir = Path(self.tmp.name) / '_augment'
        self.augment_dir.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_subcommand(self):
        result = run_cli(
            'create', 'GE-20260414-aabbcc',
            '--garden', 'jvm-garden',
            '--type', 'context',
            '--content', 'Private note here',
            '--augment-dir', str(self.augment_dir),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(list(self.augment_dir.glob('*.md'))), 1)

    def test_list_subcommand_empty(self):
        result = run_cli('list', '--augment-dir', str(self.augment_dir))
        self.assertEqual(result.returncode, 0)
        self.assertIn('0', result.stdout)

    def test_list_subcommand_after_create(self):
        create_augmentation(self.augment_dir, 'GE-20260414-aabbcc',
                            'jvm-garden', 'context', 'Note')
        result = run_cli('list', '--augment-dir', str(self.augment_dir))
        self.assertEqual(result.returncode, 0)
        self.assertIn('GE-20260414-aabbcc', result.stdout)

    def test_validate_subcommand_valid(self):
        path = create_augmentation(self.augment_dir, 'GE-20260414-aabbcc',
                                   'jvm-garden', 'context', 'Note')
        result = run_cli('validate', str(path))
        self.assertEqual(result.returncode, 0)
        self.assertIn('valid', result.stdout.lower())

    def test_validate_subcommand_invalid(self):
        p = self.augment_dir / 'bad.md'
        p.write_text('no frontmatter\n')
        result = run_cli('validate', str(p))
        self.assertEqual(result.returncode, 1)

    def test_invalid_type_exits_nonzero(self):
        result = run_cli(
            'create', 'GE-20260414-aabbcc',
            '--garden', 'jvm-garden',
            '--type', 'bogus-type',
            '--content', 'Note',
            '--augment-dir', str(self.augment_dir),
        )
        self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
