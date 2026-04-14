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
    load_entries, compute_pairs,
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


class TestLoadEntries(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_finds_yaml_entries(self):
        make_entry(self.root / 'python' / 'GE-0001.md', 'GE-0001', 'CRLF regex skip', ['regex', 'yaml'], 'python')
        make_entry(self.root / 'python' / 'GE-0002.md', 'GE-0002', 'fromisoformat crash', ['datetime'], 'python')
        result = load_entries(self.root)
        self.assertIn('python', result)
        self.assertEqual(len(result['python']), 2)

    def test_skips_non_frontmatter_entries(self):
        (self.root / 'tools').mkdir()
        (self.root / 'tools' / 'GE-0042.md').write_text(
            '## Legacy entry\n\n**ID:** GE-0042\n**Stack:** git\n'
        )
        result = load_entries(self.root)
        self.assertEqual(len(result.get('tools', [])), 0)

    def test_skips_index_and_control_files(self):
        (self.root / 'GARDEN.md').write_text('**Last legacy ID:** GE-0001\n')
        (self.root / 'CHECKED.md').write_text('| Pair |\n')
        (self.root / 'DISCARDED.md').write_text('| Pair |\n')
        (self.root / 'tools').mkdir()
        (self.root / 'tools' / 'INDEX.md').write_text('| GE-ID | Title |\n')
        make_entry(self.root / 'tools' / 'GE-0001.md', 'GE-0001', 'Test', ['git'], 'tools')
        result = load_entries(self.root)
        self.assertEqual(len(result.get('tools', [])), 1)

    def test_skips_hidden_dirs(self):
        (self.root / '_summaries').mkdir()
        (self.root / '_summaries' / 'GE-0001.md').write_text(
            '---\nid: GE-0001\ntitle: "Test"\ntype: gotcha\ndomain: tools\n'
            'tags: [git]\nscore: 10\nverified: true\nstaleness_threshold: 730\n'
            'submitted: 2026-04-14\n---\n\n## Test\n'
        )
        result = load_entries(self.root)
        self.assertEqual(result, {})

    def test_domain_filter(self):
        make_entry(self.root / 'python' / 'GE-0001.md', 'GE-0001', 'Python entry', ['regex'], 'python')
        make_entry(self.root / 'tools' / 'GE-0002.md', 'GE-0002', 'Tools entry', ['git'], 'tools')
        result = load_entries(self.root, domain_filter='python')
        self.assertIn('python', result)
        self.assertNotIn('tools', result)

    def test_crlf_files_not_skipped(self):
        path = self.root / 'python' / 'GE-0001.md'
        path.parent.mkdir(parents=True)
        path.write_bytes(
            b'---\r\nid: GE-0001\r\ntitle: "CRLF test"\r\ntype: gotcha\r\n'
            b'domain: python\r\ntags: [regex]\r\nscore: 10\r\nverified: true\r\n'
            b'staleness_threshold: 730\r\nsubmitted: 2026-04-14\r\n---\r\n\r\n'
            b'## CRLF test\r\n'
        )
        result = load_entries(self.root)
        self.assertIn('python', result)
        self.assertEqual(len(result['python']), 1)

    def test_entry_fields_correctly_parsed(self):
        make_entry(self.root / 'python' / 'GE-0001.md', 'GE-0001', 'CRLF regex skip', ['regex', 'yaml'], 'python')
        result = load_entries(self.root)
        entry = result['python'][0]
        self.assertEqual(entry['id'], 'GE-0001')
        self.assertEqual(entry['title'], 'CRLF regex skip')
        self.assertIn('regex', entry['tags'])
        self.assertIn('yaml', entry['tags'])


class TestComputePairs(unittest.TestCase):

    def test_no_entries_empty_result(self):
        self.assertEqual(compute_pairs({}, set()), [])

    def test_single_entry_no_pairs(self):
        entries = {'python': [{'id': 'GE-0001', 'title': 'Test', 'tags': ['regex']}]}
        self.assertEqual(compute_pairs(entries, set()), [])

    def test_two_entries_one_pair(self):
        entries = {'python': [
            {'id': 'GE-0001', 'title': 'regex yaml crlf parsing', 'tags': ['regex', 'yaml']},
            {'id': 'GE-0002', 'title': 'regex datetime parsing', 'tags': ['regex']},
        ]}
        pairs = compute_pairs(entries, set())
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]['pair'], 'GE-0001 × GE-0002')

    def test_three_entries_three_pairs(self):
        entries = {'python': [
            {'id': 'GE-0001', 'title': 'entry one', 'tags': ['tag']},
            {'id': 'GE-0002', 'title': 'entry two', 'tags': ['tag']},
            {'id': 'GE-0003', 'title': 'entry three', 'tags': ['tag']},
        ]}
        self.assertEqual(len(compute_pairs(entries, set())), 3)

    def test_checked_pairs_excluded(self):
        entries = {'python': [
            {'id': 'GE-0001', 'title': 'one', 'tags': []},
            {'id': 'GE-0002', 'title': 'two', 'tags': []},
        ]}
        checked = {'GE-0001 × GE-0002'}
        self.assertEqual(compute_pairs(entries, checked), [])

    def test_cross_domain_never_paired(self):
        entries = {
            'python': [{'id': 'GE-0001', 'title': 'regex yaml', 'tags': ['regex']}],
            'tools': [{'id': 'GE-0002', 'title': 'regex yaml', 'tags': ['regex']}],
        }
        pairs = compute_pairs(entries, set())
        pair_keys = [p['pair'] for p in pairs]
        self.assertNotIn('GE-0001 × GE-0002', pair_keys)

    def test_sorted_highest_score_first(self):
        entries = {'python': [
            {'id': 'GE-0001', 'title': 'regex yaml crlf parsing frontmatter', 'tags': ['regex', 'yaml', 'crlf']},
            {'id': 'GE-0002', 'title': 'regex yaml crlf parsing frontmatter', 'tags': ['regex', 'yaml', 'crlf']},
            {'id': 'GE-0003', 'title': 'completely different git branch rebase', 'tags': ['git']},
        ]}
        pairs = compute_pairs(entries, set())
        self.assertGreaterEqual(pairs[0]['score'], pairs[-1]['score'])
        self.assertEqual(pairs[0]['score'], 1.0)

    def test_top_limit(self):
        entries = {'python': [
            {'id': f'GE-000{i}', 'title': f'entry {i}', 'tags': ['tag']}
            for i in range(1, 5)
        ]}
        self.assertEqual(len(compute_pairs(entries, set())), 6)
        self.assertEqual(len(compute_pairs(entries, set(), top=3)), 3)

    def test_high_score_for_identical_entries(self):
        entries = {'python': [
            {'id': 'GE-0001', 'title': 'yaml regex crlf skip silent', 'tags': ['regex', 'yaml', 'crlf']},
            {'id': 'GE-0002', 'title': 'yaml regex crlf skip silent', 'tags': ['regex', 'yaml', 'crlf']},
        ]}
        pairs = compute_pairs(entries, set())
        self.assertEqual(pairs[0]['score'], 1.0)

    def test_low_score_for_unrelated_entries(self):
        entries = {'python': [
            {'id': 'GE-0001', 'title': 'yaml frontmatter regex crlf parsing', 'tags': ['regex', 'yaml']},
            {'id': 'GE-0002', 'title': 'git commit rebase squash branch history', 'tags': ['git', 'workflow']},
        ]}
        pairs = compute_pairs(entries, set())
        self.assertLess(pairs[0]['score'], 0.1)

    def test_pair_result_has_required_fields(self):
        entries = {'python': [
            {'id': 'GE-0001', 'title': 'regex', 'tags': ['regex']},
            {'id': 'GE-0002', 'title': 'yaml', 'tags': ['yaml']},
        ]}
        pairs = compute_pairs(entries, set())
        p = pairs[0]
        self.assertIn('pair', p)
        self.assertIn('id_a', p)
        self.assertIn('id_b', p)
        self.assertIn('title_a', p)
        self.assertIn('title_b', p)
        self.assertIn('domain', p)
        self.assertIn('score', p)


