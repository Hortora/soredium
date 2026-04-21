import unittest
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
from project_registry import ProjectRegistry


class TestProjectRegistry(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'projects.yaml'
        self.path.write_text('projects: []\n')
        self.registry = ProjectRegistry(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_empty_registry_lists_nothing(self):
        self.assertEqual(self.registry.list(), [])

    def test_add_project_persists(self):
        self.registry.add({
            'project': 'serverless-workflow',
            'url': 'https://github.com/serverlessworkflow/specification',
            'domain': 'jvm',
            'primary_language': 'java',
            'frameworks': ['quarkus'],
            'last_processed_commit': None,
            'notable_contributors': [],
        })
        projects = self.registry.list()
        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0]['project'], 'serverless-workflow')

    def test_add_duplicate_raises(self):
        entry = {'project': 'foo', 'url': 'https://github.com/foo/foo',
                 'domain': 'jvm', 'primary_language': 'java',
                 'frameworks': [], 'last_processed_commit': None,
                 'notable_contributors': []}
        self.registry.add(entry)
        with self.assertRaises(ValueError):
            self.registry.add(entry)

    def test_update_last_processed_commit(self):
        self.registry.add({'project': 'foo', 'url': 'https://github.com/foo/foo',
                           'domain': 'jvm', 'primary_language': 'java',
                           'frameworks': [], 'last_processed_commit': None,
                           'notable_contributors': []})
        self.registry.update_commit('foo', 'abc1234')
        project = self.registry.get('foo')
        self.assertEqual(project['last_processed_commit'], 'abc1234')

    def test_get_unknown_project_returns_none(self):
        self.assertIsNone(self.registry.get('does-not-exist'))

    def test_required_fields_validated_on_add(self):
        with self.assertRaises(ValueError):
            self.registry.add({'project': 'missing-fields'})

    def test_data_persists_across_instances(self):
        self.registry.add({'project': 'foo', 'url': 'https://github.com/foo/foo',
                           'domain': 'jvm', 'primary_language': 'java',
                           'frameworks': [], 'last_processed_commit': None,
                           'notable_contributors': []})
        reload = ProjectRegistry(self.path)
        self.assertEqual(len(reload.list()), 1)