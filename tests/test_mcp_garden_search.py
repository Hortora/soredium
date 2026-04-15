#!/usr/bin/env python3
"""Unit and integration tests for mcp_garden_search.py."""

import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
from mcp_garden_search import (
    search_garden, keyword_score, parse_garden_index,
    fetch_entry_body, tier3_grep,
)


def make_git_garden(tmp_path: Path) -> Path:
    """Create a minimal committed garden with 2 java entries and 1 tools entry."""
    garden = tmp_path / 'garden'
    garden.mkdir()
    subprocess.run(['git', 'init', str(garden)], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(garden), 'config', 'user.email', 'test@test.com'],
                   check=True, capture_output=True)
    subprocess.run(['git', '-C', str(garden), 'config', 'user.name', 'Test'],
                   check=True, capture_output=True)

    (garden / 'GARDEN.md').write_text(
        '**Last assigned ID:** GE-0002\n'
        '**Last full DEDUPE sweep:** 2026-04-15\n'
        '**Entries merged since last sweep:** 1\n'
        '**Drift threshold:** 10\n\n'
        '## By Technology\n\n'
        '### Java\n'
        '| GE-ID | Title | Type | Score |\n'
        '|-------|-------|------|-------|\n'
        '| [GE-20260414-aa0001](java/GE-20260414-aa0001.md) | '
        'Hibernate @PreUpdate fires at flush time | gotcha | 12 |\n'
        '| [GE-20260414-aa0002](java/GE-20260414-aa0002.md) | '
        'H2 rejects key as column name | gotcha | 10 |\n\n'
        '## By Symptom / Type\n\n## By Label\n\n'
    )

    (garden / 'java').mkdir()
    (garden / 'java' / 'GE-20260414-aa0001.md').write_text(
        '---\nid: GE-20260414-aa0001\n'
        'title: "Hibernate @PreUpdate fires at flush time not at persist"\n'
        'type: gotcha\ndomain: java\n'
        'stack: "Hibernate ORM 6.x"\ntags: [hibernate, jpa, lifecycle, flush]\n'
        'score: 12\nverified: true\nstaleness_threshold: 730\nsubmitted: 2026-04-14\n---\n\n'
        '## Hibernate @PreUpdate fires at flush time not at persist\n\n'
        '**ID:** GE-20260414-aa0001\n**Stack:** Hibernate ORM 6.x\n'
        '**Symptom:** @PreUpdate callback not firing when expected.\n\n'
        '### Root cause\nFires at flush, not persist.\n\n### Fix\nForce flush.\n'
    )
    (garden / 'java' / 'GE-20260414-aa0002.md').write_text(
        '---\nid: GE-20260414-aa0002\n'
        'title: "H2 rejects key as a column name"\n'
        'type: gotcha\ndomain: java\n'
        'stack: "H2 2.x, Quarkus"\ntags: [h2, sql, reserved-word]\n'
        'score: 10\nverified: true\nstaleness_threshold: 730\nsubmitted: 2026-04-14\n---\n\n'
        '## H2 rejects key as a column name\n\n'
        '**ID:** GE-20260414-aa0002\n**Stack:** H2 2.x\n'
        '**Symptom:** SQL syntax error on column named "key".\n\n'
        '### Root cause\n"key" is an H2 reserved word.\n\n### Fix\nRename the column.\n'
    )

    (garden / 'tools').mkdir()
    (garden / 'tools' / 'GE-20260414-bb0001.md').write_text(
        '---\nid: GE-20260414-bb0001\n'
        'title: "macOS BSD sed silently ignores word boundaries"\n'
        'type: gotcha\ndomain: tools\n'
        'stack: "macOS, BSD sed"\ntags: [sed, macos, regex]\n'
        'score: 11\nverified: true\nstaleness_threshold: 730\nsubmitted: 2026-04-14\n---\n\n'
        '## macOS BSD sed silently ignores word boundaries\n\n'
        '**ID:** GE-20260414-bb0001\n**Stack:** macOS, BSD sed\n'
        '**Symptom:** sed replacement silently does nothing.\n\n'
        '### Root cause\nBSD sed has different regex syntax.\n\n### Fix\nUse perl -pi instead.\n'
    )

    subprocess.run(['git', '-C', str(garden), 'add', '.'], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(garden), 'commit', '-m', 'init'],
                   check=True, capture_output=True)
    return garden


