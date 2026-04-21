import unittest
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
from rejection_registry import RejectionRegistry


_CENTROID_A = {'interface_count': 20.0, 'abstraction_depth': 0.6,
               'injection_points': 15.0, 'extension_signatures': 18.0,
               'file_count': 33.0, 'spi_patterns': 4.0}
_CENTROID_B = {'interface_count': 1.0, 'abstraction_depth': 0.02,
               'injection_points': 2.0, 'extension_signatures': 1.0,
               'file_count': 50.0, 'spi_patterns': 0.0}


class TestRejectionRegistryUnit(unittest.TestCase):
    """Unit tests — RejectionRegistry in isolation."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'rejections.yaml'
        self.path.write_text('rejections: []\n')
        self.reg = RejectionRegistry(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_empty_registry_has_no_rejections(self):
        self.assertEqual(self.reg.list(), [])

    def test_add_rejection_persists(self):
        self.reg.add(_CENTROID_A, ['proj-a', 'proj-b'], 'test doubles')
        records = self.reg.list()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['projects'], ['proj-a', 'proj-b'])
        self.assertEqual(records[0]['reason'], 'test doubles')

    def test_add_rejection_stores_centroid(self):
        self.reg.add(_CENTROID_A, ['proj-a'], 'noise')
        self.assertEqual(self.reg.list()[0]['centroid'], _CENTROID_A)

    def test_add_rejection_records_date(self):
        self.reg.add(_CENTROID_A, ['proj-a'], 'noise')
        self.assertIn('rejected_at', self.reg.list()[0])

    def test_data_persists_across_instances(self):
        self.reg.add(_CENTROID_A, ['proj-a'], 'noise')
        reload = RejectionRegistry(self.path)
        self.assertEqual(len(reload.list()), 1)


class TestRejectionRegistryCorrectness(unittest.TestCase):
    """Correctness tests — rejection suppression behaviour."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'rejections.yaml'
        self.path.write_text('rejections: []\n')
        self.reg = RejectionRegistry(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_is_rejected_returns_false_for_unknown_centroid(self):
        self.assertFalse(self.reg.is_rejected(_CENTROID_A))

    def test_is_rejected_returns_true_after_add(self):
        self.reg.add(_CENTROID_A, ['proj-a'], 'noise')
        self.assertTrue(self.reg.is_rejected(_CENTROID_A))

    def test_is_rejected_uses_similarity_not_exact_match(self):
        self.reg.add(_CENTROID_A, ['proj-a'], 'noise')
        near = dict(_CENTROID_A)
        near['interface_count'] = 20.1
        self.assertTrue(self.reg.is_rejected(near))

    def test_dissimilar_centroid_not_rejected(self):
        self.reg.add(_CENTROID_A, ['proj-a'], 'noise')
        self.assertFalse(self.reg.is_rejected(_CENTROID_B))

    def test_multiple_rejections_all_checked(self):
        self.reg.add(_CENTROID_A, ['proj-a'], 'noise')
        self.reg.add(_CENTROID_B, ['proj-c'], 'noise2')
        self.assertTrue(self.reg.is_rejected(_CENTROID_A))
        self.assertTrue(self.reg.is_rejected(_CENTROID_B))
