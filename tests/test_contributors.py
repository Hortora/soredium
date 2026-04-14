#!/usr/bin/env python3
"""Unit and integration tests for contributors.py."""

import sys
import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

CONTRIBUTORS_SCRIPT = Path(__file__).parent.parent / 'scripts' / 'contributors.py'


def run_contributors(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CONTRIBUTORS_SCRIPT)] + list(args),
        capture_output=True, text=True
    )


def make_yaml_entry(path: Path, ge_id: str, title: str, score: int,
                    author: str = None, constraints: str = None,
                    has_alternatives: bool = False,
                    invalidation_triggers: str = None):
    path.parent.mkdir(parents=True, exist_ok=True)
    fm_lines = [
        '---',
        f'id: {ge_id}',
        f'title: "{title}"',
        'type: gotcha',
        'domain: tools',
        'stack: "Python"',
        'tags: [test]',
        f'score: {score}',
        'verified: true',
        'staleness_threshold: 730',
        'submitted: 2026-04-14',
    ]
    if author:
        fm_lines.append(f'author: "{author}"')
    if constraints:
        fm_lines.append(f'constraints: "{constraints}"')
    if invalidation_triggers:
        fm_lines.append(f'invalidation_triggers: "{invalidation_triggers}"')
    fm_lines.append('---')

    body = f'\n## {title}\n\n**ID:** {ge_id}\n**Symptom:** Something.\n\n### Fix\nThe fix.\n'
    if has_alternatives:
        body += '\n### Alternatives considered\n- Option A — rejected because slow\n'
    body += '\n### Why this is non-obvious\nThe insight.\n'

    path.write_text('\n'.join(fm_lines) + body)


# ── Unit tests: compute_contributors ─────────────────────────────────────────

class TestComputeContributors(unittest.TestCase):

    def setUp(self):
        from contributors import compute_contributors
        self.compute = compute_contributors

    def test_empty_entries_empty_result(self):
        self.assertEqual(self.compute([]), [])

    def test_single_entry_single_contributor(self):
        entries = [{'author': 'mdp', 'base_score': 12, 'bonus': 0,
                    'effective_score': 12, 'title': 'Test', 'ge_id': 'GE-0001',
                    'path': 'tools/GE-0001.md'}]
        result = self.compute(entries)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['author'], 'mdp')
        self.assertEqual(result[0]['entries'], 1)
        self.assertEqual(result[0]['avg_score'], 12.0)

    def test_same_author_entries_averaged(self):
        entries = [
            {'author': 'mdp', 'base_score': 10, 'bonus': 2, 'effective_score': 12,
             'title': 'Entry A', 'ge_id': 'GE-0001', 'path': 'tools/GE-0001.md'},
            {'author': 'mdp', 'base_score': 12, 'bonus': 0, 'effective_score': 12,
             'title': 'Entry B', 'ge_id': 'GE-0002', 'path': 'tools/GE-0002.md'},
            {'author': 'mdp', 'base_score': 8, 'bonus': 1, 'effective_score': 9,
             'title': 'Entry C', 'ge_id': 'GE-0003', 'path': 'tools/GE-0003.md'},
        ]
        result = self.compute(entries)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['entries'], 3)
        self.assertAlmostEqual(result[0]['avg_score'], 11.0, places=1)

    def test_multiple_authors_sorted_by_avg_score(self):
        entries = [
            {'author': 'xyz', 'base_score': 8, 'bonus': 0, 'effective_score': 8,
             'title': 'Low', 'ge_id': 'GE-0001', 'path': 'tools/GE-0001.md'},
            {'author': 'mdp', 'base_score': 14, 'bonus': 1, 'effective_score': 15,
             'title': 'High', 'ge_id': 'GE-0002', 'path': 'tools/GE-0002.md'},
        ]
        result = self.compute(entries)
        self.assertEqual(result[0]['author'], 'mdp')
        self.assertEqual(result[1]['author'], 'xyz')

    def test_best_entry_is_highest_effective_score(self):
        entries = [
            {'author': 'mdp', 'base_score': 10, 'bonus': 0, 'effective_score': 10,
             'title': 'Good', 'ge_id': 'GE-0001', 'path': 'tools/GE-0001.md'},
            {'author': 'mdp', 'base_score': 12, 'bonus': 3, 'effective_score': 15,
             'title': 'Best', 'ge_id': 'GE-0002', 'path': 'tools/GE-0002.md'},
            {'author': 'mdp', 'base_score': 9, 'bonus': 0, 'effective_score': 9,
             'title': 'Okay', 'ge_id': 'GE-0003', 'path': 'tools/GE-0003.md'},
        ]
        result = self.compute(entries)
        self.assertEqual(result[0]['best_entry']['title'], 'Best')

    def test_avg_bonus_computed_correctly(self):
        entries = [
            {'author': 'mdp', 'base_score': 10, 'bonus': 3, 'effective_score': 13,
             'title': 'Full WHY', 'ge_id': 'GE-0001', 'path': 'tools/GE-0001.md'},
            {'author': 'mdp', 'base_score': 10, 'bonus': 0, 'effective_score': 10,
             'title': 'No WHY', 'ge_id': 'GE-0002', 'path': 'tools/GE-0002.md'},
        ]
        result = self.compute(entries)
        self.assertAlmostEqual(result[0]['avg_bonus'], 1.5, places=1)

    def test_unknown_author_grouped(self):
        entries = [
            {'author': 'unknown', 'base_score': 10, 'bonus': 0, 'effective_score': 10,
             'title': 'Anon A', 'ge_id': 'GE-0001', 'path': 'tools/GE-0001.md'},
            {'author': 'unknown', 'base_score': 12, 'bonus': 1, 'effective_score': 13,
             'title': 'Anon B', 'ge_id': 'GE-0002', 'path': 'tools/GE-0002.md'},
        ]
        result = self.compute(entries)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['author'], 'unknown')
        self.assertEqual(result[0]['entries'], 2)


