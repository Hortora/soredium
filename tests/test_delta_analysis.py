import unittest
import sys
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
from delta_analysis import delta_analysis, get_major_version_tags


def _git(repo: Path, *args: str) -> None:
    subprocess.run(['git', '-C', str(repo)] + list(args), check=True, capture_output=True)


def _make_repo(root: Path) -> Path:
    repo = root / 'repo'
    repo.mkdir()
    _git(repo, 'init')
    _git(repo, 'config', 'user.email', 'test@example.com')
    _git(repo, 'config', 'user.name', 'Test User')

    # v1.0 — plain class only
    (repo / 'src').mkdir()
    (repo / 'src' / 'Service.java').write_text('public class Service {}\n')
    _git(repo, 'add', '.')
    _git(repo, 'commit', '-m', 'initial')
    _git(repo, 'tag', 'v1.0')

    # v2.0 — adds an interface and an abstract class
    (repo / 'src' / 'Evaluator.java').write_text('public interface Evaluator { void eval(); }\n')
    (repo / 'src' / 'AbstractBase.java').write_text('public abstract class AbstractBase {}\n')
    _git(repo, 'add', '.')
    _git(repo, 'commit', '-m', 'add Evaluator interface')
    _git(repo, 'tag', 'v2.0')

    return repo


class TestDeltaAnalysis(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.repo = _make_repo(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_new_abstractions_returns_empty(self):
        result = delta_analysis(self.repo, from_ref='v1.0', to_ref='v1.0')
        self.assertEqual(result, [])

    def test_detects_new_interface(self):
        result = delta_analysis(self.repo, from_ref='v1.0', to_ref='v2.0')
        files = [c['file'] for c in result]
        self.assertTrue(any('Evaluator' in f for f in files))

    def test_detects_new_abstract_class(self):
        result = delta_analysis(self.repo, from_ref='v1.0', to_ref='v2.0')
        files = [c['file'] for c in result]
        self.assertTrue(any('AbstractBase' in f for f in files))

    def test_candidate_has_required_fields(self):
        result = delta_analysis(self.repo, from_ref='v1.0', to_ref='v2.0')
        self.assertTrue(len(result) > 0)
        for c in result:
            self.assertIn('file', c)
            self.assertIn('kind', c)
            self.assertIn('introduced_at', c)
            self.assertIn('commit', c)
            self.assertIn('author', c)
            self.assertIn('date', c)

    def test_kind_is_interface_or_abstract_class(self):
        result = delta_analysis(self.repo, from_ref='v1.0', to_ref='v2.0')
        for c in result:
            self.assertIn(c['kind'], ('interface', 'abstract_class'))

    def test_get_major_version_tags(self):
        tags = get_major_version_tags(self.repo)
        self.assertIn('v1.0', tags)
        self.assertIn('v2.0', tags)

    def test_pre_existing_files_not_reported(self):
        result = delta_analysis(self.repo, from_ref='v1.0', to_ref='v2.0')
        files = [c['file'] for c in result]
        self.assertFalse(any('Service' in f for f in files))
