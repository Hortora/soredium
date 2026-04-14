#!/usr/bin/env python3
"""Unit, integration, and CLI tests for validate_schema.py."""

import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
from validate_schema import (
    parse_schema, validate_name, validate_role, validate_ge_prefix,
    validate_domains, validate_upstream, validate_schema,
)

VALIDATOR = Path(__file__).parent.parent / 'scripts' / 'validate_schema.py'


def run_validator(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATOR)] + list(args),
        capture_output=True, text=True
    )


CANONICAL_SCHEMA = """\
---
name: jvm-garden
description: "JVM ecosystem knowledge garden"
role: canonical
ge_prefix: JE-
schema_version: "1.0"
domains: [java, quarkus, spring, kotlin]
---
"""

CHILD_SCHEMA = """\
---
name: my-private-garden
description: "Private extension of jvm-garden"
role: child
ge_prefix: ME-
schema_version: "1.0"
domains: [java, quarkus]
upstream:
  - https://github.com/Hortora/jvm-garden
---
"""

PEER_SCHEMA = """\
---
name: tools-garden
description: "Cross-cutting tools knowledge"
role: peer
ge_prefix: TE-
schema_version: "1.0"
domains: [tools, cli, git]
---
"""


class TestParseSchema(unittest.TestCase):

    def test_parses_canonical_schema(self):
        result = parse_schema(CANONICAL_SCHEMA)
        self.assertEqual(result['name'], 'jvm-garden')
        self.assertEqual(result['role'], 'canonical')
        self.assertEqual(result['ge_prefix'], 'JE-')
        self.assertEqual(result['domains'], ['java', 'quarkus', 'spring', 'kotlin'])

    def test_parses_child_schema_with_upstream(self):
        result = parse_schema(CHILD_SCHEMA)
        self.assertEqual(result['role'], 'child')
        self.assertIn('upstream', result)
        self.assertEqual(result['upstream'], ['https://github.com/Hortora/jvm-garden'])

    def test_parses_peer_schema(self):
        result = parse_schema(PEER_SCHEMA)
        self.assertEqual(result['role'], 'peer')
        self.assertEqual(result['domains'], ['tools', 'cli', 'git'])

    def test_missing_frontmatter_returns_none(self):
        self.assertIsNone(parse_schema('# No frontmatter\n'))

    def test_empty_string_returns_none(self):
        self.assertIsNone(parse_schema(''))

    def test_crlf_normalised(self):
        result = parse_schema(CANONICAL_SCHEMA.replace('\n', '\r\n'))
        self.assertIsNotNone(result)
        self.assertEqual(result['name'], 'jvm-garden')

    def test_inline_domain_list(self):
        result = parse_schema('---\nname: x\ndomains: [java, quarkus]\n---\n')
        self.assertEqual(result['domains'], ['java', 'quarkus'])

    def test_block_domain_list(self):
        result = parse_schema('---\nname: x\ndomains:\n  - java\n  - quarkus\n---\n')
        self.assertEqual(result['domains'], ['java', 'quarkus'])

    def test_block_upstream_list(self):
        schema = (
            '---\nrole: child\nupstream:\n'
            '  - https://github.com/Hortora/jvm-garden\n'
            '  - https://github.com/Hortora/tools-garden\n---\n'
        )
        result = parse_schema(schema)
        self.assertEqual(result['upstream'], [
            'https://github.com/Hortora/jvm-garden',
            'https://github.com/Hortora/tools-garden',
        ])


class TestValidateName(unittest.TestCase):

    def test_valid_name(self):
        self.assertEqual(validate_name({'name': 'jvm-garden'}), [])

    def test_missing_name(self):
        errors = validate_name({})
        self.assertEqual(len(errors), 1)
        self.assertIn('name', errors[0])

    def test_empty_name(self):
        errors = validate_name({'name': ''})
        self.assertEqual(len(errors), 1)

    def test_name_with_spaces_valid(self):
        self.assertEqual(validate_name({'name': 'my garden'}), [])


class TestValidateRole(unittest.TestCase):

    def test_canonical_valid(self):
        self.assertEqual(validate_role({'role': 'canonical'}), [])

    def test_child_valid(self):
        self.assertEqual(validate_role({'role': 'child'}), [])

    def test_peer_valid(self):
        self.assertEqual(validate_role({'role': 'peer'}), [])

    def test_missing_role(self):
        errors = validate_role({})
        self.assertEqual(len(errors), 1)
        self.assertIn('role', errors[0])

    def test_invalid_role(self):
        errors = validate_role({'role': 'master'})
        self.assertEqual(len(errors), 1)
        self.assertIn('canonical', errors[0])

    def test_case_sensitive(self):
        errors = validate_role({'role': 'Canonical'})
        self.assertEqual(len(errors), 1)


