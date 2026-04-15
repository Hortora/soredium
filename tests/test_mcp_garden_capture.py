#!/usr/bin/env python3
"""Unit and integration tests for mcp_garden_capture.py."""

import re
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
from mcp_garden_capture import (
    build_entry_content, generate_ge_id, validate_capture_args, capture_entry,
)


def make_git_garden(tmp: Path) -> Path:
    garden = tmp / 'garden'
    garden.mkdir()
    for cmd in [
        ['git', 'init', str(garden)],
        ['git', '-C', str(garden), 'config', 'user.email', 'test@test.com'],
        ['git', '-C', str(garden), 'config', 'user.name', 'Test'],
    ]:
        subprocess.run(cmd, check=True, capture_output=True)
    (garden / 'GARDEN.md').write_text(
        '**Last assigned ID:** GE-0000\n'
        '**Last full DEDUPE sweep:** 2026-04-15\n'
        '**Entries merged since last sweep:** 0\n'
        '**Drift threshold:** 10\n'
    )
    (garden / 'java').mkdir()
    (garden / 'java' / 'INDEX.md').write_text(
        '| GE-ID | Title | Type | Score |\n|-------|-------|------|-------|\n'
    )
    subprocess.run(['git', '-C', str(garden), 'add', '.'], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(garden), 'commit', '-m', 'init'],
                   check=True, capture_output=True)
    return garden


VALID_ARGS = {
    'title': 'CompletableFuture.get() blocks carrier thread in virtual thread context',
    'type': 'gotcha',
    'domain': 'java',
    'stack': 'Java 21+, Virtual Threads',
    'tags': ['java', 'virtual-threads', 'blocking'],
    'score': 11,
    'body': (
        '**Symptom:** Performance regression under virtual threads.\n\n'
        '### Root cause\nget() pins carrier thread.\n\n'
        '### Fix\nUse join() or structured concurrency.\n\n'
        '### Why this is non-obvious\nVirtual threads look transparent.\n'
    ),
}


class TestValidateCaptureArgs(unittest.TestCase):

    def test_valid_args_no_errors(self):
        self.assertEqual(validate_capture_args(**VALID_ARGS), [])

    def test_missing_title_error(self):
        errors = validate_capture_args(**{**VALID_ARGS, 'title': ''})
        self.assertTrue(any('title' in e for e in errors))

    def test_invalid_type_error(self):
        errors = validate_capture_args(**{**VALID_ARGS, 'type': 'bogus'})
        self.assertTrue(any('type' in e for e in errors))

    def test_score_below_minimum_error(self):
        errors = validate_capture_args(**{**VALID_ARGS, 'score': 7})
        self.assertTrue(any('score' in e for e in errors))

    def test_score_at_minimum_ok(self):
        self.assertEqual(validate_capture_args(**{**VALID_ARGS, 'score': 8}), [])

    def test_missing_domain_error(self):
        errors = validate_capture_args(**{**VALID_ARGS, 'domain': ''})
        self.assertTrue(any('domain' in e for e in errors))

    def test_empty_tags_is_ok(self):
        self.assertEqual(validate_capture_args(**{**VALID_ARGS, 'tags': []}), [])

    def test_empty_body_error(self):
        errors = validate_capture_args(**{**VALID_ARGS, 'body': ''})
        self.assertTrue(any('body' in e for e in errors))

    def test_valid_types_all_accepted(self):
        for t in ('gotcha', 'technique', 'undocumented'):
            self.assertEqual(validate_capture_args(**{**VALID_ARGS, 'type': t}), [],
                             f"Type {t!r} should be valid")


class TestGenerateGeId(unittest.TestCase):

    def test_format_matches_pattern(self):
        self.assertRegex(generate_ge_id(), r'^GE-\d{8}-[0-9a-f]{6}$')

    def test_two_calls_different_ids(self):
        self.assertNotEqual(generate_ge_id(), generate_ge_id())

    def test_contains_todays_date(self):
        from datetime import date
        today = date.today().strftime('%Y%m%d')
        self.assertIn(today, generate_ge_id())


class TestBuildEntryContent(unittest.TestCase):

    def test_produces_yaml_frontmatter(self):
        content = build_entry_content(ge_id='GE-20260415-aabbcc', **VALID_ARGS)
        self.assertTrue(content.startswith('---\n'))
        self.assertIn('\n---\n', content)

    def test_contains_ge_id(self):
        content = build_entry_content(ge_id='GE-20260415-aabbcc', **VALID_ARGS)
        self.assertIn('GE-20260415-aabbcc', content)

    def test_contains_title(self):
        content = build_entry_content(ge_id='GE-20260415-aabbcc', **VALID_ARGS)
        self.assertIn(VALID_ARGS['title'], content)

    def test_contains_domain(self):
        content = build_entry_content(ge_id='GE-20260415-aabbcc', **VALID_ARGS)
        self.assertIn(f"domain: {VALID_ARGS['domain']}", content)

    def test_contains_score(self):
        content = build_entry_content(ge_id='GE-20260415-aabbcc', **VALID_ARGS)
        self.assertIn(f"score: {VALID_ARGS['score']}", content)

    def test_contains_body_content(self):
        content = build_entry_content(ge_id='GE-20260415-aabbcc', **VALID_ARGS)
        self.assertIn('### Root cause', content)

    def test_contains_id_in_body(self):
        content = build_entry_content(ge_id='GE-20260415-aabbcc', **VALID_ARGS)
        self.assertIn('**ID:** GE-20260415-aabbcc', content)


class TestCaptureEntry(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.garden = make_git_garden(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_capture_returns_dict(self):
        self.assertIsInstance(capture_entry(self.garden, **VALID_ARGS), dict)

    def test_capture_returns_status_ok(self):
        result = capture_entry(self.garden, **VALID_ARGS)
        self.assertEqual(result['status'], 'ok', result)

    def test_capture_returns_ge_id(self):
        result = capture_entry(self.garden, **VALID_ARGS)
        self.assertIn('ge_id', result)
        self.assertRegex(result['ge_id'], r'^GE-\d{8}-[0-9a-f]{6}$')

    def test_capture_returns_branch(self):
        result = capture_entry(self.garden, **VALID_ARGS)
        self.assertIn('branch', result)
        self.assertIn('submit/', result['branch'])

    def test_entry_file_created_on_branch(self):
        result = capture_entry(self.garden, **VALID_ARGS)
        branch = result['branch']
        ge_id = result['ge_id']
        file_check = subprocess.run(
            ['git', '-C', str(self.garden), 'show', f'{branch}:java/{ge_id}.md'],
            capture_output=True, text=True
        )
        self.assertEqual(file_check.returncode, 0, file_check.stderr)
        self.assertIn(VALID_ARGS['title'], file_check.stdout)

    def test_invalid_args_returns_error_status(self):
        result = capture_entry(self.garden, title='', type='gotcha',
                               domain='java', stack='Java', tags=[], score=5, body='x')
        self.assertEqual(result['status'], 'error')
        self.assertIn('errors', result)

    def test_capture_returns_to_main_branch(self):
        capture_entry(self.garden, **VALID_ARGS)
        current = subprocess.run(
            ['git', '-C', str(self.garden), 'branch', '--show-current'],
            capture_output=True, text=True
        ).stdout.strip()
        self.assertEqual(current, 'main')


if __name__ == '__main__':
    unittest.main(verbosity=2)