class TestDedupesScannerCLI(unittest.TestCase):
    """Integration tests calling dedupe_scanner.py as a subprocess."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'CHECKED.md').write_text(
            '| Pair | Result | Date | Notes |\n|------|--------|------|-------|\n'
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_entries_exits_0_and_says_no_pairs(self):
        result = run_scanner(str(self.root))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('No unchecked pairs', result.stdout)

    def test_two_similar_entries_appear_in_output(self):
        make_entry(self.root / 'python' / 'GE-0001.md', 'GE-0001',
                   'regex yaml crlf skip silent', ['regex', 'yaml', 'crlf'], 'python')
        make_entry(self.root / 'python' / 'GE-0002.md', 'GE-0002',
                   'regex yaml crlf skip parsing', ['regex', 'yaml'], 'python')
        result = run_scanner(str(self.root))
        self.assertEqual(result.returncode, 0)
        self.assertIn('GE-0001', result.stdout)
        self.assertIn('GE-0002', result.stdout)

    def test_domain_flag_filters_to_requested_domain(self):
        make_entry(self.root / 'python' / 'GE-0001.md', 'GE-0001', 'python regex', ['regex'], 'python')
        make_entry(self.root / 'python' / 'GE-0002.md', 'GE-0002', 'python yaml', ['yaml'], 'python')
        make_entry(self.root / 'tools' / 'GE-0003.md', 'GE-0003', 'git tools branch', ['git'], 'tools')
        make_entry(self.root / 'tools' / 'GE-0004.md', 'GE-0004', 'git rebase squash', ['git'], 'tools')
        result = run_scanner(str(self.root), '--domain', 'python')
        self.assertIn('GE-0001', result.stdout)
        self.assertNotIn('GE-0003', result.stdout)
        self.assertNotIn('GE-0004', result.stdout)

    def test_top_flag_limits_number_of_pairs(self):
        for i in range(1, 5):
            make_entry(self.root / 'python' / f'GE-000{i}.md', f'GE-000{i}',
                       f'regex yaml crlf entry {i}', ['regex', 'yaml'], 'python')
        result_all = run_scanner(str(self.root))
        result_top2 = run_scanner(str(self.root), '--top', '2')
        # 4 entries = 6 pairs; --top 2 shows fewer GE-IDs in output
        all_count = result_all.stdout.count('GE-')
        top_count = result_top2.stdout.count('GE-')
        self.assertGreater(all_count, top_count)

    def test_json_flag_outputs_valid_json(self):
        make_entry(self.root / 'python' / 'GE-0001.md', 'GE-0001', 'regex yaml', ['regex'], 'python')
        make_entry(self.root / 'python' / 'GE-0002.md', 'GE-0002', 'regex crlf', ['regex'], 'python')
        result = run_scanner(str(self.root), '--json')
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)
        self.assertIn('pair', data[0])
        self.assertIn('score', data[0])
        self.assertIn('domain', data[0])

    def test_json_empty_garden_returns_empty_list(self):
        result = run_scanner(str(self.root), '--json')
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertEqual(data, [])

    def test_record_flag_writes_to_checked_md(self):
        result = run_scanner(str(self.root), '--record',
                             'GE-0001 × GE-0002', 'distinct', 'no overlap')
        self.assertEqual(result.returncode, 0, result.stderr)
        content = (self.root / 'CHECKED.md').read_text()
        self.assertIn('GE-0001 × GE-0002', content)
        self.assertIn('distinct', content)
        self.assertIn('no overlap', content)

    def test_record_then_rescan_excludes_pair(self):
        make_entry(self.root / 'python' / 'GE-0001.md', 'GE-0001',
                   'regex yaml parsing frontmatter', ['regex', 'yaml'], 'python')
        make_entry(self.root / 'python' / 'GE-0002.md', 'GE-0002',
                   'regex yaml crlf skip', ['regex', 'yaml'], 'python')
        # First scan shows the pair
        result1 = run_scanner(str(self.root))
        self.assertIn('GE-0001', result1.stdout)
        # Record it as distinct
        run_scanner(str(self.root), '--record', 'GE-0001 × GE-0002', 'distinct', '')
        # Second scan — pair absent
        result2 = run_scanner(str(self.root))
        self.assertIn('No unchecked pairs', result2.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)
