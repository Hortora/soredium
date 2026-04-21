import json
import subprocess
import unittest
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
from run_pipeline import run_pipeline, PipelineConfig
from project_registry import ProjectRegistry
from candidate_report import load_report


def _git(repo: Path, *args: str) -> None:
    subprocess.run(['git', '-C', str(repo)] + list(args), check=True, capture_output=True)


def _make_synthetic_project(root: Path, name: str, with_interface: bool = False) -> Path:
    """Create a minimal git repo with two tags to exercise delta analysis."""
    repo = root / name
    repo.mkdir()
    _git(repo, 'init')
    _git(repo, 'config', 'user.email', 'test@example.com')
    _git(repo, 'config', 'user.name', 'Test User')

    src = repo / 'src'
    src.mkdir()
    (src / 'Service.java').write_text('public class Service {}\n')
    _git(repo, 'add', '.')
    _git(repo, 'commit', '-m', 'initial')
    _git(repo, 'tag', 'v1.0')

    if with_interface:
        (src / 'Evaluator.java').write_text(
            'public interface Evaluator { void eval(); }\n'
        )
        _git(repo, 'add', '.')
        _git(repo, 'commit', '-m', 'add interface')
    _git(repo, 'tag', 'v2.0')

    return repo


class TestPipelineConfigUnit(unittest.TestCase):
    """Unit tests — PipelineConfig construction."""

    def test_pipeline_config_stores_paths(self):
        cfg = PipelineConfig(
            registry_path=Path('/tmp/projects.yaml'),
            rejections_path=Path('/tmp/rejections.yaml'),
            report_path=Path('/tmp/report.json'),
            project_roots={},
        )
        self.assertEqual(cfg.registry_path, Path('/tmp/projects.yaml'))

    def test_pipeline_config_project_roots_default_empty(self):
        cfg = PipelineConfig(
            registry_path=Path('/tmp/projects.yaml'),
            rejections_path=Path('/tmp/rejections.yaml'),
            report_path=Path('/tmp/report.json'),
        )
        self.assertEqual(cfg.project_roots, {})


class TestRunPipelineIntegration(unittest.TestCase):
    """Integration tests — pipeline stages connected."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.registry_path = self.root / 'projects.yaml'
        self.registry_path.write_text('projects: []\n')
        self.rejections_path = self.root / 'rejections.yaml'
        self.rejections_path.write_text('rejections: []\n')
        self.report_path = self.root / 'report.json'

    def tearDown(self):
        self.tmp.cleanup()

    def test_empty_registry_produces_empty_report(self):
        cfg = PipelineConfig(
            registry_path=self.registry_path,
            rejections_path=self.rejections_path,
            report_path=self.report_path,
            project_roots={},
        )
        run_pipeline(cfg)
        report = load_report(self.report_path)
        self.assertEqual(report.cluster_candidates, [])
        self.assertEqual(report.delta_candidates, [])

    def test_report_file_created(self):
        cfg = PipelineConfig(
            registry_path=self.registry_path,
            rejections_path=self.rejections_path,
            report_path=self.report_path,
            project_roots={},
        )
        run_pipeline(cfg)
        self.assertTrue(self.report_path.exists())

    def test_report_is_valid_json(self):
        cfg = PipelineConfig(
            registry_path=self.registry_path,
            rejections_path=self.rejections_path,
            report_path=self.report_path,
            project_roots={},
        )
        run_pipeline(cfg)
        data = json.loads(self.report_path.read_text())
        self.assertIn('cluster_candidates', data)
        self.assertIn('delta_candidates', data)
        self.assertIn('generated_at', data)


class TestRunPipelineE2E(unittest.TestCase):
    """E2E tests — full pipeline against synthetic project fixtures."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.proj_a = _make_synthetic_project(self.root, 'proj-a', with_interface=True)
        self.proj_b = _make_synthetic_project(self.root, 'proj-b', with_interface=True)

        self.registry_path = self.root / 'projects.yaml'
        self.registry_path.write_text('projects: []\n')
        reg = ProjectRegistry(self.registry_path)
        reg.add({'project': 'proj-a', 'url': 'https://github.com/org/proj-a',
                 'domain': 'jvm', 'primary_language': 'java',
                 'frameworks': [], 'last_processed_commit': None,
                 'notable_contributors': []})
        reg.add({'project': 'proj-b', 'url': 'https://github.com/org/proj-b',
                 'domain': 'jvm', 'primary_language': 'java',
                 'frameworks': [], 'last_processed_commit': None,
                 'notable_contributors': []})

        self.rejections_path = self.root / 'rejections.yaml'
        self.rejections_path.write_text('rejections: []\n')
        self.report_path = self.root / 'report.json'

    def tearDown(self):
        self.tmp.cleanup()

    def test_e2e_pipeline_produces_report_with_delta_candidates(self):
        cfg = PipelineConfig(
            registry_path=self.registry_path,
            rejections_path=self.rejections_path,
            report_path=self.report_path,
            project_roots={'proj-a': self.proj_a, 'proj-b': self.proj_b},
        )
        run_pipeline(cfg)
        report = load_report(self.report_path)
        self.assertGreater(len(report.delta_candidates), 0)

    def test_e2e_delta_candidates_have_required_fields(self):
        cfg = PipelineConfig(
            registry_path=self.registry_path,
            rejections_path=self.rejections_path,
            report_path=self.report_path,
            project_roots={'proj-a': self.proj_a, 'proj-b': self.proj_b},
        )
        run_pipeline(cfg)
        report = load_report(self.report_path)
        for candidate in report.delta_candidates:
            self.assertIn('file', candidate)
            self.assertIn('kind', candidate)
            self.assertIn('introduced_at', candidate)
            self.assertIn('project', candidate)  # pipeline adds project name

    def test_e2e_updates_last_processed_commit(self):
        cfg = PipelineConfig(
            registry_path=self.registry_path,
            rejections_path=self.rejections_path,
            report_path=self.report_path,
            project_roots={'proj-a': self.proj_a, 'proj-b': self.proj_b},
        )
        run_pipeline(cfg)
        reg = ProjectRegistry(self.registry_path)
        proj_a = reg.get('proj-a')
        self.assertIsNotNone(proj_a['last_processed_commit'])


