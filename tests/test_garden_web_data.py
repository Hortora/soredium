#!/usr/bin/env python3
"""Unit and integration tests for garden_web_data.py."""

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
from garden_web_data import (
    parse_entry_frontmatter, parse_domain_index,
    get_domain_entries, build_garden_data,
)

CLI = Path(__file__).parent.parent / 'scripts' / 'garden_web_data.py'


def run_cli(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI)] + list(args),
        capture_output=True, text=True
    )


ENTRY_CONTENT = """\
---
id: GE-20260414-aa0001
title: "Hibernate @PreUpdate fires at flush time not at persist"
type: gotcha
domain: java
stack: "Hibernate ORM 6.x"
tags: [hibernate, jpa, lifecycle, flush]
score: 12
verified: true
staleness_threshold: 730
submitted: 2026-04-14
---

## Hibernate @PreUpdate fires at flush time not at persist

**ID:** GE-20260414-aa0001
**Stack:** Hibernate ORM 6.x
**Symptom:** Callback not firing.

### Root cause
Fires at flush.

### Fix
Force flush.
"""

DOMAIN_INDEX = """\
# Java Index

| GE-ID | Title | Type | Score | Submitted |
|-------|-------|------|-------|-----------|
| GE-20260414-aa0001 | Hibernate @PreUpdate fires at flush time | gotcha | 12 | 2026-04-14 |
| GE-20260414-aa0002 | H2 rejects key as a column name | gotcha | 10 | 2026-04-14 |
"""


def make_garden(tmp: Path) -> Path:
    """Create a simple garden with java (2 entries) and tools (1 entry) domains."""
    garden = tmp / 'garden'
    garden.mkdir()
    (garden / 'GARDEN.md').write_text(
        '**Last assigned ID:** GE-0002\n'
        '**Last full DEDUPE sweep:** 2026-04-15\n'
        '**Entries merged since last sweep:** 0\n'
        '**Drift threshold:** 10\n'
    )
    (garden / 'java').mkdir()
    for gid, title, score in [
        ('aa0001', 'Hibernate @PreUpdate fires at flush time', 12),
        ('aa0002', 'H2 rejects key as a column name', 10),
    ]:
        (garden / 'java' / f'GE-20260414-{gid}.md').write_text(
            f'---\nid: GE-20260414-{gid}\ntitle: "{title}"\ntype: gotcha\n'
            f'domain: java\nstack: "Java"\ntags: [java, hibernate]\n'
            f'score: {score}\nverified: true\nstaleness_threshold: 730\n'
            f'submitted: 2026-04-14\n---\n\n## {title}\n**ID:** GE-20260414-{gid}\n'
        )
    (garden / 'tools').mkdir()
    (garden / 'tools' / 'GE-20260414-bb0001.md').write_text(
        '---\nid: GE-20260414-bb0001\ntitle: "macOS BSD sed ignores word boundaries"\n'
        'type: gotcha\ndomain: tools\nstack: "macOS, BSD sed"\ntags: [sed, macos, regex]\n'
        'score: 11\nverified: true\nstaleness_threshold: 730\nsubmitted: 2026-04-14\n---\n\n'
        '## macOS BSD sed ignores word boundaries\n**ID:** GE-20260414-bb0001\n'
    )
    return garden


class TestParseEntryFrontmatter(unittest.TestCase):

    def test_parses_id(self):
        self.assertEqual(parse_entry_frontmatter(ENTRY_CONTENT)['id'], 'GE-20260414-aa0001')

    def test_parses_title(self):
        self.assertIn('Hibernate', parse_entry_frontmatter(ENTRY_CONTENT)['title'])

    def test_parses_type(self):
        self.assertEqual(parse_entry_frontmatter(ENTRY_CONTENT)['type'], 'gotcha')

    def test_parses_domain(self):
        self.assertEqual(parse_entry_frontmatter(ENTRY_CONTENT)['domain'], 'java')

    def test_parses_tags_as_list(self):
        tags = parse_entry_frontmatter(ENTRY_CONTENT)['tags']
        self.assertIsInstance(tags, list)
        self.assertIn('hibernate', tags)

    def test_parses_score_as_int(self):
        self.assertEqual(parse_entry_frontmatter(ENTRY_CONTENT)['score'], 12)

    def test_parses_staleness_threshold_as_int(self):
        self.assertEqual(parse_entry_frontmatter(ENTRY_CONTENT)['staleness_threshold'], 730)

    def test_parses_submitted(self):
        self.assertEqual(parse_entry_frontmatter(ENTRY_CONTENT)['submitted'], '2026-04-14')

    def test_empty_content_returns_empty_dict(self):
        self.assertEqual(parse_entry_frontmatter(''), {})

    def test_no_frontmatter_returns_empty_dict(self):
        self.assertEqual(parse_entry_frontmatter('## Just a heading\n\nNo YAML\n'), {})

    def test_crlf_content_parsed(self):
        result = parse_entry_frontmatter(ENTRY_CONTENT.replace('\n', '\r\n'))
        self.assertEqual(result['id'], 'GE-20260414-aa0001')


