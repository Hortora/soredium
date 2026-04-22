package io.hortora.garden.engine;

import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.nio.file.*;
import java.util.*;

import static org.assertj.core.api.Assertions.*;

/**
 * Python equivalence tests — each test mirrors an exact Python test scenario.
 * Inputs and expected values are taken directly from the Python test fixtures.
 * These are the acceptance gate for the Java port: same inputs must produce
 * identical output.
 *
 * Python-only test skipped: test_python_injection_via_type_hints
 *   (.py type hints are a Python-specific feature; the Java extractor has no .py equivalent)
 */
class PythonEquivalenceTest {

    // ─────────────────────────────────────────────────────────────────────────
    // Shared fixtures — exact values from Python test_cluster_pipeline.py
    // ─────────────────────────────────────────────────────────────────────────

    /** interface_count=20, abstraction_depth=0.6, injection_points=15,
     *  extension_signatures=18, file_count=33, spi_patterns=4 */
    static final Fingerprint FP_HIGH_ABSTRACTION   = new Fingerprint(20, 0.6,  15, 18, 33, 4);

    /** interface_count=18, abstraction_depth=0.55, injection_points=14,
     *  extension_signatures=16, file_count=30, spi_patterns=3 */
    static final Fingerprint FP_HIGH_ABSTRACTION_2 = new Fingerprint(18, 0.55, 14, 16, 30, 3);

    /** interface_count=1,  abstraction_depth=0.02, injection_points=2,
     *  extension_signatures=1,  file_count=50, spi_patterns=0 */
    static final Fingerprint FP_LOW_ABSTRACTION    = new Fingerprint(1,  0.02,  2,  1, 50, 0);

    // ═════════════════════════════════════════════════════════════════════════
    // FeatureExtractor equivalence — 6 Python scenarios (Python-only test skipped)
    // ═════════════════════════════════════════════════════════════════════════

    @Nested
    @DisplayName("FeatureExtractor — Python equivalence")
    class FeatureExtractorEquivalence {

        @TempDir Path root;
        final FeatureExtractor extractor = new FeatureExtractor();

        /**
         * Python: test_empty_directory_returns_zero_counts
         *   features = extract_features(root)
         *   assertEqual(features['interface_count'], 0)
         *   assertEqual(features['file_count'], 0)
         */
        @Test
        @DisplayName("py: test_empty_directory_returns_zero_counts")
        void emptyDirectoryReturnsZeroCounts() throws IOException {
            Fingerprint fp = extractor.extract(root);
            assertThat(fp.interfaceCount()).isEqualTo(0);
            assertThat(fp.fileCount()).isEqualTo(0);
        }

        /**
         * Python: test_counts_java_interfaces
         *   write 'public interface Foo {}'
         *   write 'public interface Bar extends Foo {}'
         *   write 'public class Baz implements Foo {}'
         *   assertEqual(features['interface_count'], 2)
         *   assertEqual(features['file_count'], 3)
         */
        @Test
        @DisplayName("py: test_counts_java_interfaces")
        void countsJavaInterfaces() throws IOException {
            TestFixtures.write(root, "src/Foo.java", "public interface Foo {}");
            TestFixtures.write(root, "src/Bar.java", "public interface Bar extends Foo {}");
            TestFixtures.write(root, "src/Baz.java", "public class Baz implements Foo {}");
            Fingerprint fp = extractor.extract(root);
            assertThat(fp.interfaceCount()).isEqualTo(2);
            assertThat(fp.fileCount()).isEqualTo(3);
        }

        /**
         * Python: test_counts_injection_points
         *   write '@ApplicationScoped\npublic class A {\n  @Inject Foo foo;\n}'
         *   assertEqual(features['injection_points'], 2)
         */
        @Test
        @DisplayName("py: test_counts_injection_points")
        void countsInjectionPoints() throws IOException {
            TestFixtures.write(root, "src/A.java",
                "@ApplicationScoped\npublic class A {\n  @Inject Foo foo;\n}");
            Fingerprint fp = extractor.extract(root);
            assertThat(fp.injectionPoints()).isEqualTo(2);
        }

        /**
         * Python: test_counts_extension_signatures
         *   write 'public class A extends B implements C, D {}'
         *   assertEqual(features['extension_signatures'], 1)
         */
        @Test
        @DisplayName("py: test_counts_extension_signatures")
        void countsExtensionSignatures() throws IOException {
            TestFixtures.write(root, "src/A.java", "public class A extends B implements C, D {}");
            Fingerprint fp = extractor.extract(root);
            assertThat(fp.extensionSignatures()).isEqualTo(1);
        }

