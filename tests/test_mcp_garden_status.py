#!/usr/bin/env python3
"""Unit and integration tests for mcp_garden_status.py."""

import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
from mcp_garden_status import get_status, count_entries, parse_garden_md_metadata


def make_git_garden(tmp: Path, entries_since_sweep: int = 3) -> Path:
    garden = tmp / 'garden'
    garden.mkdir(parents=True, exist_ok=True)
    for cmd in [
        ['git', 'init', str(garden)],
        ['git', '-C', str(garden), 'config', 'user.email', 'test@test.com'],
        ['git', '-C', str(garden), 'config', 'user.name', 'Test'],
    ]:
        subprocess.run(cmd, check=True, capture_output=True)

    (garden / 'GARDEN.md').write_text(
        f'# test-garden\n\n'
        f'**Last assigned ID:** GE-0002\n'
        f'**Last full DEDUPE sweep:** 2026-04-10\n'
        f'**Entries merged since last sweep:** {entries_since_sweep}\n'
        f'**Drift threshold:** 10\n'
        f'**Last staleness review:** 2026-04-01\n'
    )
    (garden / 'java').mkdir()
    for i in range(1, 3):
        (garden / 'java' / f'GE-2026041{i}-aa000{i}.md').write_text(
            f'---\nid: GE-2026041{i}-aa000{i}\ntitle: "Entry {i}"\ntype: gotcha\n'
            f'domain: java\nstack: "Java"\ntags: [java]\nscore: 10\n'
            f'verified: true\nstaleness_threshold: 730\nsubmitted: 2026-04-14\n---\n\n'
            f'## Entry {i}\n\n**ID:** GE-2026041{i}-aa000{i}\n'
        )
    subprocess.run(['git', '-C', str(garden), 'add', '.'], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(garden), 'commit', '-m', 'init'],
                   check=True, capture_output=True)
    return garden


class TestParseGardenMdMetadata(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.garden = make_git_garden(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_reads_drift_counter(self):
        meta = parse_garden_md_metadata(self.garden)
        self.assertEqual(meta['drift'], 3)

    def test_reads_threshold(self):
        meta = parse_garden_md_metadata(self.garden)
        self.assertEqual(meta['threshold'], 10)

    def test_reads_last_sweep(self):
        meta = parse_garden_md_metadata(self.garden)
        self.assertEqual(meta['last_sweep'], '2026-04-10')

    def test_reads_last_staleness_review(self):
        meta = parse_garden_md_metadata(self.garden)
        self.assertEqual(meta['last_staleness_review'], '2026-04-01')

    def test_missing_garden_md_returns_defaults(self):
        tmp = Path(self.tmp.name) / 'empty'
        tmp.mkdir()
        for cmd in [
            ['git', 'init', str(tmp)],
            ['git', '-C', str(tmp), 'config', 'user.email', 'test@test.com'],
            ['git', '-C', str(tmp), 'config', 'user.name', 'Test'],
        ]:
            subprocess.run(cmd, check=True, capture_output=True)
        meta = parse_garden_md_metadata(tmp)
        self.assertEqual(meta['drift'], 0)
        self.assertEqual(meta['threshold'], 10)


class TestCountEntries(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.garden = make_git_garden(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_counts_yaml_entries(self):
        count = count_entries(self.garden)
        self.assertEqual(count, 2)

    def test_zero_entries_in_empty_garden(self):
        tmp = Path(self.tmp.name) / 'empty'
        tmp.mkdir()
        for cmd in [
            ['git', 'init', str(tmp)],
            ['git', '-C', str(tmp), 'config', 'user.email', 'test@test.com'],
            ['git', '-C', str(tmp), 'config', 'user.name', 'Test'],
        ]:
            subprocess.run(cmd, check=True, capture_output=True)
        (tmp / 'GARDEN.md').write_text('**Last assigned ID:** GE-0000\n')
        subprocess.run(['git', '-C', str(tmp), 'add', '.'], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(tmp), 'commit', '-m', 'init'],
                       check=True, capture_output=True)
        self.assertEqual(count_entries(tmp), 0)

    def test_does_not_count_control_files(self):
        # GARDEN.md, CHECKED.md, DISCARDED.md should not be counted
        count = count_entries(self.garden)
        self.assertEqual(count, 2)  # only the 2 java entries


class TestGetStatus(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.garden = make_git_garden(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_returns_dict(self):
        status = get_status(self.garden)
        self.assertIsInstance(status, dict)

    def test_has_entry_count(self):
        status = get_status(self.garden)
        self.assertIn('entry_count', status)
        self.assertEqual(status['entry_count'], 2)

    def test_has_drift(self):
        status = get_status(self.garden)
        self.assertIn('drift', status)
        self.assertEqual(status['drift'], 3)

    def test_has_threshold(self):
        status = get_status(self.garden)
        self.assertIn('threshold', status)

    def test_has_last_sweep(self):
        status = get_status(self.garden)
        self.assertIn('last_sweep', status)
        self.assertEqual(status['last_sweep'], '2026-04-10')

    def test_dedupe_recommended_when_above_threshold(self):
        garden = make_git_garden(Path(self.tmp.name) / 'high', entries_since_sweep=15)
        status = get_status(garden)
        self.assertTrue(status.get('dedupe_recommended', False))

    def test_dedupe_not_recommended_when_below_threshold(self):
        status = get_status(self.garden)
        self.assertFalse(status.get('dedupe_recommended', True))

    def test_has_garden_path(self):
        status = get_status(self.garden)
        self.assertIn('garden_path', status)

    def test_invalid_path_raises(self):
        with self.assertRaises(Exception):
            get_status(Path('/nonexistent/path/that/does/not/exist'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
