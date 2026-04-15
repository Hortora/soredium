#!/usr/bin/env python3
"""Comprehensive MCP server tests — unit, protocol integration, and E2E happy paths.

Run:
  python3 -m pytest tests/test_garden_mcp_server_extended.py -v

The IsolatedAsyncioTestCase classes use the MCP stdio_client to communicate with
the server via the actual MCP JSON-RPC protocol, not by calling Python functions
directly. This is the only way to verify FastMCP serialization, tool discovery,
and protocol correctness.
"""

import asyncio
import importlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
import garden_mcp_server

SERVER = Path(__file__).parent.parent / 'scripts' / 'garden_mcp_server.py'

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _git(*args):
    subprocess.run(list(args), check=True, capture_output=True)


def make_rich_garden(tmp: Path) -> Path:
    """Garden with 2 committed entries: one java (Hibernate), one tools (sed)."""
    garden = tmp / 'garden'
    garden.mkdir()
    _git('git', 'init', str(garden))
    _git('git', '-C', str(garden), 'config', 'user.email', 'test@test.com')
    _git('git', '-C', str(garden), 'config', 'user.name', 'Test')

    (garden / 'GARDEN.md').write_text(
        '# test-garden\n\n'
        '**Last assigned ID:** GE-0002\n'
        '**Last full DEDUPE sweep:** 2026-04-15\n'
        '**Entries merged since last sweep:** 2\n'
        '**Drift threshold:** 10\n'
        '**Last staleness review:** 2026-04-01\n\n'
        '## By Technology\n\n'
        '### Java\n'
        '| GE-ID | Title | Type | Score |\n'
        '|-------|-------|------|-------|\n'
        '| [GE-20260414-aa0001](java/GE-20260414-aa0001.md) | '
        'Hibernate @PreUpdate fires at flush | gotcha | 12 |\n\n'
        '### Tools\n'
        '| GE-ID | Title | Type | Score |\n'
        '|-------|-------|------|-------|\n'
        '| [GE-20260414-bb0001](tools/GE-20260414-bb0001.md) | '
        'macOS BSD sed silently ignores word boundaries | gotcha | 11 |\n\n'
        '## By Symptom / Type\n\n## By Label\n\n'
    )

    (garden / 'java').mkdir()
    (garden / 'java' / 'GE-20260414-aa0001.md').write_text(
        '---\nid: GE-20260414-aa0001\n'
        'title: "Hibernate @PreUpdate fires at flush time not at persist"\n'
        'type: gotcha\ndomain: java\nstack: "Hibernate ORM 6.x"\n'
        'tags: [hibernate, jpa, lifecycle, flush]\n'
        'score: 12\nverified: true\nstaleness_threshold: 730\nsubmitted: 2026-04-14\n---\n\n'
        '## Hibernate @PreUpdate fires at flush time not at persist\n\n'
        '**ID:** GE-20260414-aa0001\n**Stack:** Hibernate ORM 6.x\n'
        '**Symptom:** @PreUpdate callback not firing when expected.\n\n'
        '### Root cause\nFires at flush, not at persist() call.\n\n'
        '### Fix\nForce a flush or restructure lifecycle logic.\n\n'
        '### Why this is non-obvious\nThe method name implies persist time.\n\n'
        '*Score: 12/15 · Included because: common JPA trap · Reservation: none*\n'
    )

    (garden / 'tools').mkdir()
    (garden / 'tools' / 'GE-20260414-bb0001.md').write_text(
        '---\nid: GE-20260414-bb0001\n'
        'title: "macOS BSD sed silently ignores word boundaries"\n'
        'type: gotcha\ndomain: tools\nstack: "macOS, BSD sed"\n'
        'tags: [sed, macos, regex, bsd]\n'
        'score: 11\nverified: true\nstaleness_threshold: 730\nsubmitted: 2026-04-14\n---\n\n'
        '## macOS BSD sed silently ignores word boundaries\n\n'
        '**ID:** GE-20260414-bb0001\n**Stack:** macOS, BSD sed\n'
        '**Symptom:** sed replacement does nothing, no error.\n\n'
        '### Root cause\nBSD sed uses ERE differently from GNU sed.\n\n'
        '### Fix\nUse perl -pi -e instead of sed -i.\n\n'
        '### Why this is non-obvious\nBoth claim POSIX compatibility.\n\n'
        '*Score: 11/15 · Included because: macOS gotcha · Reservation: none*\n'
    )

    _git('git', '-C', str(garden), 'add', '.')
    _git('git', '-C', str(garden), 'commit', '-m', 'init')
    return garden