class TestParseDomainIndex(unittest.TestCase):

    def test_returns_list(self):
        self.assertIsInstance(parse_domain_index(DOMAIN_INDEX), list)

    def test_finds_both_entries(self):
        self.assertEqual(len(parse_domain_index(DOMAIN_INDEX)), 2)

    def test_entry_has_ge_id(self):
        ids = [e['id'] for e in parse_domain_index(DOMAIN_INDEX)]
        self.assertIn('GE-20260414-aa0001', ids)
        self.assertIn('GE-20260414-aa0002', ids)

    def test_entry_has_title(self):
        result = parse_domain_index(DOMAIN_INDEX)
        self.assertTrue(any('Hibernate' in e['title'] for e in result))

    def test_empty_index_returns_empty_list(self):
        self.assertEqual(parse_domain_index('# Java Index\n\nNo table.\n'), [])

    def test_header_rows_not_included(self):
        ids = [e['id'] for e in parse_domain_index(DOMAIN_INDEX)]
        self.assertNotIn('GE-ID', ids)


class TestGetDomainEntries(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.garden = make_garden(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_returns_entries_for_java(self):
        self.assertEqual(len(get_domain_entries(self.garden, 'java')), 2)

    def test_returns_entries_for_tools(self):
        self.assertEqual(len(get_domain_entries(self.garden, 'tools')), 1)

    def test_entries_have_id(self):
        for e in get_domain_entries(self.garden, 'java'):
            self.assertIn('id', e)
            self.assertRegex(e['id'], r'^GE-\d{8}-[0-9a-f]{6}$')

    def test_entries_have_title(self):
        for e in get_domain_entries(self.garden, 'java'):
            self.assertIn('title', e)
            self.assertTrue(len(e['title']) > 0)

    def test_entries_have_required_fields(self):
        for e in get_domain_entries(self.garden, 'java'):
            for field in ('id', 'title', 'type', 'domain', 'score', 'tags'):
                self.assertIn(field, e, f"Missing field: {field}")

    def test_nonexistent_domain_returns_empty(self):
        self.assertEqual(get_domain_entries(self.garden, 'nonexistent'), [])


class TestBuildGardenData(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.garden = make_garden(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_returns_dict(self):
        self.assertIsInstance(build_garden_data(self.garden), dict)

    def test_has_domains_list(self):
        data = build_garden_data(self.garden)
        self.assertIn('domains', data)
        self.assertIsInstance(data['domains'], list)

    def test_finds_both_domains(self):
        names = [d['name'] for d in build_garden_data(self.garden)['domains']]
        self.assertIn('java', names)
        self.assertIn('tools', names)

    def test_domain_has_entry_count(self):
        data = build_garden_data(self.garden)
        java = next(d for d in data['domains'] if d['name'] == 'java')
        self.assertEqual(java['entry_count'], 2)

    def test_domain_has_entries_list(self):
        data = build_garden_data(self.garden)
        java = next(d for d in data['domains'] if d['name'] == 'java')
        self.assertEqual(len(java['entries']), 2)

    def test_has_total_entries(self):
        self.assertEqual(build_garden_data(self.garden)['total_entries'], 3)

    def test_has_generated_timestamp(self):
        data = build_garden_data(self.garden)
        self.assertIn('generated', data)
        self.assertIsInstance(data['generated'], str)

    def test_output_is_json_serializable(self):
        json.dumps(build_garden_data(self.garden))  # must not raise

    def test_nonexistent_garden_raises(self):
        with self.assertRaises(Exception):
            build_garden_data(Path('/nonexistent/path'))


class TestGardenWebDataCLI(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.garden = make_garden(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_outputs_valid_json(self):
        result = run_cli(str(self.garden))
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertIn('domains', data)

    def test_json_contains_both_domains(self):
        result = run_cli(str(self.garden))
        names = [d['name'] for d in json.loads(result.stdout)['domains']]
        self.assertIn('java', names)
        self.assertIn('tools', names)

    def test_json_contains_correct_total(self):
        result = run_cli(str(self.garden))
        self.assertEqual(json.loads(result.stdout)['total_entries'], 3)

    def test_invalid_path_exits_1(self):
        self.assertEqual(run_cli('/nonexistent/garden').returncode, 1)

    def test_no_args_does_not_crash(self):
        result = run_cli()
        self.assertIn(result.returncode, [0, 1])


if __name__ == '__main__':
    unittest.main(verbosity=2)
