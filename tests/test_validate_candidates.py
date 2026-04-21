import unittest
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
from candidate_report import CandidateReport
from validate_candidates import validate_candidates, Decision, SessionSummary


_CLUSTER_A = {
    'projects': ['proj-a', 'proj-b'],
    'centroid': {'interface_count': 20.0, 'abstraction_depth': 0.6,
                 'injection_points': 15.0, 'extension_signatures': 18.0,
                 'file_count': 33.0, 'spi_patterns': 4.0},
    'similarity_score': 0.97,
    'matches_known_pattern': None,
}
_CLUSTER_B = {
    'projects': ['proj-c', 'proj-d'],
    'centroid': {'interface_count': 5.0, 'abstraction_depth': 0.1,
                 'injection_points': 3.0, 'extension_signatures': 2.0,
                 'file_count': 50.0, 'spi_patterns': 0.0},
    'similarity_score': 0.91,
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


class TestDecisionEnum(unittest.TestCase):
    """Unit tests — Decision values."""

    def test_decision_values_defined(self):
        self.assertEqual(Decision.ACCEPT, 'accept')
        self.assertEqual(Decision.REJECT, 'reject')
        self.assertEqual(Decision.SKIP, 'skip')


class TestSessionSummaryUnit(unittest.TestCase):
    """Unit tests — SessionSummary construction."""

    def test_summary_tracks_counts(self):
        s = SessionSummary(accepted=2, rejected=1, skipped=3)
        self.assertEqual(s.accepted, 2)
        self.assertEqual(s.rejected, 1)
        self.assertEqual(s.skipped, 3)

    def test_summary_total(self):
        s = SessionSummary(accepted=2, rejected=1, skipped=3)
        self.assertEqual(s.total(), 6)


class TestValidateCandidatesCorrectness(unittest.TestCase):
    """Correctness tests — accept/reject/skip state transitions."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.out_dir = Path(self.tmp.name) / 'patterns'
        self.rejections_path = Path(self.tmp.name) / 'rejections.yaml'
        self.rejections_path.write_text('rejections: []\n')
        self.report = CandidateReport(
            cluster_candidates=[_CLUSTER_A, _CLUSTER_B],
            delta_candidates=[],
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_accept_creates_skeleton_file(self):
        decisions = iter([
            (Decision.ACCEPT, None),
            (Decision.REJECT, 'noise'),
        ])
        validate_candidates(
            self.report, _REGISTRY_PROJECTS,
            self.rejections_path, self.out_dir,
            decide_fn=lambda c: next(decisions),
        )
        files = list(self.out_dir.glob('GP-*.md'))
        self.assertEqual(len(files), 1)

    def test_reject_records_in_rejection_registry(self):
        validate_candidates(
            self.report, _REGISTRY_PROJECTS,
            self.rejections_path, self.out_dir,
            decide_fn=lambda c: (Decision.REJECT, 'test doubles'),
        )
        import yaml as _yaml
        data = _yaml.safe_load(self.rejections_path.read_text())
        self.assertEqual(len(data['rejections']), 2)

    def test_skip_creates_no_files_and_no_rejections(self):
        validate_candidates(
            self.report, _REGISTRY_PROJECTS,
            self.rejections_path, self.out_dir,
            decide_fn=lambda c: (Decision.SKIP, None),
        )
        self.assertEqual(list(self.out_dir.glob('GP-*.md')), [])
        import yaml as _yaml
        data = _yaml.safe_load(self.rejections_path.read_text())
        self.assertEqual(len(data['rejections']), 0)

    def test_summary_reflects_decisions(self):
        decisions = iter([
            (Decision.ACCEPT, None),
            (Decision.REJECT, 'noise'),
        ])
        summary = validate_candidates(
            self.report, _REGISTRY_PROJECTS,
            self.rejections_path, self.out_dir,
            decide_fn=lambda c: next(decisions),
        )
        self.assertEqual(summary.accepted, 1)
        self.assertEqual(summary.rejected, 1)
        self.assertEqual(summary.skipped, 0)

    def test_reject_stores_reason_in_registry(self):
        validate_candidates(
            self.report, _REGISTRY_PROJECTS,
            self.rejections_path, self.out_dir,
            decide_fn=lambda c: (Decision.REJECT, 'my reason'),
        )
        import yaml as _yaml
        data = _yaml.safe_load(self.rejections_path.read_text())
        self.assertEqual(data['rejections'][0]['reason'], 'my reason')

    def test_already_rejected_candidate_is_skipped_automatically(self):
        from rejection_registry import RejectionRegistry
        reg = RejectionRegistry(self.rejections_path)
        reg.add(_CLUSTER_A['centroid'], _CLUSTER_A['projects'], 'pre-existing')

        called_with = []
        def decide(c):
            called_with.append(c)
            return (Decision.ACCEPT, None)

        validate_candidates(
            self.report, _REGISTRY_PROJECTS,
            self.rejections_path, self.out_dir,
            decide_fn=decide,
        )
        self.assertEqual(len(called_with), 1)
        self.assertEqual(called_with[0]['projects'], ['proj-c', 'proj-d'])


class TestValidateCandidatesIntegration(unittest.TestCase):
    """Integration tests — validate_candidates using real rejection_registry + pattern_entry."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.out_dir = Path(self.tmp.name) / 'patterns'
        self.rejections_path = Path(self.tmp.name) / 'rejections.yaml'
        self.rejections_path.write_text('rejections: []\n')

    def tearDown(self):
        self.tmp.cleanup()

    def test_accepted_entry_is_valid_yaml(self):
        report = CandidateReport(cluster_candidates=[_CLUSTER_A], delta_candidates=[])
        validate_candidates(
            report, _REGISTRY_PROJECTS,
            self.rejections_path, self.out_dir,
            decide_fn=lambda c: (Decision.ACCEPT, None),
        )
        files = list(self.out_dir.glob('GP-*.md'))
        self.assertEqual(len(files), 1)
        content = files[0].read_text()
        parts = content.split('---\n', 2)
        frontmatter = yaml.safe_load(parts[1])
        self.assertEqual(frontmatter['garden'], 'patterns')

    def test_accept_then_reject_correct_state(self):
        report = CandidateReport(
            cluster_candidates=[_CLUSTER_A, _CLUSTER_B],
            delta_candidates=[],
        )
        decisions = iter([(Decision.ACCEPT, None), (Decision.REJECT, 'low signal')])
        summary = validate_candidates(
            report, _REGISTRY_PROJECTS,
            self.rejections_path, self.out_dir,
            decide_fn=lambda c: next(decisions),
        )
        self.assertEqual(len(list(self.out_dir.glob('GP-*.md'))), 1)
        data = yaml.safe_load(self.rejections_path.read_text())
        self.assertEqual(len(data['rejections']), 1)
        self.assertEqual(summary.total(), 2)
