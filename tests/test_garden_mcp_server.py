#!/usr/bin/env python3
"""Integration tests for garden_mcp_server.py."""

import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

SERVER = Path(__file__).parent.parent / 'scripts' / 'garden_mcp_server.py'


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
        '**Last assigned ID:** GE-0001\n'
        '**Last full DEDUPE sweep:** 2026-04-15\n'
        '**Entries merged since last sweep:** 1\n'
        '**Drift threshold:** 10\n'
        '**Last staleness review:** never\n\n'
        '## By Technology\n\n'
        '### Java\n'
        '| GE-ID | Title | Type | Score |\n'
        '|-------|-------|------|-------|\n'
        '| [GE-20260414-aa0001](java/GE-20260414-aa0001.md) | '
        'Hibernate PreUpdate fires at flush | gotcha | 12 |\n\n'
        '## By Symptom / Type\n\n## By Label\n\n'
    )
    (garden / 'java').mkdir()
    (garden / 'java' / 'GE-20260414-aa0001.md').write_text(
        '---\nid: GE-20260414-aa0001\n'
        'title: "Hibernate @PreUpdate fires at flush time"\n'
        'type: gotcha\ndomain: java\nstack: "Hibernate ORM 6.x"\n'
        'tags: [hibernate, jpa, flush]\nscore: 12\nverified: true\n'
        'staleness_threshold: 730\nsubmitted: 2026-04-14\n---\n\n'
        '## Hibernate @PreUpdate fires at flush time\n\n'
        '**ID:** GE-20260414-aa0001\n**Stack:** Hibernate ORM 6.x\n'
        '**Symptom:** Callback not firing.\n\n'
        '### Root cause\nFires at flush.\n\n### Fix\nForce flush.\n'
    )
    subprocess.run(['git', '-C', str(garden), 'add', '.'], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(garden), 'commit', '-m', 'init'],
                   check=True, capture_output=True)
    return garden


class TestMcpServerFile(unittest.TestCase):
    """Verify the server file has the right structure."""

    def test_server_file_exists(self):
        self.assertTrue(SERVER.exists(), f"Missing: {SERVER}")

    def test_server_file_references_garden_search(self):
        self.assertIn('garden_search', SERVER.read_text())

    def test_server_file_references_garden_capture(self):
        self.assertIn('garden_capture', SERVER.read_text())

    def test_server_file_references_garden_status(self):
        self.assertIn('garden_status', SERVER.read_text())

    def test_server_file_uses_fastmcp(self):
        self.assertIn('FastMCP', SERVER.read_text())

    def test_server_file_imports_mcp_modules(self):
        content = SERVER.read_text()
        self.assertIn('mcp_garden_search', content)
        self.assertIn('mcp_garden_status', content)
        self.assertIn('mcp_garden_capture', content)


class TestMcpServerImport(unittest.TestCase):
    """Verify the server module can be imported."""

    def setUp(self):
        sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

    def test_server_module_importable(self):
        import garden_mcp_server
        self.assertIsNotNone(garden_mcp_server)

    def test_mcp_app_exists(self):
        import importlib
        import garden_mcp_server
        importlib.reload(garden_mcp_server)
        self.assertTrue(hasattr(garden_mcp_server, 'mcp'))


class TestMcpServerTools(unittest.TestCase):
    """Test the tool functions directly (bypassing MCP protocol)."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.garden = make_git_garden(Path(self.tmp.name))
        sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
        import importlib
        import garden_mcp_server
        importlib.reload(garden_mcp_server)
        self.server = garden_mcp_server

    def tearDown(self):
        self.tmp.cleanup()

    def test_garden_status_returns_dict(self):
        result = self.server.garden_status(str(self.garden))
        self.assertIsInstance(result, dict)
        self.assertIn('entry_count', result)

    def test_garden_status_correct_count(self):
        result = self.server.garden_status(str(self.garden))
        self.assertEqual(result['entry_count'], 1)

    def test_garden_search_returns_list(self):
        result = self.server.garden_search('hibernate flush',
                                           garden_path=str(self.garden))
        self.assertIsInstance(result, list)

    def test_garden_search_finds_entry(self):
        result = self.server.garden_search('hibernate flush',
                                           garden_path=str(self.garden))
        self.assertTrue(len(result) > 0)
        self.assertTrue(any('aa0001' in r['id'] for r in result))

    def test_garden_search_empty_returns_empty(self):
        result = self.server.garden_search('', garden_path=str(self.garden))
        self.assertEqual(result, [])

    def test_garden_capture_returns_dict(self):
        result = self.server.garden_capture(
            title='CompletableFuture blocks carrier thread',
            type='gotcha', domain='java', stack='Java 21+',
            tags=['java', 'virtual-threads'], score=11,
            body='**Symptom:** Blocking.\n\n### Root cause\nPins carrier.\n\n### Fix\nUse join().\n\n### Why non-obvious\nLooks transparent.\n',
            garden_path=str(self.garden),
        )
        self.assertIsInstance(result, dict)
        self.assertIn('status', result)

    def test_garden_capture_valid_returns_ok(self):
        result = self.server.garden_capture(
            title='CompletableFuture blocks carrier thread',
            type='gotcha', domain='java', stack='Java 21+',
            tags=['java', 'virtual-threads'], score=11,
            body='**Symptom:** Blocking.\n\n### Root cause\nPins carrier.\n\n### Fix\nUse join().\n\n### Why non-obvious\nLooks transparent.\n',
            garden_path=str(self.garden),
        )
        self.assertEqual(result['status'], 'ok')
        self.assertIn('ge_id', result)

    def test_garden_capture_low_score_returns_error(self):
        result = self.server.garden_capture(
            title='Test', type='gotcha', domain='java', stack='Java',
            tags=[], score=5, body='content',
            garden_path=str(self.garden),
        )
        self.assertEqual(result['status'], 'error')


if __name__ == '__main__':
    unittest.main(verbosity=2)
