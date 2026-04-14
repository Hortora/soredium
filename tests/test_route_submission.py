#!/usr/bin/env python3
"""Unit, integration, and CLI tests for route_submission.py."""

import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
from route_submission import route

CLI = Path(__file__).parent.parent / 'scripts' / 'route_submission.py'


def run_cli(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI)] + list(args),
        capture_output=True, text=True
    )


def write_schema(garden_dir: Path, role: str, ge_prefix: str,
                 domains: list, name: str = 'test'):
    garden_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        '---', f'name: {name}', 'description: "test"',
        f'role: {role}', f'ge_prefix: {ge_prefix}',
        'schema_version: "1.0"', f'domains: [{", ".join(domains)}]',
        '---', '',
    ]
    (garden_dir / 'SCHEMA.md').write_text('\n'.join(lines))


class TestRoute(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _make_garden(self, name: str, domains: list) -> dict:
        gdir = self.root / name
        write_schema(gdir, role='canonical', ge_prefix='GE-',
                     domains=domains, name=name)
        return {'name': name, 'path': str(gdir)}

    def test_routes_to_correct_garden(self):
        jvm = self._make_garden('jvm-garden', ['java', 'quarkus'])
        tools = self._make_garden('tools-garden', ['tools', 'cli'])
        result = route('java', [jvm, tools])
        self.assertEqual(result, Path(jvm['path']))

    def test_returns_none_for_unknown_domain(self):
        jvm = self._make_garden('jvm-garden', ['java'])
        result = route('python', [jvm])
        self.assertIsNone(result)

    def test_empty_garden_list_returns_none(self):
        result = route('java', [])
        self.assertIsNone(result)

    def test_returns_path_object(self):
        jvm = self._make_garden('jvm-garden', ['java'])
        result = route('java', [jvm])
        self.assertIsInstance(result, Path)

    def test_garden_without_schema_skipped(self):
        empty = {'name': 'empty', 'path': str(self.root / 'empty')}
        (self.root / 'empty').mkdir()
        jvm = self._make_garden('jvm-garden', ['java'])
        result = route('java', [empty, jvm])
        self.assertEqual(result, Path(jvm['path']))

    def test_second_garden_domain_found(self):
        jvm = self._make_garden('jvm-garden', ['java'])
        tools = self._make_garden('tools-garden', ['tools', 'cli'])
        result = route('cli', [jvm, tools])
        self.assertEqual(result, Path(tools['path']))


class TestRouteIntegration(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.jvm_dir = self.root / 'jvm-garden'
        self.tools_dir = self.root / 'tools-garden'
        write_schema(self.jvm_dir, role='canonical', ge_prefix='JE-',
                     domains=['java', 'quarkus'], name='jvm-garden')
        write_schema(self.tools_dir, role='canonical', ge_prefix='TE-',
                     domains=['tools', 'cli', 'git'], name='tools-garden')
        self.config = self.root / 'garden-config.toml'
        self.config.write_text(
            f'[[gardens]]\nname = "jvm-garden"\npath = "{self.jvm_dir}"\n\n'
            f'[[gardens]]\nname = "tools-garden"\npath = "{self.tools_dir}"\n'
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_java_routes_to_jvm_garden(self):
        result = run_cli('java', '--config', str(self.config))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(str(self.jvm_dir), result.stdout)

    def test_tools_routes_to_tools_garden(self):
        result = run_cli('tools', '--config', str(self.config))
        self.assertEqual(result.returncode, 0)
        self.assertIn(str(self.tools_dir), result.stdout)

    def test_unknown_domain_exits_1(self):
        result = run_cli('python', '--config', str(self.config))
        self.assertEqual(result.returncode, 1)
        self.assertIn('python', result.stdout + result.stderr)


class TestRouteSubmissionCLI(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.jvm_dir = self.root / 'jvm-garden'
        write_schema(self.jvm_dir, role='canonical', ge_prefix='JE-',
                     domains=['java', 'quarkus'], name='jvm-garden')
        self.config = self.root / 'garden-config.toml'
        self.config.write_text(
            f'[[gardens]]\nname = "jvm-garden"\npath = "{self.jvm_dir}"\n'
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_found_exits_0_and_prints_path(self):
        result = run_cli('java', '--config', str(self.config))
        self.assertEqual(result.returncode, 0)
        self.assertIn(str(self.jvm_dir), result.stdout)

    def test_not_found_exits_1_and_prints_error(self):
        result = run_cli('python', '--config', str(self.config))
        self.assertEqual(result.returncode, 1)
        output = result.stdout + result.stderr
        self.assertTrue(
            any(term in output for term in ('No garden', 'not found', 'python')),
            f"Expected error about domain not found, got: {output}"
        )

    def test_missing_config_exits_1(self):
        result = run_cli('java', '--config', '/nonexistent.toml')
        self.assertEqual(result.returncode, 1)

    def test_missing_domain_arg_exits_nonzero(self):
        result = run_cli('--config', str(self.config))
        self.assertNotEqual(result.returncode, 0)

    def test_output_is_absolute_path(self):
        result = run_cli('java', '--config', str(self.config))
        self.assertEqual(result.returncode, 0)
        output = result.stdout.strip()
        self.assertTrue(Path(output).is_absolute(), f"Expected absolute path, got: {output}")


if __name__ == '__main__':
    unittest.main(verbosity=2)
