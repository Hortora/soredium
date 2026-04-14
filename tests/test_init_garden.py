#!/usr/bin/env python3
"""Unit, integration, and CLI tests for init_garden.py."""

import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
from init_garden import (
    create_garden_md, create_schema_md, create_checked_md,
    create_discarded_md, create_domain, create_ci_workflow, init_garden,
)
from validate_schema import parse_schema, validate_schema

INIT = Path(__file__).parent.parent / 'scripts' / 'init_garden.py'
SCHEMA_V = Path(__file__).parent.parent / 'scripts' / 'validate_schema.py'


def run_init(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(INIT)] + list(args),
        capture_output=True, text=True
    )


def run_schema_validator(garden: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCHEMA_V), str(garden)],
        capture_output=True, text=True
    )


class TestCreateGardenMd(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_creates_file(self):
        create_garden_md(self.root, name='jvm-garden', ge_prefix='JE-')
        self.assertTrue((self.root / 'GARDEN.md').exists())

    def test_contains_last_assigned_id(self):
        create_garden_md(self.root, name='jvm-garden', ge_prefix='JE-')
        content = (self.root / 'GARDEN.md').read_text()
        self.assertIn('Last assigned ID', content)

    def test_contains_dedupe_sweep_field(self):
        create_garden_md(self.root, name='jvm-garden', ge_prefix='JE-')
        content = (self.root / 'GARDEN.md').read_text()
        self.assertIn('Last full DEDUPE sweep', content)

    def test_drift_counter_starts_at_zero(self):
        create_garden_md(self.root, name='jvm-garden', ge_prefix='JE-')
        content = (self.root / 'GARDEN.md').read_text()
        self.assertIn('Entries merged since last sweep: 0', content)

    def test_contains_drift_threshold(self):
        create_garden_md(self.root, name='jvm-garden', ge_prefix='JE-')
        content = (self.root / 'GARDEN.md').read_text()
        self.assertIn('Drift threshold', content)

    def test_contains_by_technology_section(self):
        create_garden_md(self.root, name='jvm-garden', ge_prefix='JE-')
        content = (self.root / 'GARDEN.md').read_text()
        self.assertIn('## By Technology', content)

    def test_contains_by_symptom_section(self):
        create_garden_md(self.root, name='jvm-garden', ge_prefix='JE-')
        content = (self.root / 'GARDEN.md').read_text()
        self.assertIn('## By Symptom', content)

    def test_contains_by_label_section(self):
        create_garden_md(self.root, name='jvm-garden', ge_prefix='JE-')
        content = (self.root / 'GARDEN.md').read_text()
        self.assertIn('## By Label', content)

    def test_idempotent_does_not_overwrite(self):
        create_garden_md(self.root, name='jvm-garden', ge_prefix='JE-')
        p = self.root / 'GARDEN.md'
        p.write_text(p.read_text() + '\n<!-- sentinel -->\n')
        create_garden_md(self.root, name='jvm-garden', ge_prefix='JE-')
        self.assertIn('sentinel', p.read_text())


class TestCreateSchemaMd(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_creates_file(self):
        create_schema_md(self.root, name='jvm-garden', description='JVM garden',
                         role='canonical', ge_prefix='JE-', domains=['java', 'quarkus'])
        self.assertTrue((self.root / 'SCHEMA.md').exists())

    def test_created_schema_validates(self):
        create_schema_md(self.root, name='jvm-garden', description='JVM garden',
                         role='canonical', ge_prefix='JE-', domains=['java', 'quarkus'])
        content = (self.root / 'SCHEMA.md').read_text()
        schema = parse_schema(content)
        errors, _ = validate_schema(schema)
        self.assertEqual(errors, [], f"Created SCHEMA.md has errors: {errors}")

    def test_canonical_has_no_upstream(self):
        create_schema_md(self.root, name='jvm-garden', description='JVM garden',
                         role='canonical', ge_prefix='JE-', domains=['java'])
        content = (self.root / 'SCHEMA.md').read_text()
        self.assertNotIn('upstream', content)

    def test_child_includes_upstream(self):
        create_schema_md(self.root, name='my-garden', description='Private',
                         role='child', ge_prefix='ME-', domains=['java'],
                         upstream=['https://github.com/Hortora/jvm-garden'])
        content = (self.root / 'SCHEMA.md').read_text()
        self.assertIn('upstream', content)
        self.assertIn('https://github.com/Hortora/jvm-garden', content)
        schema = parse_schema(content)
        errors, _ = validate_schema(schema)
        self.assertEqual(errors, [])

    def test_domains_appear_in_schema(self):
        create_schema_md(self.root, name='jvm-garden', description='JVM',
                         role='canonical', ge_prefix='JE-',
                         domains=['java', 'quarkus', 'spring'])
        schema = parse_schema((self.root / 'SCHEMA.md').read_text())
        self.assertEqual(sorted(schema['domains']), ['java', 'quarkus', 'spring'])

    def test_idempotent_does_not_overwrite(self):
        create_schema_md(self.root, name='jvm-garden', description='JVM garden',
                         role='canonical', ge_prefix='JE-', domains=['java'])
        p = self.root / 'SCHEMA.md'
        p.write_text(p.read_text() + '\n# sentinel\n')
        create_schema_md(self.root, name='jvm-garden', description='JVM garden',
                         role='canonical', ge_prefix='JE-', domains=['java'])
        self.assertIn('sentinel', p.read_text())


class TestCreateCheckedMd(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_creates_file(self):
        create_checked_md(self.root)
        self.assertTrue((self.root / 'CHECKED.md').exists())

    def test_has_table_header(self):
        create_checked_md(self.root)
        content = (self.root / 'CHECKED.md').read_text()
        self.assertIn('| Pair |', content)
        self.assertIn('| Result |', content)

    def test_no_data_rows(self):
        create_checked_md(self.root)
        content = (self.root / 'CHECKED.md').read_text()
        data_rows = [
            l for l in content.splitlines()
            if l.startswith('|') and '---' not in l and 'Pair' not in l
        ]
        self.assertEqual(data_rows, [])


class TestCreateDiscardedMd(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_creates_file(self):
        create_discarded_md(self.root)
        self.assertTrue((self.root / 'DISCARDED.md').exists())

    def test_has_table_header(self):
        create_discarded_md(self.root)
        content = (self.root / 'DISCARDED.md').read_text()
        self.assertIn('| Discarded |', content)
        self.assertIn('| Conflicts With |', content)


class TestCreateDomain(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_creates_directory(self):
        create_domain(self.root, 'java')
        self.assertTrue((self.root / 'java').is_dir())

    def test_creates_index_md(self):
        create_domain(self.root, 'java')
        self.assertTrue((self.root / 'java' / 'INDEX.md').exists())

    def test_index_md_has_table_header(self):
        create_domain(self.root, 'java')
        content = (self.root / 'java' / 'INDEX.md').read_text()
        self.assertIn('| GE-ID |', content)
        self.assertIn('| Title |', content)

    def test_multiple_domains_independent(self):
        create_domain(self.root, 'java')
        create_domain(self.root, 'quarkus')
        self.assertTrue((self.root / 'java' / 'INDEX.md').exists())
        self.assertTrue((self.root / 'quarkus' / 'INDEX.md').exists())

    def test_idempotent(self):
        create_domain(self.root, 'java')
        idx = self.root / 'java' / 'INDEX.md'
        idx.write_text(idx.read_text() + '\n<!-- sentinel -->\n')
        create_domain(self.root, 'java')
        self.assertIn('sentinel', idx.read_text())


class TestCreateCiWorkflow(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_creates_workflow_file(self):
        create_ci_workflow(self.root)
        self.assertTrue((self.root / '.github' / 'workflows' / 'validate_pr.yml').exists())

    def test_workflow_references_validate_pr(self):
        create_ci_workflow(self.root)
        content = (self.root / '.github' / 'workflows' / 'validate_pr.yml').read_text()
        self.assertIn('validate_pr.py', content)

    def test_workflow_triggers_on_pull_request(self):
        create_ci_workflow(self.root)
        content = (self.root / '.github' / 'workflows' / 'validate_pr.yml').read_text()
        self.assertIn('pull_request', content)

    def test_workflow_has_required_yaml_keys(self):
        create_ci_workflow(self.root)
        content = (self.root / '.github' / 'workflows' / 'validate_pr.yml').read_text()
        self.assertIn('on:', content)
        self.assertIn('jobs:', content)


class TestInitGarden(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_creates_all_required_files(self):
        init_garden(self.root, name='jvm-garden', description='JVM garden',
                    role='canonical', ge_prefix='JE-', domains=['java', 'quarkus'])
        self.assertTrue((self.root / 'GARDEN.md').exists())
        self.assertTrue((self.root / 'SCHEMA.md').exists())
        self.assertTrue((self.root / 'CHECKED.md').exists())
        self.assertTrue((self.root / 'DISCARDED.md').exists())
        self.assertTrue((self.root / '.github' / 'workflows' / 'validate_pr.yml').exists())

    def test_creates_all_domain_directories(self):
        init_garden(self.root, name='jvm-garden', description='JVM garden',
                    role='canonical', ge_prefix='JE-', domains=['java', 'quarkus', 'spring'])
        for domain in ['java', 'quarkus', 'spring']:
            self.assertTrue((self.root / domain / 'INDEX.md').exists(),
                            f"Missing {domain}/INDEX.md")

    def test_idempotent_preserves_existing_entries(self):
        init_garden(self.root, name='jvm-garden', description='JVM garden',
                    role='canonical', ge_prefix='JE-', domains=['java'])
        (self.root / 'java' / 'GE-0001.md').write_text('# Custom entry\n')
        init_garden(self.root, name='jvm-garden', description='JVM garden',
                    role='canonical', ge_prefix='JE-', domains=['java'])
        self.assertTrue((self.root / 'java' / 'GE-0001.md').exists())

    def test_created_schema_passes_validate_schema(self):
        init_garden(self.root, name='jvm-garden', description='JVM garden',
                    role='canonical', ge_prefix='JE-', domains=['java', 'quarkus'])
        result = run_schema_validator(self.root)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_child_garden_includes_upstream(self):
        init_garden(self.root, name='my-garden', description='Private',
                    role='child', ge_prefix='ME-', domains=['java'],
                    upstream=['https://github.com/Hortora/jvm-garden'])
        content = (self.root / 'SCHEMA.md').read_text()
        self.assertIn('https://github.com/Hortora/jvm-garden', content)
        result = run_schema_validator(self.root)
        self.assertEqual(result.returncode, 0)

    def test_returns_list_of_created_paths(self):
        created = init_garden(self.root, name='jvm-garden', description='JVM',
                              role='canonical', ge_prefix='JE-', domains=['java'])
        self.assertIsInstance(created, list)
        self.assertGreater(len(created), 0)
        self.assertTrue(any('GARDEN.md' in p for p in created))
        self.assertTrue(any('SCHEMA.md' in p for p in created))

    def test_child_garden_creates_augment_dir(self):
        init_garden(self.root, name='my-garden', description='Private',
                    role='child', ge_prefix='ME-', domains=['java'],
                    upstream=['https://github.com/Hortora/jvm-garden'])
        self.assertTrue((self.root / '_augment').is_dir(),
                        "Child garden should have _augment/ directory")

    def test_canonical_garden_no_augment_dir(self):
        init_garden(self.root, name='jvm-garden', description='JVM',
                    role='canonical', ge_prefix='JE-', domains=['java'])
        self.assertFalse((self.root / '_augment').exists(),
                         "Canonical garden should NOT have _augment/")

    def test_peer_garden_no_augment_dir(self):
        init_garden(self.root, name='tools-garden', description='Tools',
                    role='peer', ge_prefix='TE-', domains=['tools'])
        self.assertFalse((self.root / '_augment').exists(),
                         "Peer garden should NOT have _augment/")

    def test_augment_dir_has_readme(self):
        init_garden(self.root, name='my-garden', description='Private',
                    role='child', ge_prefix='ME-', domains=['java'],
                    upstream=['https://github.com/Hortora/jvm-garden'])
        readme = self.root / '_augment' / 'README.md'
        self.assertTrue(readme.exists(), "_augment/ should have README.md")
        self.assertIn('augment', readme.read_text().lower())


class TestInitGardenCLI(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'new-garden'

    def tearDown(self):
        self.tmp.cleanup()

    def test_basic_canonical_garden(self):
        result = run_init(
            str(self.root),
            '--name', 'jvm-garden',
            '--description', 'JVM garden',
            '--role', 'canonical',
            '--ge-prefix', 'JE-',
            '--domains', 'java', 'quarkus',
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.root / 'GARDEN.md').exists())
        self.assertTrue((self.root / 'SCHEMA.md').exists())

    def test_child_garden_with_upstream(self):
        result = run_init(
            str(self.root),
            '--name', 'my-garden',
            '--description', 'Private garden',
            '--role', 'child',
            '--ge-prefix', 'ME-',
            '--domains', 'java',
            '--upstream', 'https://github.com/Hortora/jvm-garden',
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        content = (self.root / 'SCHEMA.md').read_text()
        self.assertIn('https://github.com/Hortora/jvm-garden', content)

    def test_missing_required_arg_exits_nonzero(self):
        result = run_init(str(self.root), '--role', 'canonical')
        self.assertNotEqual(result.returncode, 0)

    def test_output_confirms_created_files(self):
        result = run_init(
            str(self.root),
            '--name', 'test-garden',
            '--description', 'Test',
            '--role', 'canonical',
            '--ge-prefix', 'TE-',
            '--domains', 'tools',
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('GARDEN.md', result.stdout)
        self.assertIn('SCHEMA.md', result.stdout)

    def test_child_role_creates_augment_dir(self):
        result = run_init(
            str(self.root),
            '--name', 'my-garden',
            '--description', 'Private garden',
            '--role', 'child',
            '--ge-prefix', 'ME-',
            '--domains', 'java',
            '--upstream', 'https://github.com/Hortora/jvm-garden',
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.root / '_augment').is_dir())

    def test_second_run_reports_nothing_created(self):
        args = [
            str(self.root), '--name', 'test-garden', '--description', 'Test',
            '--role', 'canonical', '--ge-prefix', 'TE-', '--domains', 'tools',
        ]
        run_init(*args)
        result = run_init(*args)
        self.assertEqual(result.returncode, 0)
        self.assertIn('nothing created', result.stdout.lower())


if __name__ == '__main__':
    unittest.main(verbosity=2)
