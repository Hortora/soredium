#!/usr/bin/env python3
"""Unit, integration, and CLI tests for garden_config.py."""

import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
from garden_config import (
    load_config, validate_config, resolve_paths,
    find_garden_for_domain, get_upstream_chain,
)

CLI = Path(__file__).parent.parent / 'scripts' / 'garden_config.py'


def run_cli(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI)] + list(args),
        capture_output=True, text=True
    )


def write_schema(garden_dir: Path, role: str, ge_prefix: str,
                 domains: list, name: str = 'test', upstream: list = None):
    garden_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        '---', f'name: {name}', 'description: "test"',
        f'role: {role}', f'ge_prefix: {ge_prefix}',
        'schema_version: "1.0"', f'domains: [{", ".join(domains)}]',
    ]
    if upstream:
        lines.append('upstream:')
        for u in upstream:
            lines.append(f'  - {u}')
    lines.extend(['---', ''])
    (garden_dir / 'SCHEMA.md').write_text('\n'.join(lines))


VALID_TOML = """\
[[gardens]]
name = "jvm-garden"
path = "/tmp/jvm-garden"

[[gardens]]
name = "tools-garden"
path = "/tmp/tools-garden"
"""


class TestLoadConfig(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_loads_valid_toml(self):
        p = self.root / 'garden-config.toml'
        p.write_text(VALID_TOML)
        result = load_config(p)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['name'], 'jvm-garden')
        self.assertEqual(result[1]['name'], 'tools-garden')

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_config(self.root / 'nonexistent.toml')

    def test_invalid_toml_raises(self):
        p = self.root / 'bad.toml'
        p.write_text('[[gardens\nbroken')
        with self.assertRaises(Exception):
            load_config(p)

    def test_empty_file_returns_empty_list(self):
        p = self.root / 'empty.toml'
        p.write_text('')
        result = load_config(p)
        self.assertEqual(result, [])

    def test_single_garden(self):
        p = self.root / 'single.toml'
        p.write_text('[[gardens]]\nname = "jvm-garden"\npath = "/tmp/jvm"\n')
        result = load_config(p)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['name'], 'jvm-garden')


class TestValidateConfig(unittest.TestCase):

    def test_valid_config_no_errors(self):
        gardens = [
            {'name': 'jvm-garden', 'path': '/tmp/jvm'},
            {'name': 'tools-garden', 'path': '/tmp/tools'},
        ]
        errors, warnings = validate_config(gardens)
        self.assertEqual(errors, [])

    def test_missing_name_error(self):
        errors, _ = validate_config([{'path': '/tmp/jvm'}])
        self.assertEqual(len(errors), 1)
        self.assertIn('name', errors[0])

    def test_missing_path_error(self):
        errors, _ = validate_config([{'name': 'jvm-garden'}])
        self.assertEqual(len(errors), 1)
        self.assertIn('path', errors[0])

    def test_duplicate_names_error(self):
        gardens = [
            {'name': 'jvm-garden', 'path': '/tmp/a'},
            {'name': 'jvm-garden', 'path': '/tmp/b'},
        ]
        errors, _ = validate_config(gardens)
        self.assertEqual(len(errors), 1)
        self.assertIn('duplicate', errors[0].lower())

    def test_empty_list_valid(self):
        errors, warnings = validate_config([])
        self.assertEqual(errors, [])

    def test_both_missing_fields_both_reported(self):
        errors, _ = validate_config([{}])
        self.assertGreaterEqual(len(errors), 2)


class TestResolvePaths(unittest.TestCase):

    def test_tilde_expanded(self):
        gardens = [{'name': 'jvm', 'path': '~/.hortora/jvm-garden'}]
        result = resolve_paths(gardens)
        self.assertNotIn('~', result[0]['path'])
        self.assertIn('.hortora', result[0]['path'])

    def test_absolute_path_unchanged(self):
        gardens = [{'name': 'jvm', 'path': '/absolute/path'}]
        result = resolve_paths(gardens)
        self.assertEqual(result[0]['path'], '/absolute/path')

    def test_does_not_modify_original(self):
        gardens = [{'name': 'jvm', 'path': '~/.hortora/jvm'}]
        resolve_paths(gardens)
        self.assertEqual(gardens[0]['path'], '~/.hortora/jvm')

    def test_multiple_gardens_all_resolved(self):
        gardens = [
            {'name': 'a', 'path': '~/a'},
            {'name': 'b', 'path': '~/b'},
        ]
        result = resolve_paths(gardens)
        for g in result:
            self.assertNotIn('~', g['path'])


