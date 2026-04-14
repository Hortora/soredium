#!/usr/bin/env python3
"""Unit and integration tests for dedupe_scanner.py."""

import sys
import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
from dedupe_scanner import (
    tokenize, jaccard, canonical_pair, parse_tags,
    load_checked_pairs, record_pair,
)

SCANNER = Path(__file__).parent.parent / 'scripts' / 'dedupe_scanner.py'


def run_scanner(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCANNER)] + list(args),
        capture_output=True, text=True
    )


def make_entry(path: Path, ge_id: str, title: str, tags: list, domain: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'---\nid: {ge_id}\ntitle: "{title}"\ntype: gotcha\n'
        f'domain: {domain}\ntags: [{", ".join(tags)}]\nscore: 10\n'
        f'verified: true\nstaleness_threshold: 730\nsubmitted: 2026-04-14\n---\n\n'
        f'## {title}\n\n**ID:** {ge_id}\n'
    )


# ── tokenize ──────────────────────────────────────────────────────────────────

class TestTokenize(unittest.TestCase):

    def test_empty_string(self):
        self.assertEqual(tokenize(''), set())

    def test_short_words_excluded(self):
        self.assertEqual(tokenize('is an of to'), set())

    def test_three_char_included(self):
        self.assertIn('the', tokenize('the'))

    def test_lowercase_normalisation(self):
        self.assertEqual(tokenize('Python REGEX'), tokenize('python regex'))

    def test_deduplication(self):
        self.assertEqual(tokenize('regex regex regex'), {'regex'})

    def test_punctuation_stripped(self):
        result = tokenize('parsing, yaml; frontmatter.')
        self.assertIn('parsing', result)
        self.assertIn('yaml', result)
        self.assertIn('frontmatter', result)

    def test_hyphenated_words_split(self):
        result = tokenize('crlf line-ending')
        self.assertIn('crlf', result)
        self.assertIn('line', result)
        self.assertIn('ending', result)

    def test_numbers_excluded(self):
        result = tokenize('123 456')
        self.assertEqual(result, set())


# ── jaccard ───────────────────────────────────────────────────────────────────

class TestJaccard(unittest.TestCase):

    def test_empty_sets(self):
        self.assertEqual(jaccard(set(), set()), 0.0)

    def test_identical_sets(self):
        s = {'regex', 'yaml', 'parsing'}
        self.assertEqual(jaccard(s, s), 1.0)

    def test_disjoint_sets(self):
        self.assertEqual(jaccard({'regex'}, {'yaml'}), 0.0)

    def test_partial_overlap(self):
        # {aaa, bbb} ∩ {bbb, ccc} = {bbb}, union = {aaa, bbb, ccc} → 1/3
        result = jaccard({'aaa', 'bbb'}, {'bbb', 'ccc'})
        self.assertAlmostEqual(result, 1 / 3, places=4)

    def test_one_empty(self):
        self.assertEqual(jaccard({'regex'}, set()), 0.0)
        self.assertEqual(jaccard(set(), {'regex'}), 0.0)

    def test_formula_correctness(self):
        a = {'one', 'two', 'six'}
        b = {'one', 'two', 'thr', 'fou', 'fiv'}
        expected = len(a & b) / len(a | b)
        self.assertAlmostEqual(jaccard(a, b), expected, places=4)


# ── canonical_pair ────────────────────────────────────────────────────────────

class TestCanonicalPair(unittest.TestCase):

    def test_lower_first(self):
        self.assertEqual(canonical_pair('GE-0002', 'GE-0001'), 'GE-0001 × GE-0002')

    def test_already_ordered(self):
        self.assertEqual(canonical_pair('GE-0001', 'GE-0002'), 'GE-0001 × GE-0002')

    def test_legacy_before_new_format(self):
        # GE-0001 < GE-20260414-aabbcc lexicographically ('0' < '2')
        result = canonical_pair('GE-20260414-aabbcc', 'GE-0001')
        self.assertEqual(result, 'GE-0001 × GE-20260414-aabbcc')

    def test_new_format_ordering(self):
        a = 'GE-20260414-aaaaaa'
        b = 'GE-20260414-bbbbbb'
        self.assertEqual(canonical_pair(b, a), f'{a} × {b}')