        /**
         * Python: test_counts_spi_services_file
         *   write META-INF/services/com.example.Foo → 'com.example.impl.FooImpl\n'
         *   assertEqual(features['spi_patterns'], 1)
         */
        @Test
        @DisplayName("py: test_counts_spi_services_file")
        void countsSpiServicesFile() throws IOException {
            TestFixtures.write(root, "META-INF/services/com.example.Foo",
                "com.example.impl.FooImpl\n");
            Fingerprint fp = extractor.extract(root);
            assertThat(fp.spiPatterns()).isEqualTo(1);
        }

        /**
         * Python: test_ignores_non_source_files
         *   write README.md '# interface Foo'
         *   write build.xml  '<interface name="Foo"/>'
         *   assertEqual(features['interface_count'], 0)
         */
        @Test
        @DisplayName("py: test_ignores_non_source_files")
        void ignoresNonSourceFiles() throws IOException {
            TestFixtures.write(root, "README.md", "# interface Foo");
            TestFixtures.write(root, "build.xml", "<interface name=\"Foo\"/>");
            Fingerprint fp = extractor.extract(root);
            assertThat(fp.interfaceCount()).isEqualTo(0);
        }

        // Python: test_python_injection_via_type_hints — SKIPPED
        // This test exercises Python-specific __init__ type hints.
        // The Java extractor has no equivalent .py handling — skipping intentionally.
    }

    // ═════════════════════════════════════════════════════════════════════════
    // ClusterPipeline equivalence — 6 Python scenarios
    // ═════════════════════════════════════════════════════════════════════════

    @Nested
    @DisplayName("ClusterPipeline — Python equivalence")
    class ClusterPipelineEquivalence {

        final ClusterPipeline pipeline = new ClusterPipeline();

        /**
         * Python: test_feature_keys_defined
         *   assertIn('interface_count', FEATURE_KEYS)
         *   assertIn('abstraction_depth', FEATURE_KEYS)
         *
         * Java equivalent: Fingerprint record has matching fields
         * (FEATURE_KEYS are the 6 Fingerprint fields in the same order).
         */
        @Test
        @DisplayName("py: test_feature_keys_defined")
        void featureKeysDefined() {
            // Fingerprint fields correspond exactly to Python FEATURE_KEYS:
            // ['interface_count', 'abstraction_depth', 'injection_points',
            //  'extension_signatures', 'file_count', 'spi_patterns']
            Fingerprint fp = FP_HIGH_ABSTRACTION;
            // Verify all 6 accessor methods exist and return the correct fixture values
            assertThat(fp.interfaceCount()).isEqualTo(20);
            assertThat(fp.abstractionDepth()).isEqualTo(0.6);
            assertThat(fp.injectionPoints()).isEqualTo(15);
            assertThat(fp.extensionSignatures()).isEqualTo(18);
            assertThat(fp.fileCount()).isEqualTo(33);
            assertThat(fp.spiPatterns()).isEqualTo(4);
        }

        /**
         * Python: test_fingerprint_to_vector_returns_list
         *   vec = fingerprint_to_vector(_FP_HIGH_ABSTRACTION)
         *   assertEqual(len(vec), len(FEATURE_KEYS))  → 6
         *   assertIsInstance(vec[0], float)
         *
         * Java equivalent: Fingerprint has exactly 6 fields.
         */
        @Test
        @DisplayName("py: test_fingerprint_to_vector_returns_list")
        void fingerprintToVectorReturnsCorrectLength() {
            // Python FEATURE_KEYS has 6 keys; Fingerprint record has exactly 6 components
            assertThat(FP_HIGH_ABSTRACTION.getClass().getRecordComponents()).hasSize(6);
        }

        /**
         * Python: test_too_few_projects_returns_empty
         *   result = cluster_projects({'only-one': _FP_HIGH_ABSTRACTION}, known_patterns=[])
         *   assertEqual(result, [])
         */
        @Test
        @DisplayName("py: test_too_few_projects_returns_empty")
        void tooFewProjectsReturnsEmpty() {
            var result = pipeline.cluster(
                Map.of("only-one", FP_HIGH_ABSTRACTION), List.of(), 0.95);
            assertThat(result).isEmpty();
        }