class TestKeywordScore(unittest.TestCase):

    def test_empty_query_scores_zero(self):
        self.assertEqual(keyword_score('', 'some content here'), 0)

    def test_single_match(self):
        self.assertGreater(keyword_score('hibernate', 'Hibernate fires at flush'), 0)

    def test_no_match_scores_zero(self):
        self.assertEqual(keyword_score('python asyncio', 'Hibernate flush fires'), 0)

    def test_multiple_matches_higher_than_single(self):
        single = keyword_score('flush', 'Hibernate fires at flush')
        multi = keyword_score('hibernate flush fires', 'Hibernate fires at flush')
        self.assertGreater(multi, single)

    def test_case_insensitive(self):
        self.assertEqual(
            keyword_score('HIBERNATE', 'Hibernate ORM'),
            keyword_score('hibernate', 'Hibernate ORM')
        )

    def test_short_words_ignored(self):
        self.assertEqual(keyword_score('at in of', 'at in of to'), 0)


class TestParseGardenIndex(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.garden = make_git_garden(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_returns_dict(self):
        index = parse_garden_index(self.garden)
        self.assertIsInstance(index, dict)

    def test_java_entries_found(self):
        index = parse_garden_index(self.garden)
        all_ids = [geid for ids in index.values() for geid in ids]
        self.assertGreater(len(all_ids), 0)

    def test_ge_ids_in_index(self):
        index = parse_garden_index(self.garden)
        all_ids = [geid for ids in index.values() for geid in ids]
        self.assertIn('GE-20260414-aa0001', all_ids)
        self.assertIn('GE-20260414-aa0002', all_ids)

    def test_no_garden_md_returns_empty(self):
        tmp = Path(self.tmp.name) / 'empty'
        tmp.mkdir()
        subprocess.run(['git', 'init', str(tmp)], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(tmp), 'config', 'user.email', 'test@test.com'],
                       check=True, capture_output=True)
        subprocess.run(['git', '-C', str(tmp), 'config', 'user.name', 'Test'],
                       check=True, capture_output=True)
        result = parse_garden_index(tmp)
        self.assertEqual(result, {})


class TestFetchEntryBody(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.garden = make_git_garden(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_fetches_known_entry(self):
        body = fetch_entry_body(self.garden, 'java', 'GE-20260414-aa0001')
        self.assertIsNotNone(body)
        self.assertIn('Hibernate', body)
        self.assertIn('flush', body)

    def test_returns_none_for_unknown_entry(self):
        body = fetch_entry_body(self.garden, 'java', 'GE-99999999-ffffff')
        self.assertIsNone(body)

    def test_fetches_tools_entry(self):
        body = fetch_entry_body(self.garden, 'tools', 'GE-20260414-bb0001')
        self.assertIsNotNone(body)
        self.assertIn('sed', body)


class TestTier3Grep(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.garden = make_git_garden(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_finds_matching_entry(self):
        results = tier3_grep(self.garden, 'flush', domain='java')
        ids = [r['id'] for r in results]
        self.assertIn('GE-20260414-aa0001', ids)

    def test_no_match_returns_empty(self):
        results = tier3_grep(self.garden, 'xyzzy_nonexistent_term', domain='java')
        self.assertEqual(results, [])

    def test_domain_filter_excludes_other_domains(self):
        results = tier3_grep(self.garden, 'sed', domain='java')
        self.assertEqual(results, [])

    def test_no_domain_searches_all(self):
        results = tier3_grep(self.garden, 'sed')
        ids = [r['id'] for r in results]
        self.assertIn('GE-20260414-bb0001', ids)


class TestSearchGarden(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.garden = make_git_garden(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_search_returns_list(self):
        results = search_garden(self.garden, 'hibernate')
        self.assertIsInstance(results, list)

    def test_relevant_entry_returned(self):
        results = search_garden(self.garden, 'hibernate flush')
        self.assertTrue(len(results) > 0)
        self.assertTrue(any('aa0001' in r['id'] for r in results))

    def test_each_result_has_required_fields(self):
        results = search_garden(self.garden, 'hibernate')
        self.assertTrue(len(results) > 0)
        for r in results:
            self.assertIn('id', r)
            self.assertIn('title', r)
            self.assertIn('domain', r)
            self.assertIn('body', r)

    def test_no_results_for_unknown_query(self):
        results = search_garden(self.garden, 'xyzzy_nonexistent_term_7829')
        self.assertEqual(results, [])

    def test_domain_parameter_filters_correctly(self):
        results = search_garden(self.garden, 'sed', domain='tools')
        ids = [r['id'] for r in results]
        self.assertIn('GE-20260414-bb0001', ids)

    def test_empty_query_returns_empty(self):
        results = search_garden(self.garden, '')
        self.assertEqual(results, [])

    def test_technology_filter_finds_java_entries(self):
        results = search_garden(self.garden, 'flush', technology='Java')
        self.assertTrue(len(results) > 0)
        for r in results:
            self.assertEqual(r['domain'], 'java')


if __name__ == '__main__':
    unittest.main(verbosity=2)
