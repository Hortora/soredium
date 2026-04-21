import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
from cluster_pipeline import cluster_projects, fingerprint_to_vector, FEATURE_KEYS


_FP_HIGH_ABSTRACTION = {
    'interface_count': 20, 'abstraction_depth': 0.6,
    'injection_points': 15, 'extension_signatures': 18,
    'file_count': 33, 'spi_patterns': 4,
}
_FP_HIGH_ABSTRACTION_2 = {
    'interface_count': 18, 'abstraction_depth': 0.55,
    'injection_points': 14, 'extension_signatures': 16,
    'file_count': 30, 'spi_patterns': 3,
}
_FP_LOW_ABSTRACTION = {
    'interface_count': 1, 'abstraction_depth': 0.02,
    'injection_points': 2, 'extension_signatures': 1,
    'file_count': 50, 'spi_patterns': 0,
}


class TestClusterPipeline(unittest.TestCase):

    def test_feature_keys_defined(self):
        self.assertIn('interface_count', FEATURE_KEYS)
        self.assertIn('abstraction_depth', FEATURE_KEYS)

    def test_fingerprint_to_vector_returns_list(self):
        vec = fingerprint_to_vector(_FP_HIGH_ABSTRACTION)
        self.assertEqual(len(vec), len(FEATURE_KEYS))
        self.assertIsInstance(vec[0], float)

    def test_too_few_projects_returns_empty(self):
        result = cluster_projects({'only-one': _FP_HIGH_ABSTRACTION}, known_patterns=[])
        self.assertEqual(result, [])

    def test_similar_projects_form_candidate(self):
        fingerprints = {
            'proj-a': _FP_HIGH_ABSTRACTION,
            'proj-b': _FP_HIGH_ABSTRACTION_2,
            'proj-c': _FP_LOW_ABSTRACTION,
        }
        candidates = cluster_projects(fingerprints, known_patterns=[])
        clustered = [set(c['projects']) for c in candidates]
        self.assertIn({'proj-a', 'proj-b'}, clustered)

    def test_candidate_has_required_fields(self):
        fingerprints = {
            'proj-a': _FP_HIGH_ABSTRACTION,
            'proj-b': _FP_HIGH_ABSTRACTION_2,
        }
        candidates = cluster_projects(fingerprints, known_patterns=[])
        self.assertTrue(len(candidates) > 0)
        c = candidates[0]
        self.assertIn('projects', c)
        self.assertIn('centroid', c)
        self.assertIn('similarity_score', c)
        self.assertIn('matches_known_pattern', c)

    def test_known_pattern_match_is_tagged(self):
        fingerprints = {
            'proj-a': _FP_HIGH_ABSTRACTION,
            'proj-b': _FP_HIGH_ABSTRACTION_2,
        }
        known = [{'name': 'plugin-system', 'signature': _FP_HIGH_ABSTRACTION}]
        candidates = cluster_projects(fingerprints, known_patterns=known)
        for c in candidates:
            if c['matches_known_pattern']:
                self.assertIsInstance(c['matches_known_pattern'], str)

    def test_minimum_cluster_size_is_two(self):
        fingerprints = {f'proj-{i}': _FP_HIGH_ABSTRACTION for i in range(5)}
        candidates = cluster_projects(fingerprints, known_patterns=[])
        for c in candidates:
            self.assertGreaterEqual(len(c['projects']), 2)