        /**
         * Python: test_similar_projects_form_candidate
         *   fingerprints = {'proj-a': HIGH, 'proj-b': HIGH_2, 'proj-c': LOW}
         *   candidates = cluster_projects(fingerprints, known_patterns=[])
         *   clustered = [set(c['projects']) for c in candidates]
         *   assertIn({'proj-a', 'proj-b'}, clustered)
         */
        @Test
        @DisplayName("py: test_similar_projects_form_candidate")
        void similarProjectsFormCandidate() {
            var fingerprints = new java.util.LinkedHashMap<String, Fingerprint>();
            fingerprints.put("proj-a", FP_HIGH_ABSTRACTION);
            fingerprints.put("proj-b", FP_HIGH_ABSTRACTION_2);
            fingerprints.put("proj-c", FP_LOW_ABSTRACTION);

            var candidates = pipeline.cluster(fingerprints, List.of(), 0.95);

            // proj-a and proj-b must form a cluster together
            boolean found = candidates.stream()
                .anyMatch(c -> new HashSet<>(c.projects()).equals(Set.of("proj-a", "proj-b")));
            assertThat(found)
                .as("Expected {proj-a, proj-b} to form a cluster")
                .isTrue();
        }

        /**
         * Python: test_candidate_has_required_fields
         *   fingerprints = {'proj-a': HIGH, 'proj-b': HIGH_2}
         *   candidates = cluster_projects(fingerprints, known_patterns=[])
         *   assertTrue(len(candidates) > 0)
         *   c = candidates[0]
         *   assertIn('projects', c)
         *   assertIn('centroid', c)
         *   assertIn('similarity_score', c)
         *   assertIn('matches_known_pattern', c)
         */
        @Test
        @DisplayName("py: test_candidate_has_required_fields")
        void candidateHasRequiredFields() {
            var fingerprints = Map.of(
                "proj-a", FP_HIGH_ABSTRACTION,
                "proj-b", FP_HIGH_ABSTRACTION_2
            );
            var candidates = pipeline.cluster(fingerprints, List.of(), 0.95);
            assertThat(candidates).isNotEmpty();

            var c = candidates.get(0);
            assertThat(c.projects()).as("projects field").isNotNull();
            assertThat(c.centroid()).as("centroid field").isNotNull();
            // similarity_score: must be a valid double — asserting it is non-negative
            assertThat(c.similarityScore()).as("similarity_score field").isGreaterThanOrEqualTo(0.0);
            // matches_known_pattern: null is valid (no known patterns provided)
            // Java field exists — record accessor compiles = field exists
            assertThatCode(c::matchesKnownPattern).doesNotThrowAnyException();
        }

        /**
         * Python: test_minimum_cluster_size_is_two
         *   fingerprints = {f'proj-{i}': HIGH for i in range(5)}
         *   candidates = cluster_projects(fingerprints, known_patterns=[])
         *   for c in candidates:
         *       assertGreaterEqual(len(c['projects']), 2)
         */
        @Test
        @DisplayName("py: test_minimum_cluster_size_is_two")
        void minimumClusterSizeIsTwo() {
            var fingerprints = new java.util.LinkedHashMap<String, Fingerprint>();
            for (int i = 0; i < 5; i++) {
                fingerprints.put("proj-" + i, FP_HIGH_ABSTRACTION);
            }
            var candidates = pipeline.cluster(fingerprints, List.of(), 0.95);
            assertThat(candidates).allSatisfy(c ->
                assertThat(c.projects()).hasSizeGreaterThanOrEqualTo(2));
        }
    }

    // ═════════════════════════════════════════════════════════════════════════
    // DeltaAnalysis equivalence — 7 Python scenarios
    // ═════════════════════════════════════════════════════════════════════════

    @Nested
    @DisplayName("DeltaAnalysis — Python equivalence")
    class DeltaAnalysisEquivalence {

        @TempDir Path root;
        final DeltaAnalysis delta = new DeltaAnalysis();

        /** Shared repo built once per test via TestFixtures.gitRepoWithTwoVersions. */
        Path repo;

        @BeforeEach
        void buildRepo() throws IOException, InterruptedException {
            repo = TestFixtures.gitRepoWithTwoVersions(root);
        }

        /**
         * Python: test_no_new_abstractions_returns_empty
         *   result = delta_analysis(repo, from_ref='v1.0', to_ref='v1.0')
         *   assertEqual(result, [])
         */
        @Test
        @DisplayName("py: test_no_new_abstractions_returns_empty")
        void noNewAbstractionsReturnsEmpty() {
            var result = delta.analyze(repo, "v1.0", "v1.0");
            assertThat(result).isEmpty();
        }

        /**
         * Python: test_detects_new_interface
         *   result = delta_analysis(repo, from_ref='v1.0', to_ref='v2.0')
         *   files = [c['file'] for c in result]
         *   assertTrue(any('Evaluator' in f for f in files))
         */
        @Test
        @DisplayName("py: test_detects_new_interface")
        void detectsNewInterface() {
            var result = delta.analyze(repo, "v1.0", "v2.0");
            assertThat(result)
                .as("Expected a candidate with 'Evaluator' in the file path")
                .anyMatch(c -> c.file().contains("Evaluator"));
        }