# ── Integration tests: load_garden_entries ────────────────────────────────────

class TestLoadGardenEntries(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.garden = Path(self.tmp.name)
        (self.garden / 'CHECKED.md').write_text('')

    def tearDown(self):
        self.tmp.cleanup()

    def test_finds_yaml_entries(self):
        from contributors import load_garden_entries
        make_yaml_entry(self.garden / 'tools' / 'GE-0001.md',
                        'GE-0001', 'Test entry', 10, author='mdp')
        entries = load_garden_entries(self.garden)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['author'], 'mdp')
        self.assertEqual(entries[0]['base_score'], 10)

    def test_skips_non_yaml_entries(self):
        from contributors import load_garden_entries
        (self.garden / 'tools').mkdir()
        (self.garden / 'tools' / 'GE-0042.md').write_text(
            '## Legacy\n\n**ID:** GE-0042\n'
        )
        entries = load_garden_entries(self.garden)
        self.assertEqual(len(entries), 0)

    def test_bonus_computed_from_why_fields(self):
        from contributors import load_garden_entries
        make_yaml_entry(
            self.garden / 'tools' / 'GE-0001.md',
            'GE-0001', 'Rich entry', 10, author='mdp',
            constraints='requires Java 17+',
            has_alternatives=True,
            invalidation_triggers='revisit if library changes'
        )
        entries = load_garden_entries(self.garden)
        self.assertEqual(entries[0]['bonus'], 3)
        self.assertEqual(entries[0]['effective_score'], 13)

    def test_unknown_author_when_no_field_no_git(self):
        from contributors import load_garden_entries
        make_yaml_entry(self.garden / 'tools' / 'GE-0001.md',
                        'GE-0001', 'No author', 10)
        entries = load_garden_entries(self.garden)
        self.assertEqual(entries[0]['author'], 'unknown')

    def test_skips_control_files(self):
        from contributors import load_garden_entries
        (self.garden / 'GARDEN.md').write_text('**Last legacy ID:** GE-0001\n')
        (self.garden / 'CONTRIBUTORS.md').write_text('# Contributors\n')
        make_yaml_entry(self.garden / 'tools' / 'GE-0001.md',
                        'GE-0001', 'Real entry', 10, author='mdp')
        entries = load_garden_entries(self.garden)
        self.assertEqual(len(entries), 1)

    def test_multiple_entries_multiple_authors(self):
        from contributors import load_garden_entries
        make_yaml_entry(self.garden / 'tools' / 'GE-0001.md',
                        'GE-0001', 'Entry A', 12, author='mdp')
        make_yaml_entry(self.garden / 'python' / 'GE-0002.md',
                        'GE-0002', 'Entry B', 10, author='xyz')
        entries = load_garden_entries(self.garden)
        self.assertEqual(len(entries), 2)
        authors = {e['author'] for e in entries}
        self.assertEqual(authors, {'mdp', 'xyz'})


# ── E2E tests: full pipeline ──────────────────────────────────────────────────

class TestContributorsCLI(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.garden = Path(self.tmp.name)
        (self.garden / 'CHECKED.md').write_text('')

    def tearDown(self):
        self.tmp.cleanup()

    def test_empty_garden_produces_contributors_md(self):
        result = run_contributors(str(self.garden))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.garden / 'CONTRIBUTORS.md').exists())

    def test_single_contributor_appears_in_table(self):
        make_yaml_entry(self.garden / 'tools' / 'GE-0001.md',
                        'GE-0001', 'Test entry', 12, author='mdp')
        run_contributors(str(self.garden))
        content = (self.garden / 'CONTRIBUTORS.md').read_text()
        self.assertIn('mdp', content)
        self.assertIn('| 1 |', content)

    def test_ranking_by_average_score(self):
        make_yaml_entry(self.garden / 'tools' / 'GE-0001.md',
                        'GE-0001', 'Low score', 8, author='xyz')
        make_yaml_entry(self.garden / 'tools' / 'GE-0002.md',
                        'GE-0002', 'High score', 14, author='mdp',
                        constraints='requires Java 17')
        run_contributors(str(self.garden))
        content = (self.garden / 'CONTRIBUTORS.md').read_text()
        mdp_idx = content.index('mdp')
        xyz_idx = content.index('xyz')
        self.assertLess(mdp_idx, xyz_idx)

    def test_json_flag_returns_valid_json(self):
        make_yaml_entry(self.garden / 'tools' / 'GE-0001.md',
                        'GE-0001', 'Test', 10, author='mdp')
        result = run_contributors(str(self.garden), '--json')
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)
        for key in ('author', 'avg_score', 'avg_bonus', 'entries', 'best_entry'):
            self.assertIn(key, data[0])

    def test_bonus_reflected_in_avg_score(self):
        make_yaml_entry(
            self.garden / 'tools' / 'GE-0001.md',
            'GE-0001', 'Rich entry', 10, author='mdp',
            constraints='requires Java 17+',
            has_alternatives=True,
            invalidation_triggers='revisit if library changes'
        )
        result = run_contributors(str(self.garden), '--json')
        data = json.loads(result.stdout)
        self.assertEqual(data[0]['avg_score'], 13.0)
        self.assertEqual(data[0]['avg_bonus'], 3.0)

    def test_contributors_md_has_legend(self):
        run_contributors(str(self.garden))
        content = (self.garden / 'CONTRIBUTORS.md').read_text()
        self.assertIn('Avg Bonus', content)
        self.assertIn('constraints', content)


if __name__ == '__main__':
    unittest.main(verbosity=2)