def make_empty_garden(tmp: Path) -> Path:
    """Garden with no entries — just GARDEN.md."""
    garden = tmp / 'empty-garden'
    garden.mkdir(parents=True, exist_ok=True)
    _git('git', 'init', str(garden))
    _git('git', '-C', str(garden), 'config', 'user.email', 'test@test.com')
    _git('git', '-C', str(garden), 'config', 'user.name', 'Test')
    (garden / 'GARDEN.md').write_text(
        '# empty-garden\n\n'
        '**Last assigned ID:** GE-0000\n'
        '**Last full DEDUPE sweep:** 2026-04-15\n'
        '**Entries merged since last sweep:** 0\n'
        '**Drift threshold:** 10\n'
        '**Last staleness review:** never\n'
    )
    (garden / 'java').mkdir()
    _git('git', '-C', str(garden), 'add', '.')
    _git('git', '-C', str(garden), 'commit', '-m', 'init')
    return garden


def _server_params(garden: Path) -> StdioServerParameters:
    return StdioServerParameters(
        command='python3',
        args=[str(SERVER)],
        env={**os.environ, 'HORTORA_GARDEN': str(garden)},
    )


def _parse_dict(result) -> dict:
    """Parse a CallToolResult that returns a dict (status, capture).
    FastMCP serializes dicts as a single JSON TextContent item."""
    if not result.content:
        return {}
    return json.loads(result.content[0].text)


def _parse_list(result) -> list:
    """Parse a CallToolResult that returns a list (search).
    FastMCP serializes each list element as a separate TextContent item.
    An empty list produces zero content items."""
    if not result.content:
        return []
    return [json.loads(c.text) for c in result.content]


def _parse(result) -> object:
    """Parse JSON from a CallToolResult — use _parse_dict or _parse_list
    for tool-specific parsing where the return type is known."""
    if not result.content:
        return None
    return json.loads(result.content[0].text)


# ---------------------------------------------------------------------------
# Group 1: Extended unit tests (Python function layer — no MCP protocol)
# ---------------------------------------------------------------------------