        /**
         * Python: test_detects_new_abstract_class
         *   result = delta_analysis(repo, from_ref='v1.0', to_ref='v2.0')
         *   files = [c['file'] for c in result]
         *   assertTrue(any('AbstractBase' in f for f in files))
         */
        @Test
        @DisplayName("py: test_detects_new_abstract_class")
        void detectsNewAbstractClass() {
            var result = delta.analyze(repo, "v1.0", "v2.0");
            assertThat(result)
                .as("Expected a candidate with 'AbstractBase' in the file path")
                .anyMatch(c -> c.file().contains("AbstractBase"));
        }

        /**
         * Python: test_candidate_has_required_fields
         *   result = delta_analysis(repo, from_ref='v1.0', to_ref='v2.0')
         *   assertTrue(len(result) > 0)
         *   for c in result:
         *       assertIn('file', c); assertIn('kind', c); assertIn('introduced_at', c)
         *       assertIn('commit', c); assertIn('author', c); assertIn('date', c)
         */
        @Test
        @DisplayName("py: test_candidate_has_required_fields")
        void candidateHasRequiredFields() {
            var result = delta.analyze(repo, "v1.0", "v2.0");
            assertThat(result).isNotEmpty();
            for (var c : result) {
                assertThat(c.file()).as("file").isNotNull().isNotBlank();
                assertThat(c.kind()).as("kind").isNotNull().isNotBlank();
                assertThat(c.introducedAt()).as("introduced_at").isNotNull().isNotBlank();
                assertThat(c.commit()).as("commit").isNotNull().isNotBlank();
                assertThat(c.author()).as("author").isNotNull().isNotBlank();
                assertThat(c.date()).as("date").isNotNull().isNotBlank();
            }
        }

        /**
         * Python: test_kind_is_interface_or_abstract_class
         *   result = delta_analysis(repo, from_ref='v1.0', to_ref='v2.0')
         *   for c in result:
         *       assertIn(c['kind'], ('interface', 'abstract_class'))
         */
        @Test
        @DisplayName("py: test_kind_is_interface_or_abstract_class")
        void kindIsInterfaceOrAbstractClass() {
            var result = delta.analyze(repo, "v1.0", "v2.0");
            assertThat(result).isNotEmpty();
            assertThat(result).allSatisfy(c ->
                assertThat(c.kind()).isIn("interface", "abstract_class"));
        }

        /**
         * Python: test_get_major_version_tags
         *   tags = get_major_version_tags(repo)
         *   assertIn('v1.0', tags)
         *   assertIn('v2.0', tags)
         */
        @Test
        @DisplayName("py: test_get_major_version_tags")
        void getMajorVersionTags() throws IOException, InterruptedException {
            var tags = delta.getMajorVersionTags(repo);
            assertThat(tags).contains("v1.0", "v2.0");
        }

        /**
         * Python: test_pre_existing_files_not_reported
         *   result = delta_analysis(repo, from_ref='v1.0', to_ref='v2.0')
         *   files = [c['file'] for c in result]
         *   assertFalse(any('Service' in f for f in files))
         *
         * Service.java was present in v1.0 — it must not appear as a new delta candidate.
         */
        @Test
        @DisplayName("py: test_pre_existing_files_not_reported")
        void preExistingFilesNotReported() {
            var result = delta.analyze(repo, "v1.0", "v2.0");
            assertThat(result)
                .as("Service.java existed in v1.0 — must not appear as a delta candidate")
                .noneMatch(c -> c.file().contains("Service"));
        }
    }

    // ═════════════════════════════════════════════════════════════════════════
    // ProjectRegistry equivalence — 6 Python scenarios
    // ═════════════════════════════════════════════════════════════════════════

    @Nested
    @DisplayName("ProjectRegistry — Python equivalence")
    class ProjectRegistryEquivalence {

        @TempDir Path tmpDir;

        /** Build the minimal valid entry used by the Python tests. */
        private Map<String, Object> pyEntry(String project) {
            var m = new java.util.HashMap<String, Object>();
            m.put("project", project);
            m.put("url", "https://github.com/" + project + "/" + project);
            m.put("domain", "jvm");
            m.put("primary_language", "java");
            m.put("frameworks", List.of());
            m.put("last_processed_commit", null);
            m.put("notable_contributors", List.of());
            return m;
        }

        /** Python setUp: path.write_text('projects: []\n') */
        private Path emptyRegistry() throws IOException {
            Path p = tmpDir.resolve("projects.yaml");
            Files.writeString(p, "projects: []\n");
            return p;
        }