class TestRunPipelineHappyPath(unittest.TestCase):
    """Happy path — complete session: candidates in, patterns-garden entries out."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.proj_a = _make_synthetic_project(self.root, 'proj-a', with_interface=True)
        self.proj_b = _make_synthetic_project(self.root, 'proj-b', with_interface=True)

        self.registry_path = self.root / 'projects.yaml'
        self.registry_path.write_text('projects: []\n')
        reg = ProjectRegistry(self.registry_path)
        for name, path in [('proj-a', self.proj_a), ('proj-b', self.proj_b)]:
            reg.add({'project': name, 'url': f'https://github.com/org/{name}',
                     'domain': 'jvm', 'primary_language': 'java',
                     'frameworks': [], 'last_processed_commit': None,
                     'notable_contributors': []})

        self.rejections_path = self.root / 'rejections.yaml'
        self.rejections_path.write_text('rejections: []\n')
        self.report_path = self.root / 'report.json'
        self.patterns_dir = self.root / 'patterns'

    def tearDown(self):
        self.tmp.cleanup()

    def test_happy_path_pipeline_to_accepted_entry(self):
        """Full journey: run pipeline → load report → validate (accept all) → GP entry on disk."""
        from validate_candidates import validate_candidates, Decision

        # Step 1: run pipeline
        cfg = PipelineConfig(
            registry_path=self.registry_path,
            rejections_path=self.rejections_path,
            report_path=self.report_path,
            project_roots={'proj-a': self.proj_a, 'proj-b': self.proj_b},
        )
        run_pipeline(cfg)

        # Step 2: load the report
        report = load_report(self.report_path)
        self.assertGreater(report.total_count(), 0)

        # Step 3: validate — accept everything
        registry = ProjectRegistry(self.registry_path)
        summary = validate_candidates(
            report,
            registry.list(),
            self.rejections_path,
            self.patterns_dir,
            decide_fn=lambda c: (Decision.ACCEPT, None),
        )

        # Step 4: at least one GP entry was written
        gp_files = list(self.patterns_dir.glob('GP-*.md'))
        self.assertGreater(len(gp_files), 0)
        self.assertGreater(summary.accepted, 0)
        self.assertEqual(summary.rejected, 0)