# ── parse_tags ────────────────────────────────────────────────────────────────

class TestParseTags(unittest.TestCase):

    def test_basic(self):
        self.assertEqual(parse_tags('regex, yaml, parsing'), ['regex', 'yaml', 'parsing'])

    def test_with_quotes(self):
        self.assertEqual(parse_tags('"regex", "yaml"'), ['regex', 'yaml'])

    def test_empty(self):
        self.assertEqual(parse_tags(''), [])

    def test_single_tag(self):
        self.assertEqual(parse_tags('regex'), ['regex'])


# ── load_checked_pairs ────────────────────────────────────────────────────────

class TestLoadCheckedPairs(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_empty_file(self):
        (self.root / 'CHECKED.md').write_text(
            '| Pair | Result | Date | Notes |\n|------|--------|------|-------|\n'
        )
        self.assertEqual(load_checked_pairs(self.root), set())

    def test_missing_file(self):
        self.assertEqual(load_checked_pairs(self.root), set())

    def test_single_pair(self):
        (self.root / 'CHECKED.md').write_text(
            '| GE-0001 × GE-0002 | distinct | 2026-04-14 | |\n'
        )
        result = load_checked_pairs(self.root)
        self.assertIn('GE-0001 × GE-0002', result)

    def test_both_orderings_recognised(self):
        (self.root / 'CHECKED.md').write_text(
            '| GE-0002 × GE-0001 | distinct | 2026-04-14 | |\n'
        )
        result = load_checked_pairs(self.root)
        self.assertIn('GE-0001 × GE-0002', result)

    def test_malformed_rows_skipped(self):
        (self.root / 'CHECKED.md').write_text(
            'This is not a pair row\n'
            '| GE-0001 × GE-0002 | distinct | 2026-04-14 | |\n'
            'Another bad row\n'
        )
        result = load_checked_pairs(self.root)
        self.assertEqual(len(result), 1)

    def test_multiple_pairs(self):
        (self.root / 'CHECKED.md').write_text(
            '| GE-0001 × GE-0002 | distinct | 2026-04-14 | |\n'
            '| GE-0003 × GE-0004 | related | 2026-04-14 | cross-referenced |\n'
            '| GE-0005 × GE-0006 | duplicate-discarded | 2026-04-14 | GE-0005 kept |\n'
        )
        self.assertEqual(len(load_checked_pairs(self.root)), 3)


# ── record_pair ───────────────────────────────────────────────────────────────

class TestRecordPair(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'CHECKED.md').write_text(
            '| Pair | Result | Date | Notes |\n|------|--------|------|-------|\n'
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_appends_row(self):
        record_pair(self.root, 'GE-0001 × GE-0002', 'distinct', 'no overlap')
        content = (self.root / 'CHECKED.md').read_text()
        self.assertIn('GE-0001 × GE-0002', content)
        self.assertIn('distinct', content)
        self.assertIn('no overlap', content)

    def test_canonical_ordering_enforced(self):
        record_pair(self.root, 'GE-0002 × GE-0001', 'distinct', '')
        content = (self.root / 'CHECKED.md').read_text()
        self.assertIn('GE-0001 × GE-0002', content)
        self.assertNotIn('GE-0002 × GE-0001', content)

    def test_idempotent(self):
        record_pair(self.root, 'GE-0001 × GE-0002', 'distinct', '')
        record_pair(self.root, 'GE-0001 × GE-0002', 'distinct', '')
        content = (self.root / 'CHECKED.md').read_text()
        self.assertEqual(content.count('GE-0001 × GE-0002'), 1)

    def test_all_valid_results_accepted(self):
        for i, res in enumerate(['distinct', 'related', 'duplicate-discarded']):
            record_pair(self.root, f'GE-000{i+1} × GE-999{i+1}', res, '')
        content = (self.root / 'CHECKED.md').read_text()
        self.assertIn('distinct', content)
        self.assertIn('related', content)
        self.assertIn('duplicate-discarded', content)

    def test_invalid_result_exits_1(self):
        with self.assertRaises(SystemExit) as ctx:
            record_pair(self.root, 'GE-0001 × GE-0002', 'bogus', '')
        self.assertEqual(ctx.exception.code, 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