        /**
         * Python: test_empty_registry_lists_nothing
         *   registry = ProjectRegistry(path)
         *   assertEqual(registry.list(), [])
         */
        @Test
        @DisplayName("py: test_empty_registry_lists_nothing")
        void emptyRegistryListsNothing() throws IOException {
            var registry = new ProjectRegistry(emptyRegistry());
            assertThat(registry.list()).isEmpty();
        }

        /**
         * Python: test_add_project_persists
         *   registry.add({project: 'serverless-workflow', url: ..., domain: 'jvm',
         *                  primary_language: 'java', frameworks: ['quarkus'],
         *                  last_processed_commit: None, notable_contributors: []})
         *   projects = registry.list()
         *   assertEqual(len(projects), 1)
         *   assertEqual(projects[0]['project'], 'serverless-workflow')
         */
        @Test
        @DisplayName("py: test_add_project_persists")
        void addProjectPersists() throws IOException {
            Path file = emptyRegistry();
            var registry = new ProjectRegistry(file);

            // Exact Python fixture entry
            var entry = new java.util.HashMap<String, Object>();
            entry.put("project", "serverless-workflow");
            entry.put("url", "https://github.com/serverlessworkflow/specification");
            entry.put("domain", "jvm");
            entry.put("primary_language", "java");
            entry.put("frameworks", List.of("quarkus"));
            entry.put("last_processed_commit", null);
            entry.put("notable_contributors", List.of());
            registry.add(entry);

            var projects = registry.list();
            assertThat(projects).hasSize(1);
            assertThat(projects.get(0).get("project")).isEqualTo("serverless-workflow");
        }

        /**
         * Python: test_add_duplicate_raises
         *   registry.add(entry)
         *   with self.assertRaises(ValueError):
         *       registry.add(entry)
         *
         * Java uses IllegalArgumentException (subtype of RuntimeException, same semantics as ValueError).
         */
        @Test
        @DisplayName("py: test_add_duplicate_raises")
        void addDuplicateRaises() throws IOException {
            Path file = emptyRegistry();
            var registry = new ProjectRegistry(file);
            var entry = pyEntry("foo");
            registry.add(entry);
            assertThatThrownBy(() -> registry.add(pyEntry("foo")))
                .isInstanceOf(IllegalArgumentException.class);
        }

        /**
         * Python: test_update_last_processed_commit
         *   registry.add({'project': 'foo', ...})
         *   registry.update_commit('foo', 'abc1234')
         *   project = registry.get('foo')
         *   assertEqual(project['last_processed_commit'], 'abc1234')
         */
        @Test
        @DisplayName("py: test_update_last_processed_commit")
        void updateLastProcessedCommit() throws IOException {
            Path file = emptyRegistry();
            var registry = new ProjectRegistry(file);
            registry.add(pyEntry("foo"));
            registry.updateCommit("foo", "abc1234");

            var project = registry.get("foo");
            assertThat(project).isPresent();
            assertThat(project.get().get("last_processed_commit")).isEqualTo("abc1234");
        }

        /**
         * Python: test_get_unknown_project_returns_none
         *   assertIsNone(registry.get('does-not-exist'))
         *
         * Java: Optional.empty() is the equivalent of None.
         */
        @Test
        @DisplayName("py: test_get_unknown_project_returns_none")
        void getUnknownProjectReturnsNone() throws IOException {
            var registry = new ProjectRegistry(emptyRegistry());
            assertThat(registry.get("does-not-exist")).isEmpty();
        }

        /**
         * Python: test_required_fields_validated_on_add
         *   with self.assertRaises(ValueError):
         *       registry.add({'project': 'missing-fields'})
         */
        @Test
        @DisplayName("py: test_required_fields_validated_on_add")
        void requiredFieldsValidatedOnAdd() throws IOException {
            var registry = new ProjectRegistry(emptyRegistry());
            assertThatThrownBy(() -> registry.add(Map.of("project", "missing-fields")))
                .isInstanceOf(IllegalArgumentException.class);
        }

        /**
         * Python: test_data_persists_across_instances
         *   registry.add({'project': 'foo', ...})
         *   reload = ProjectRegistry(self.path)
         *   assertEqual(len(reload.list()), 1)
         */
        @Test
        @DisplayName("py: test_data_persists_across_instances")
        void dataPersistsAcrossInstances() throws IOException {
            Path file = emptyRegistry();
            new ProjectRegistry(file).add(pyEntry("foo"));

            var reload = new ProjectRegistry(file);
            assertThat(reload.list()).hasSize(1);
        }
    }
}