class TestMcpServerUnitExpanded(unittest.TestCase):
    """Extended direct-call tests for tool functions. Verifies business logic
    in isolation from the MCP protocol layer."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.garden = make_rich_garden(Path(self.tmp.name))
        importlib.reload(garden_mcp_server)
        self.s = garden_mcp_server

    def tearDown(self):
        self.tmp.cleanup()

    # garden_status

    def test_status_all_required_fields_present(self):
        r = self.s.garden_status(str(self.garden))
        for field in ('entry_count', 'drift', 'threshold', 'dedupe_recommended',
                      'last_sweep', 'last_staleness_review', 'garden_path'):
            self.assertIn(field, r, f"Missing field: {field}")

    def test_status_drift_value_correct(self):
        r = self.s.garden_status(str(self.garden))
        self.assertEqual(r['drift'], 2)

    def test_status_dedupe_not_recommended_below_threshold(self):
        r = self.s.garden_status(str(self.garden))
        self.assertFalse(r['dedupe_recommended'])  # drift=2 < threshold=10

    def test_status_dedupe_recommended_when_at_threshold(self):
        # Write a garden with drift = threshold
        g = make_empty_garden(Path(self.tmp.name) / 'high')
        (g / 'GARDEN.md').write_text(
            '**Last assigned ID:** GE-0000\n'
            '**Last full DEDUPE sweep:** 2026-04-15\n'
            '**Entries merged since last sweep:** 10\n'
            '**Drift threshold:** 10\n'
        )
        _git('git', '-C', str(g), 'add', '.')
        _git('git', '-C', str(g), 'commit', '-m', 'update drift')
        r = self.s.garden_status(str(g))
        self.assertTrue(r['dedupe_recommended'])

    def test_status_empty_garden_returns_zero_entries(self):
        g = make_empty_garden(Path(self.tmp.name) / 'empty')
        r = self.s.garden_status(str(g))
        self.assertEqual(r['entry_count'], 0)

    # garden_search

    def test_search_returns_entries_with_all_required_fields(self):
        results = self.s.garden_search('hibernate', garden_path=str(self.garden))
        self.assertTrue(len(results) > 0)
        for r in results:
            for field in ('id', 'title', 'domain', 'body'):
                self.assertIn(field, r, f"Missing field {field!r} in result")

    def test_search_domain_filter_excludes_other_domains(self):
        results = self.s.garden_search('sed', domain='java',
                                        garden_path=str(self.garden))
        # 'sed' is only in tools domain; java filter should exclude it
        ids = [r['id'] for r in results]
        self.assertNotIn('GE-20260414-bb0001', ids)

    def test_search_technology_filter_restricts_results(self):
        results = self.s.garden_search('flush', technology='Java',
                                        garden_path=str(self.garden))
        self.assertTrue(len(results) > 0)
        for r in results:
            self.assertEqual(r['domain'], 'java')

    def test_search_unrelated_query_returns_empty(self):
        results = self.s.garden_search('xyzzy_nonexistent_9999',
                                        garden_path=str(self.garden))
        self.assertEqual(results, [])

    def test_search_finds_tools_entry_with_domain_filter(self):
        results = self.s.garden_search('sed bsd', domain='tools',
                                        garden_path=str(self.garden))
        ids = [r['id'] for r in results]
        self.assertIn('GE-20260414-bb0001', ids)

    # garden_capture

    def test_capture_technique_type_accepted(self):
        r = self.s.garden_capture(
            title='Use git worktree for isolated feature branches',
            type='technique', domain='tools', stack='git',
            tags=['git', 'workflow'], score=10,
            body='**What it achieves:** Isolation.\n\n### The technique\nRun git worktree add.\n\n### Why this is non-obvious\nMost devs use stash.\n',
            garden_path=str(self.garden),
        )
        self.assertEqual(r['status'], 'ok')

    def test_capture_undocumented_type_accepted(self):
        r = self.s.garden_capture(
            title='git -C flag allows running git from any directory',
            type='undocumented', domain='tools', stack='git (all versions)',
            tags=['git', 'cli'], score=9,
            body='**What it is:** -C flag.\n\n### How to use it\ngit -C /path/to/repo status.\n\n### Why it\'s not obvious\nNot widely documented.\n',
            garden_path=str(self.garden),
        )
        self.assertEqual(r['status'], 'ok')

    def test_capture_creates_branch_that_persists_after_return(self):
        r = self.s.garden_capture(
            title='CompletableFuture get blocks carrier thread',
            type='gotcha', domain='java', stack='Java 21+',
            tags=['java', 'virtual-threads'], score=11,
            body='**Symptom:** Slow.\n\n### Root cause\nBlocks carrier.\n\n### Fix\nUse join.\n\n### Why non-obvious\nLooks cooperative.\n',
            garden_path=str(self.garden),
        )
        self.assertEqual(r['status'], 'ok')
        branch = r['branch']
        # Verify branch exists in the git repo
        branches = subprocess.run(
            ['git', '-C', str(self.garden), 'branch', '--list', branch],
            capture_output=True, text=True
        ).stdout
        self.assertIn(branch, branches)

    def test_capture_invalid_type_returns_error_not_exception(self):
        r = self.s.garden_capture(
            title='Test entry', type='invalid-type', domain='java',
            stack='Java', tags=[], score=10, body='content',
            garden_path=str(self.garden),
        )
        self.assertEqual(r['status'], 'error')
        self.assertIn('errors', r)

    def test_capture_empty_body_returns_error(self):
        r = self.s.garden_capture(
            title='Test entry', type='gotcha', domain='java',
            stack='Java', tags=[], score=10, body='',
            garden_path=str(self.garden),
        )
        self.assertEqual(r['status'], 'error')

    def test_two_captures_produce_different_ge_ids(self):
        body = '**Symptom:** X.\n\n### Root cause\nY.\n\n### Fix\nZ.\n\n### Why non-obvious\nW.\n'
        r1 = self.s.garden_capture(
            title='First distinct entry about virtual threads blocking',
            type='gotcha', domain='java', stack='Java 21+',
            tags=['java'], score=9, body=body,
            garden_path=str(self.garden),
        )
        r2 = self.s.garden_capture(
            title='Second distinct entry about heap allocation patterns',
            type='gotcha', domain='java', stack='Java 21+',
            tags=['java'], score=9, body=body,
            garden_path=str(self.garden),
        )
        self.assertNotEqual(r1['ge_id'], r2['ge_id'])
        self.assertNotEqual(r1['branch'], r2['branch'])


# ---------------------------------------------------------------------------
# Group 2: MCP protocol integration tests (real JSON-RPC via stdio_client)
# ---------------------------------------------------------------------------

class TestMcpProtocolToolDiscovery(unittest.IsolatedAsyncioTestCase):
    """Verify the server advertises the right tools via MCP list_tools.
    Each test method spawns its own server subprocess for full isolation."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.garden = make_rich_garden(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    async def _list_tools(self):
        async with stdio_client(_server_params(self.garden)) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                return await session.list_tools()

    async def test_server_initializes_via_mcp_protocol(self):
        async with stdio_client(_server_params(self.garden)) as (r, w):
            async with ClientSession(r, w) as session:
                result = await session.initialize()
                self.assertIsNotNone(result)

    async def test_list_tools_returns_exactly_three_tools(self):
        result = await self._list_tools()
        self.assertEqual(len(result.tools), 3)

    async def test_garden_search_tool_listed(self):
        result = await self._list_tools()
        names = [t.name for t in result.tools]
        self.assertIn('garden_search', names)

    async def test_garden_status_tool_listed(self):
        result = await self._list_tools()
        names = [t.name for t in result.tools]
        self.assertIn('garden_status', names)

    async def test_garden_capture_tool_listed(self):
        result = await self._list_tools()
        names = [t.name for t in result.tools]
        self.assertIn('garden_capture', names)

    async def test_garden_search_tool_has_description(self):
        result = await self._list_tools()
        tool = next(t for t in result.tools if t.name == 'garden_search')
        self.assertIsNotNone(tool.description)
        self.assertGreater(len(tool.description), 10)

    async def test_garden_search_tool_has_query_parameter(self):
        result = await self._list_tools()
        tool = next(t for t in result.tools if t.name == 'garden_search')
        schema = tool.inputSchema
        self.assertIn('query', schema.get('properties', {}))

    async def test_garden_capture_tool_has_required_parameters(self):
        result = await self._list_tools()
        tool = next(t for t in result.tools if t.name == 'garden_capture')
        schema = tool.inputSchema
        props = schema.get('properties', {})
        for param in ('title', 'type', 'domain', 'stack', 'score', 'body'):
            self.assertIn(param, props, f"Missing parameter: {param}")

    async def test_garden_status_tool_has_garden_path_parameter(self):
        result = await self._list_tools()
        tool = next(t for t in result.tools if t.name == 'garden_status')
        props = tool.inputSchema.get('properties', {})
        self.assertIn('garden_path', props)