class TestValidateGePrefix(unittest.TestCase):

    def test_two_letter_prefix(self):
        self.assertEqual(validate_ge_prefix({'ge_prefix': 'JE-'}), [])

    def test_one_letter_prefix(self):
        self.assertEqual(validate_ge_prefix({'ge_prefix': 'J-'}), [])

    def test_three_letter_prefix(self):
        self.assertEqual(validate_ge_prefix({'ge_prefix': 'JVM-'}), [])

    def test_missing_ge_prefix(self):
        errors = validate_ge_prefix({})
        self.assertEqual(len(errors), 1)
        self.assertIn('ge_prefix', errors[0])

    def test_lowercase_rejected(self):
        errors = validate_ge_prefix({'ge_prefix': 'je-'})
        self.assertEqual(len(errors), 1)

    def test_missing_hyphen_rejected(self):
        errors = validate_ge_prefix({'ge_prefix': 'JE'})
        self.assertEqual(len(errors), 1)

    def test_four_letters_rejected(self):
        errors = validate_ge_prefix({'ge_prefix': 'JAVA-'})
        self.assertEqual(len(errors), 1)

    def test_empty_rejected(self):
        errors = validate_ge_prefix({'ge_prefix': ''})
        self.assertEqual(len(errors), 1)


class TestValidateDomains(unittest.TestCase):

    def test_single_domain_valid(self):
        self.assertEqual(validate_domains({'domains': ['java']}), [])

    def test_multiple_domains_valid(self):
        self.assertEqual(validate_domains({'domains': ['java', 'quarkus', 'spring']}), [])

    def test_missing_domains(self):
        errors = validate_domains({})
        self.assertEqual(len(errors), 1)
        self.assertIn('domains', errors[0])

    def test_empty_list_rejected(self):
        errors = validate_domains({'domains': []})
        self.assertEqual(len(errors), 1)

    def test_non_list_rejected(self):
        errors = validate_domains({'domains': 'java'})
        self.assertEqual(len(errors), 1)


class TestValidateUpstream(unittest.TestCase):

    def test_child_with_upstream_valid(self):
        schema = {'role': 'child', 'upstream': ['https://github.com/Hortora/jvm-garden']}
        self.assertEqual(validate_upstream(schema), [])

    def test_child_without_upstream_rejected(self):
        errors = validate_upstream({'role': 'child'})
        self.assertEqual(len(errors), 1)
        self.assertIn('upstream', errors[0])

    def test_child_with_empty_upstream_rejected(self):
        errors = validate_upstream({'role': 'child', 'upstream': []})
        self.assertEqual(len(errors), 1)

    def test_canonical_with_upstream_rejected(self):
        errors = validate_upstream({'role': 'canonical', 'upstream': ['https://example.com']})
        self.assertEqual(len(errors), 1)
        self.assertIn('canonical', errors[0])

    def test_canonical_without_upstream_valid(self):
        self.assertEqual(validate_upstream({'role': 'canonical'}), [])

    def test_peer_without_upstream_valid(self):
        self.assertEqual(validate_upstream({'role': 'peer'}), [])

    def test_peer_with_upstream_rejected(self):
        errors = validate_upstream({'role': 'peer', 'upstream': ['https://example.com']})
        self.assertEqual(len(errors), 1)

    def test_upstream_items_must_be_strings(self):
        errors = validate_upstream({'role': 'child', 'upstream': [123]})
        self.assertEqual(len(errors), 1)


class TestValidateSchema(unittest.TestCase):

    def test_valid_canonical_no_errors(self):
        schema = parse_schema(CANONICAL_SCHEMA)
        errors, warnings = validate_schema(schema)
        self.assertEqual(errors, [])

    def test_valid_child_no_errors(self):
        schema = parse_schema(CHILD_SCHEMA)
        errors, warnings = validate_schema(schema)
        self.assertEqual(errors, [])

    def test_valid_peer_no_errors(self):
        schema = parse_schema(PEER_SCHEMA)
        errors, warnings = validate_schema(schema)
        self.assertEqual(errors, [])

    def test_multiple_missing_fields_all_reported(self):
        errors, warnings = validate_schema({'role': 'canonical'})
        self.assertGreaterEqual(len(errors), 3)

    def test_unknown_schema_version_warns_not_errors(self):
        schema = parse_schema(CANONICAL_SCHEMA.replace('"1.0"', '"99.0"'))
        errors, warnings = validate_schema(schema)
        self.assertEqual(errors, [])
        self.assertTrue(any('schema_version' in w for w in warnings))

    def test_empty_dict_returns_multiple_errors(self):
        errors, warnings = validate_schema({})
        self.assertGreater(len(errors), 0)


