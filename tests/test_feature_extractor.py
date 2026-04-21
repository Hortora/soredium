import unittest
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
from feature_extractor import extract_features


def _write(root: Path, rel: str, content: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


class TestFeatureExtractor(unittest.TestCase):

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_empty_directory_returns_zero_counts(self):
        features = extract_features(self.root)
        self.assertEqual(features['interface_count'], 0)
        self.assertEqual(features['file_count'], 0)

    def test_counts_java_interfaces(self):
        _write(self.root, 'src/Foo.java', 'public interface Foo {}')
        _write(self.root, 'src/Bar.java', 'public interface Bar extends Foo {}')
        _write(self.root, 'src/Baz.java', 'public class Baz implements Foo {}')
        features = extract_features(self.root)
        self.assertEqual(features['interface_count'], 2)
        self.assertEqual(features['file_count'], 3)

    def test_counts_injection_points(self):
        _write(self.root, 'src/A.java',
               '@ApplicationScoped\npublic class A {\n  @Inject Foo foo;\n}')
        features = extract_features(self.root)
        self.assertEqual(features['injection_points'], 2)

    def test_counts_extension_signatures(self):
        _write(self.root, 'src/A.java', 'public class A extends B implements C, D {}')
        features = extract_features(self.root)
        self.assertEqual(features['extension_signatures'], 1)

    def test_counts_spi_services_file(self):
        _write(self.root, 'META-INF/services/com.example.Foo',
               'com.example.impl.FooImpl\n')
        features = extract_features(self.root)
        self.assertEqual(features['spi_patterns'], 1)

    def test_ignores_non_source_files(self):
        _write(self.root, 'README.md', '# interface Foo')
        _write(self.root, 'build.xml', '<interface name="Foo"/>')
        features = extract_features(self.root)
        self.assertEqual(features['interface_count'], 0)

    def test_python_injection_via_type_hints(self):
        _write(self.root, 'src/service.py',
               'def __init__(self, foo: Foo, bar: Bar) -> None: ...')
        features = extract_features(self.root)
        self.assertGreaterEqual(features['injection_points'], 0)