class TestMcpProtocolToolCalls(unittest.IsolatedAsyncioTestCase):
    """Call each tool via MCP JSON-RPC protocol and verify response structure.
    Tests go through the full FastMCP serialization/deserialization path."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.garden = make_rich_garden(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    async def _call(self, tool: str, args: dict):
        async with stdio_client(_server_params(self.garden)) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                return await session.call_tool(tool, args)

    # garden_status via protocol

    async def test_call_garden_status_returns_no_error(self):
        result = await self._call('garden_status', {'garden_path': str(self.garden)})
        self.assertFalse(result.isError)

    async def test_call_garden_status_returns_json(self):
        result = await self._call('garden_status', {'garden_path': str(self.garden)})
        data = _parse_dict(result)
        self.assertIsInstance(data, dict)

    async def test_call_garden_status_correct_entry_count(self):
        result = await self._call('garden_status', {'garden_path': str(self.garden)})
        data = _parse_dict(result)
        self.assertEqual(data['entry_count'], 2)

    async def test_call_garden_status_has_dedupe_recommended(self):
        result = await self._call('garden_status', {'garden_path': str(self.garden)})
        data = _parse_dict(result)
        self.assertIn('dedupe_recommended', data)
        self.assertIsInstance(data['dedupe_recommended'], bool)

    # garden_search via protocol
    # NOTE: FastMCP serializes list returns as one TextContent per element.
    # Use _parse_list() for all garden_search results.

    async def test_call_garden_search_returns_list(self):
        result = await self._call('garden_search', {
            'query': 'hibernate flush',
            'garden_path': str(self.garden),
        })
        self.assertFalse(result.isError)
        data = _parse_list(result)
        self.assertIsInstance(data, list)

    async def test_call_garden_search_finds_hibernate_entry(self):
        result = await self._call('garden_search', {
            'query': 'hibernate flush',
            'garden_path': str(self.garden),
        })
        data = _parse_list(result)
        self.assertTrue(len(data) > 0)
        self.assertTrue(any('aa0001' in r['id'] for r in data))

    async def test_call_garden_search_empty_query_returns_empty_list(self):
        result = await self._call('garden_search', {
            'query': '',
            'garden_path': str(self.garden),
        })
        data = _parse_list(result)
        self.assertEqual(data, [])

    async def test_call_garden_search_unrelated_query_returns_empty(self):
        result = await self._call('garden_search', {
            'query': 'xyzzy_nonexistent_term_99999',
            'garden_path': str(self.garden),
        })
        data = _parse_list(result)
        self.assertEqual(data, [])

    async def test_call_garden_search_domain_filter_works(self):
        result = await self._call('garden_search', {
            'query': 'sed bsd regex',
            'domain': 'tools',
            'garden_path': str(self.garden),
        })
        data = _parse_list(result)
        self.assertTrue(len(data) > 0)
        self.assertTrue(any('bb0001' in r['id'] for r in data))

    # garden_capture via protocol

    async def test_call_garden_capture_valid_returns_ok_status(self):
        result = await self._call('garden_capture', {
            'title': 'Virtual thread pinning via synchronized blocks',
            'type': 'gotcha',
            'domain': 'java',
            'stack': 'Java 21+, Virtual Threads',
            'tags': ['java', 'virtual-threads', 'synchronized'],
            'score': 12,
            'body': (
                '**Symptom:** Virtual threads not scaling as expected.\n\n'
                '### Root cause\nSynchronized blocks pin the carrier thread.\n\n'
                '### Fix\nReplace synchronized with ReentrantLock.\n\n'
                '### Why this is non-obvious\n'
                'Synchronized "should" work with virtual threads.\n'
            ),
            'garden_path': str(self.garden),
        })
        self.assertFalse(result.isError)
        data = _parse_dict(result)
        self.assertEqual(data['status'], 'ok')
        self.assertIn('ge_id', data)
        self.assertIn('branch', data)

    async def test_call_garden_capture_low_score_returns_error_status(self):
        result = await self._call('garden_capture', {
            'title': 'Test entry', 'type': 'gotcha', 'domain': 'java',
            'stack': 'Java', 'tags': [], 'score': 3, 'body': 'content',
            'garden_path': str(self.garden),
        })
        self.assertFalse(result.isError)  # tool itself doesn't crash
        data = _parse_dict(result)
        self.assertEqual(data['status'], 'error')  # but returns error status

    async def test_call_garden_capture_ge_id_matches_pattern(self):
        import re
        result = await self._call('garden_capture', {
            'title': 'Quarkus reactive route requires @Blocking for sync DB access',
            'type': 'gotcha', 'domain': 'java',
            'stack': 'Quarkus 3.x, Mutiny',
            'tags': ['quarkus', 'reactive', 'blocking'], 'score': 11,
            'body': (
                '**Symptom:** Thread pinning warning in logs.\n\n'
                '### Root cause\nReactive routes run on event loop thread.\n\n'
                '### Fix\nAnnotate with @Blocking.\n\n'
                '### Why non-obvious\nAnnotation is not in main Quarkus docs.\n'
            ),
            'garden_path': str(self.garden),
        })
        data = _parse_dict(result)
        self.assertRegex(data['ge_id'], r'^GE-\d{8}-[0-9a-f]{6}$')


# ---------------------------------------------------------------------------
# Group 3: End-to-end happy path tests (full lifecycle via MCP protocol)
# ---------------------------------------------------------------------------

class TestMcpE2EHappyPath(unittest.IsolatedAsyncioTestCase):
    """Full end-to-end scenarios: multiple tools used in realistic sequences.
    These tests simulate actual assistant workflows — start, search, capture,
    verify — going through the complete MCP protocol stack each step."""

    def setUp(self):
        self.tmp = TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    async def _session(self, garden: Path):
        """Context manager returning an active ClientSession."""
        # Returns (stdio_cm, session_cm, session) — caller must manage context
        params = _server_params(garden)
        return params

    async def _run(self, garden: Path, tool: str, args: dict):
        """Single tool call against a garden. New server per call for isolation.
        Dispatches to _parse_list for garden_search (FastMCP per-element serialization),
        _parse_dict for garden_status and garden_capture."""
        async with stdio_client(_server_params(garden)) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                result = await session.call_tool(tool, args)
                if tool == 'garden_search':
                    return _parse_list(result)
                return _parse_dict(result)

    async def test_happy_path_status_shows_zero_entries_in_empty_garden(self):
        garden = make_empty_garden(Path(self.tmp.name))
        data = await self._run(garden, 'garden_status', {'garden_path': str(garden)})
        self.assertEqual(data['entry_count'], 0)
        self.assertFalse(data['dedupe_recommended'])

    async def test_happy_path_search_empty_garden_returns_nothing(self):
        garden = make_empty_garden(Path(self.tmp.name))
        data = await self._run(garden, 'garden_search', {
            'query': 'hibernate flush java',
            'garden_path': str(garden),
        })
        self.assertEqual(data, [])

    async def test_happy_path_status_shows_correct_count_in_populated_garden(self):
        garden = make_rich_garden(Path(self.tmp.name))
        data = await self._run(garden, 'garden_status', {'garden_path': str(garden)})
        self.assertEqual(data['entry_count'], 2)

    async def test_happy_path_search_finds_existing_entry(self):
        """The canonical happy path: search for a known problem, get the entry."""
        garden = make_rich_garden(Path(self.tmp.name))
        data = await self._run(garden, 'garden_search', {
            'query': 'hibernate PreUpdate flush time',
            'garden_path': str(garden),
        })
        self.assertTrue(len(data) > 0)
        first = data[0]
        self.assertIn('id', first)
        self.assertIn('title', first)
        self.assertIn('body', first)
        self.assertIn('aa0001', first['id'])
        self.assertIn('Hibernate', first['title'])

    async def test_happy_path_capture_then_branch_exists(self):
        """Capture a new entry → verify the git branch was created."""
        garden = make_empty_garden(Path(self.tmp.name))
        result = await self._run(garden, 'garden_capture', {
            'title': 'H2 reserved word key causes silent SQL failure',
            'type': 'gotcha',
            'domain': 'java',
            'stack': 'H2 2.x, Quarkus',
            'tags': ['h2', 'sql', 'reserved-word', 'java'],
            'score': 10,
            'body': (
                '**Symptom:** SQL syntax error with no helpful message.\n\n'
                '### Root cause\n"key" is an H2 reserved word.\n\n'
                '### Fix\nRename the column or quote it.\n\n'
                '### Why this is non-obvious\nError message points at SQL structure, not name.\n'
            ),
            'garden_path': str(garden),
        })
        self.assertEqual(result['status'], 'ok')
        branch = result['branch']
        ge_id = result['ge_id']
        # The branch must exist in the repo
        branches = subprocess.run(
            ['git', '-C', str(garden), 'branch', '--list', branch],
            capture_output=True, text=True
        ).stdout
        self.assertIn(branch, branches)
        # The entry file exists on the branch
        file_check = subprocess.run(
            ['git', '-C', str(garden), 'show', f'{branch}:java/{ge_id}.md'],
            capture_output=True, text=True
        )
        self.assertEqual(file_check.returncode, 0)
        self.assertIn('H2 reserved word', file_check.stdout)

    async def test_happy_path_capture_does_not_change_main_entry_count(self):
        """Capture creates a branch but does NOT merge — main HEAD entry count unchanged."""
        garden = make_rich_garden(Path(self.tmp.name))
        # Status before capture
        before = await self._run(garden, 'garden_status', {'garden_path': str(garden)})
        # Capture new entry
        await self._run(garden, 'garden_capture', {
            'title': 'QuarkusTransaction requiringNew for independent commits in tests',
            'type': 'technique', 'domain': 'java',
            'stack': 'Quarkus 3.x, JPA',
            'tags': ['quarkus', 'transaction', 'testing'], 'score': 11,
            'body': (
                '**What it achieves:** Independent transaction in test.\n\n'
                '### The technique\nQuarkusTransaction.requiringNew().run(() -> ...).\n\n'
                '### Why this is non-obvious\nNot in Quarkus testing docs.\n'
            ),
            'garden_path': str(garden),
        })
        # Status after capture — main HEAD unchanged, entry still on branch
        after = await self._run(garden, 'garden_status', {'garden_path': str(garden)})
        self.assertEqual(before['entry_count'], after['entry_count'])

    async def test_happy_path_multi_tool_session_status_search_capture(self):
        """Realistic session: check status, search, then capture when not found."""
        garden = make_rich_garden(Path(self.tmp.name))

        # 1. Check garden health
        status = await self._run(garden, 'garden_status',
                                  {'garden_path': str(garden)})
        self.assertGreater(status['entry_count'], 0)

        # 2. Search for relevant knowledge
        search = await self._run(garden, 'garden_search', {
            'query': 'sed regex macos word boundary',
            'garden_path': str(garden),
        })
        self.assertTrue(len(search) > 0)  # sed entry exists
        self.assertTrue(any('bb0001' in r['id'] for r in search))

        # 3. Capture a related but distinct entry not yet in the garden
        capture = await self._run(garden, 'garden_capture', {
            'title': 'macOS awk uses POSIX BRE not ERE — different from GNU awk',
            'type': 'gotcha', 'domain': 'tools',
            'stack': 'macOS, BSD awk',
            'tags': ['awk', 'macos', 'regex', 'bsd'], 'score': 10,
            'body': (
                '**Symptom:** awk regex patterns fail silently on macOS.\n\n'
                '### Root cause\nmacOS uses POSIX BRE; GNU awk uses ERE by default.\n\n'
                '### Fix\nUse gawk (brew install gawk) or escape patterns correctly.\n\n'
                '### Why this is non-obvious\nSame symptom as GNU awk but different cause.\n'
            ),
            'garden_path': str(garden),
        })
        self.assertEqual(capture['status'], 'ok')
        self.assertRegex(capture['ge_id'], r'^GE-\d{8}-[0-9a-f]{6}$')

    async def test_happy_path_search_respects_technology_filter(self):
        """Technology filter returns only entries from that technology section."""
        garden = make_rich_garden(Path(self.tmp.name))

        # Search Java domain — should find Hibernate, not sed
        java_results = await self._run(garden, 'garden_search', {
            'query': 'lifecycle callback firing',
            'technology': 'Java',
            'garden_path': str(garden),
        })
        ids = [r['id'] for r in java_results]
        self.assertIn('GE-20260414-aa0001', ids)
        self.assertNotIn('GE-20260414-bb0001', ids)


if __name__ == '__main__':
    unittest.main(verbosity=2)