class TestSchemaIntegration(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, content: str):
        (self.root / 'SCHEMA.md').write_text(content)

    def test_canonical_garden_valid(self):
        self._write(CANONICAL_SCHEMA)
        schema = parse_schema((self.root / 'SCHEMA.md').read_text())
        errors, _ = validate_schema(schema)
        self.assertEqual(errors, [])

    def test_child_garden_valid(self):
        self._write(CHILD_SCHEMA)
        schema = parse_schema((self.root / 'SCHEMA.md').read_text())
        errors, _ = validate_schema(schema)
        self.assertEqual(errors, [])

    def test_peer_garden_valid(self):
        self._write(PEER_SCHEMA)
        schema = parse_schema((self.root / 'SCHEMA.md').read_text())
        errors, _ = validate_schema(schema)
        self.assertEqual(errors, [])

    def test_child_without_upstream_fails(self):
        content = CHILD_SCHEMA.replace(
            'upstream:\n  - https://github.com/Hortora/jvm-garden\n', ''
        )
        self._write(content)
        schema = parse_schema((self.root / 'SCHEMA.md').read_text())
        errors, _ = validate_schema(schema)
        self.assertTrue(any('upstream' in e for e in errors))

    def test_invalid_ge_prefix_fails(self):
        self._write(CANONICAL_SCHEMA.replace('ge_prefix: JE-', 'ge_prefix: java-'))
        schema = parse_schema((self.root / 'SCHEMA.md').read_text())
        errors, _ = validate_schema(schema)
        self.assertTrue(any('ge_prefix' in e for e in errors))

    def test_crlf_schema_valid(self):
        self._write(CANONICAL_SCHEMA.replace('\n', '\r\n'))
        schema = parse_schema((self.root / 'SCHEMA.md').read_text())
        errors, _ = validate_schema(schema)
        self.assertEqual(errors, [])


class TestValidateSchemaCLI(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_valid_canonical_exits_0(self):
        (self.root / 'SCHEMA.md').write_text(CANONICAL_SCHEMA)
        result = run_validator(str(self.root))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('✅', result.stdout)

    def test_valid_child_exits_0(self):
        (self.root / 'SCHEMA.md').write_text(CHILD_SCHEMA)
        result = run_validator(str(self.root))
        self.assertEqual(result.returncode, 0)

    def test_invalid_exits_1(self):
        (self.root / 'SCHEMA.md').write_text('---\nname: broken\n---\n')
        result = run_validator(str(self.root))
        self.assertEqual(result.returncode, 1)
        self.assertIn('❌', result.stdout)

    def test_missing_schema_md_exits_1(self):
        result = run_validator(str(self.root))
        self.assertEqual(result.returncode, 1)
        self.assertIn('SCHEMA.md', result.stdout + result.stderr)

    def test_output_shows_role_and_prefix_on_success(self):
        (self.root / 'SCHEMA.md').write_text(CANONICAL_SCHEMA)
        result = run_validator(str(self.root))
        self.assertIn('canonical', result.stdout)
        self.assertIn('JE-', result.stdout)

    def test_all_errors_reported(self):
        (self.root / 'SCHEMA.md').write_text('---\nrole: canonical\n---\n')
        result = run_validator(str(self.root))
        self.assertEqual(result.returncode, 1)
        self.assertGreaterEqual(result.stdout.count('ERROR'), 3)

    def test_unknown_version_warns_exits_0(self):
        (self.root / 'SCHEMA.md').write_text(
            CANONICAL_SCHEMA.replace('"1.0"', '"99.0"')
        )
        result = run_validator(str(self.root))
        self.assertEqual(result.returncode, 0)
        self.assertIn('WARNING', result.stdout)

    def test_no_frontmatter_exits_1(self):
        (self.root / 'SCHEMA.md').write_text('# No frontmatter here\n')
        result = run_validator(str(self.root))
        self.assertEqual(result.returncode, 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
