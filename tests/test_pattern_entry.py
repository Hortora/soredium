import unittest
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
from pattern_entry import generate_skeleton, write_skeleton, SKELETON_SECTIONS


_CLUSTER = {
    'projects': ['proj-a', 'proj-b'],
    'centroid': {'interface_count': 11.5, 'abstraction_depth': 0.3,
                 'injection_points': 7.0, 'extension_signatures': 8.0,
                 'file_count': 31.5, 'spi_patterns': 1.5},
    'similarity_score': 0.97,
    'matches_known_pattern': None,
}
_REGISTRY_PROJECTS = [
    {'project': 'proj-a', 'url': 'https://github.com/org/proj-a',
     'domain': 'jvm', 'primary_language': 'java',
     'frameworks': [], 'last_processed_commit': None, 'notable_contributors': []},
    {'project': 'proj-b', 'url': 'https://github.com/org/proj-b',
     'domain': 'jvm', 'primary_language': 'java',
     'frameworks': [], 'last_processed_commit': None, 'notable_contributors': []},
]


class TestPatternEntryUnit(unittest.TestCase):
    """Unit tests — generate_skeleton in isolation."""

    def test_returns_string(self):
        skeleton = generate_skeleton(_CLUSTER, _REGISTRY_PROJECTS)
        self.assertIsInstance(skeleton, str)

    def test_contains_yaml_frontmatter_delimiters(self):
        skeleton = generate_skeleton(_CLUSTER, _REGISTRY_PROJECTS)
        self.assertTrue(skeleton.startswith('---\n'))
        self.assertIn('\n---\n', skeleton)

    def test_id_has_gp_prefix(self):
        skeleton = generate_skeleton(_CLUSTER, _REGISTRY_PROJECTS)
        frontmatter = yaml.safe_load(skeleton.split('---\n')[1])
        self.assertTrue(frontmatter['id'].startswith('GP-'))

    def test_garden_is_patterns(self):
        skeleton = generate_skeleton(_CLUSTER, _REGISTRY_PROJECTS)
        frontmatter = yaml.safe_load(skeleton.split('---\n')[1])
        self.assertEqual(frontmatter['garden'], 'patterns')

    def test_observed_in_contains_cluster_projects(self):
        skeleton = generate_skeleton(_CLUSTER, _REGISTRY_PROJECTS)
        frontmatter = yaml.safe_load(skeleton.split('---\n')[1])
        observed_projects = [o['project'] for o in frontmatter['observed_in']]
        self.assertIn('proj-a', observed_projects)
        self.assertIn('proj-b', observed_projects)

    def test_observed_in_includes_url_from_registry(self):
        skeleton = generate_skeleton(_CLUSTER, _REGISTRY_PROJECTS)
        frontmatter = yaml.safe_load(skeleton.split('---\n')[1])
        proj_a = next(o for o in frontmatter['observed_in'] if o['project'] == 'proj-a')
        self.assertEqual(proj_a['url'], 'https://github.com/org/proj-a')

    def test_skeleton_sections_defined(self):
        self.assertIn('Pattern description', SKELETON_SECTIONS)
        self.assertIn('When to use', SKELETON_SECTIONS)
        self.assertIn('When not to use', SKELETON_SECTIONS)
        self.assertIn('Variants', SKELETON_SECTIONS)

    def test_body_contains_all_sections(self):
        skeleton = generate_skeleton(_CLUSTER, _REGISTRY_PROJECTS)
        for section in SKELETON_SECTIONS:
            self.assertIn(f'### {section}', skeleton)


class TestPatternEntryCorrectness(unittest.TestCase):
    """Correctness tests — file writing and YAML validity."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.out_dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_write_creates_file(self):
        path = write_skeleton(_CLUSTER, _REGISTRY_PROJECTS, self.out_dir)
        self.assertTrue(path.exists())

    def test_written_file_is_valid_yaml_frontmatter(self):
        path = write_skeleton(_CLUSTER, _REGISTRY_PROJECTS, self.out_dir)
        content = path.read_text()
        parts = content.split('---\n', 2)
        self.assertEqual(len(parts), 3)
        frontmatter = yaml.safe_load(parts[1])
        self.assertIsInstance(frontmatter, dict)

    def test_filename_uses_gp_id(self):
        path = write_skeleton(_CLUSTER, _REGISTRY_PROJECTS, self.out_dir)
        self.assertTrue(path.name.startswith('GP-'))
        self.assertTrue(path.name.endswith('.md'))

    def test_project_not_in_registry_gets_empty_url(self):
        cluster = dict(_CLUSTER)
        cluster['projects'] = ['proj-a', 'unknown-proj']
        skeleton = generate_skeleton(cluster, _REGISTRY_PROJECTS)
        frontmatter = yaml.safe_load(skeleton.split('---\n')[1])
        unknown = next(o for o in frontmatter['observed_in'] if o['project'] == 'unknown-proj')
        self.assertEqual(unknown['url'], '')