class TestFindGardenForDomain(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _make_garden(self, name: str, domains: list, role: str = 'canonical') -> dict:
        gdir = self.root / name
        write_schema(gdir, role=role, ge_prefix='GE-', domains=domains, name=name)
        return {'name': name, 'path': str(gdir)}

    def test_finds_correct_garden(self):
        jvm = self._make_garden('jvm-garden', ['java', 'quarkus'])
        tools = self._make_garden('tools-garden', ['tools', 'cli'])
        result = find_garden_for_domain([jvm, tools], 'java')
        self.assertEqual(result['name'], 'jvm-garden')

    def test_returns_none_when_not_found(self):
        jvm = self._make_garden('jvm-garden', ['java'])
        result = find_garden_for_domain([jvm], 'python')
        self.assertIsNone(result)

    def test_empty_list_returns_none(self):
        result = find_garden_for_domain([], 'java')
        self.assertIsNone(result)

    def test_garden_without_schema_skipped(self):
        no_schema = {'name': 'no-schema', 'path': str(self.root / 'empty')}
        (self.root / 'empty').mkdir()
        jvm = self._make_garden('jvm-garden', ['java'])
        result = find_garden_for_domain([no_schema, jvm], 'java')
        self.assertEqual(result['name'], 'jvm-garden')

    def test_domain_in_second_garden(self):
        jvm = self._make_garden('jvm-garden', ['java'])
        tools = self._make_garden('tools-garden', ['tools', 'cli'])
        result = find_garden_for_domain([jvm, tools], 'tools')
        self.assertEqual(result['name'], 'tools-garden')


class TestGetUpstreamChain(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _make_garden(self, name: str, role: str, domains: list,
                     upstream_names: list = None) -> tuple:
        gdir = self.root / name
        upstream_urls = []
        if upstream_names:
            upstream_urls = [f'https://github.com/Hortora/{n}' for n in upstream_names]
        write_schema(gdir, role=role, ge_prefix='GE-', domains=domains,
                     name=name, upstream=upstream_urls)
        garden = {'name': name, 'path': str(gdir)}
        return gdir, garden

    def test_canonical_returns_empty_chain(self):
        gdir, garden = self._make_garden('jvm-garden', 'canonical', ['java'])
        chain = get_upstream_chain([garden], Path(gdir))
        self.assertEqual(chain, [])

    def test_child_returns_parent(self):
        jvm_dir, jvm = self._make_garden('jvm-garden', 'canonical', ['java'])
        my_dir, my = self._make_garden('my-garden', 'child', ['java'],
                                       upstream_names=['jvm-garden'])
        chain = get_upstream_chain([jvm, my], Path(my_dir))
        self.assertEqual(len(chain), 1)
        self.assertEqual(str(chain[0]), str(jvm_dir))

    def test_three_level_chain(self):
        root_dir, root = self._make_garden('root', 'canonical', ['java'])
        mid_dir, mid = self._make_garden('mid', 'child', ['java'],
                                         upstream_names=['root'])
        leaf_dir, leaf = self._make_garden('leaf', 'child', ['java'],
                                           upstream_names=['mid'])
        gardens = [root, mid, leaf]
        chain = get_upstream_chain(gardens, Path(leaf_dir))
        self.assertEqual(len(chain), 2)
        self.assertEqual(str(chain[0]), str(mid_dir))
        self.assertEqual(str(chain[1]), str(root_dir))

    def test_unknown_upstream_returns_empty(self):
        my_dir, my = self._make_garden('my-garden', 'child', ['java'],
                                       upstream_names=['nonexistent'])
        chain = get_upstream_chain([my], Path(my_dir))
        self.assertEqual(chain, [])

    def test_peer_returns_empty_chain(self):
        gdir, garden = self._make_garden('peer-garden', 'peer', ['tools'])
        chain = get_upstream_chain([garden], Path(gdir))
        self.assertEqual(chain, [])


class TestGardenConfigIntegration(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.jvm_dir = self.root / 'jvm-garden'
        self.my_dir = self.root / 'my-garden'
        write_schema(self.jvm_dir, role='canonical', ge_prefix='JE-',
                     domains=['java', 'quarkus'], name='jvm-garden')
        write_schema(self.my_dir, role='child', ge_prefix='ME-',
                     domains=['java'], name='my-garden',
                     upstream=['https://github.com/Hortora/jvm-garden'])
        self.config_path = self.root / 'garden-config.toml'
        self.config_path.write_text(
            f'[[gardens]]\nname = "jvm-garden"\npath = "{self.jvm_dir}"\n\n'
            f'[[gardens]]\nname = "my-garden"\npath = "{self.my_dir}"\n'
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_domain_routing_via_schema(self):
        gardens = load_config(self.config_path)
        result = find_garden_for_domain(gardens, 'quarkus')
        self.assertEqual(result['name'], 'jvm-garden')

    def test_upstream_chain_resolution(self):
        gardens = load_config(self.config_path)
        chain = get_upstream_chain(gardens, self.my_dir)
        self.assertEqual(len(chain), 1)
        self.assertEqual(str(chain[0]), str(self.jvm_dir))

    def test_domain_not_in_any_garden(self):
        gardens = load_config(self.config_path)
        result = find_garden_for_domain(gardens, 'python')
        self.assertIsNone(result)


class TestGardenConfigCLI(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.jvm_dir = self.root / 'jvm-garden'
        write_schema(self.jvm_dir, role='canonical', ge_prefix='JE-',
                     domains=['java', 'quarkus'], name='jvm-garden')
        self.config_path = self.root / 'garden-config.toml'
        self.config_path.write_text(
            f'[[gardens]]\nname = "jvm-garden"\npath = "{self.jvm_dir}"\n'
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_status_exits_0(self):
        result = run_cli('status', '--config', str(self.config_path))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_status_shows_garden_names(self):
        result = run_cli('status', '--config', str(self.config_path))
        self.assertIn('jvm-garden', result.stdout)

    def test_missing_config_exits_1(self):
        result = run_cli('status', '--config', '/nonexistent/config.toml')
        self.assertEqual(result.returncode, 1)

    def test_status_shows_role_and_domains(self):
        result = run_cli('status', '--config', str(self.config_path))
        self.assertIn('canonical', result.stdout)
        self.assertIn('java', result.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)
