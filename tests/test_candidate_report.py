import json
import unittest
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
from candidate_report import CandidateReport, load_report, save_report


_CLUSTER = {
    'projects': ['proj-a', 'proj-b'],
    'centroid': {'interface_count': 11.5, 'abstraction_depth': 0.3,
                 'injection_points': 7.0, 'extension_signatures': 8.0,
                 'file_count': 31.5, 'spi_patterns': 1.5},
    'similarity_score': 0.97,
    'matches_known_pattern': None,
}
_DELTA = {
    'file': 'src/Evaluator.java',
    'kind': 'interface',
    'introduced_at': 'v2.0',
    'commit': 'abc1234',
    'author': 'dev@example.com',
    'date': '2026-04-21',
}


class TestCandidateReportUnit(unittest.TestCase):
    """Unit tests — CandidateReport construction."""

    def test_empty_report_has_no_candidates(self):
        report = CandidateReport(cluster_candidates=[], delta_candidates=[])
        self.assertEqual(report.cluster_candidates, [])
        self.assertEqual(report.delta_candidates, [])

    def test_report_stores_candidates(self):
        report = CandidateReport(cluster_candidates=[_CLUSTER], delta_candidates=[_DELTA])
        self.assertEqual(len(report.cluster_candidates), 1)
        self.assertEqual(len(report.delta_candidates), 1)

    def test_report_has_generated_at_timestamp(self):
        report = CandidateReport(cluster_candidates=[], delta_candidates=[])
        self.assertIsInstance(report.generated_at, str)
        datetime.fromisoformat(report.generated_at)

    def test_total_count(self):
        report = CandidateReport(cluster_candidates=[_CLUSTER], delta_candidates=[_DELTA])
        self.assertEqual(report.total_count(), 2)


class TestCandidateReportCorrectness(unittest.TestCase):
    """Correctness tests — round-trip serialization."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'report.json'

    def tearDown(self):
        self.tmp.cleanup()

    def test_save_creates_valid_json(self):
        report = CandidateReport(cluster_candidates=[_CLUSTER], delta_candidates=[_DELTA])
        save_report(report, self.path)
        with open(self.path) as f:
            data = json.load(f)
        self.assertIn('generated_at', data)
        self.assertIn('cluster_candidates', data)
        self.assertIn('delta_candidates', data)

    def test_load_restores_cluster_candidates(self):
        report = CandidateReport(cluster_candidates=[_CLUSTER], delta_candidates=[])
        save_report(report, self.path)
        loaded = load_report(self.path)
        self.assertEqual(loaded.cluster_candidates[0]['projects'], ['proj-a', 'proj-b'])

    def test_load_restores_delta_candidates(self):
        report = CandidateReport(cluster_candidates=[], delta_candidates=[_DELTA])
        save_report(report, self.path)
        loaded = load_report(self.path)
        self.assertEqual(loaded.delta_candidates[0]['file'], 'src/Evaluator.java')

    def test_round_trip_preserves_all_fields(self):
        report = CandidateReport(cluster_candidates=[_CLUSTER], delta_candidates=[_DELTA])
        save_report(report, self.path)
        loaded = load_report(self.path)
        self.assertEqual(loaded.cluster_candidates, [_CLUSTER])
        self.assertEqual(loaded.delta_candidates, [_DELTA])

    def test_load_nonexistent_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_report(Path('/nonexistent/report.json'))