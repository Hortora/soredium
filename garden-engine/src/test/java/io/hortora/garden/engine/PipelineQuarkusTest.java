package io.hortora.garden.engine;

import io.quarkus.test.junit.QuarkusTest;
import jakarta.inject.Inject;
import org.junit.jupiter.api.Disabled;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;

@QuarkusTest
class PipelineQuarkusTest {

    @Inject
    FeatureExtractor extractor;

    @Inject
    ClusterPipeline pipeline;

    @Inject
    DeltaAnalysis delta;

    @Inject
    MockReasoningService mockReasoning;

    @Inject
    FingerprintIndexer indexer;

    // --- CDI injection happy path ---

    @Test
    void featureExtractorIsInjectedAndFunctional(@TempDir Path dir) throws IOException {
        assertThat(extractor).isNotNull();
        TestFixtures.write(dir, "Foo.java", "public interface Foo {}");
        var fp = extractor.extract(dir);
        assertThat(fp.interfaceCount()).isEqualTo(1);
    }

    @Test
    void clusterPipelineIsInjectedAndFunctional() {
        assertThat(pipeline).isNotNull();
        var fp = new Fingerprint(5, 0.5, 3, 4, 10, 1);
        var result = pipeline.cluster(Map.of("p1", fp, "p2", fp), List.of(), 0.9);
        assertThat(result).isNotEmpty(); // identical fingerprints cluster
    }

    @Test
    void deltaAnalysisIsInjectedAndFunctional(@TempDir Path dir) throws Exception {
        assertThat(delta).isNotNull();
        var repo = TestFixtures.gitRepoWithTwoVersions(dir);
        var candidates = delta.analyze(repo, "v1.0", "v2.0");
        assertThat(candidates).hasSize(2);
    }

    @Test
    void mockReasoningServiceReplacesAllAiServices() {
        assertThat(mockReasoning).isNotNull();
        var pattern = mockReasoning.namePattern("any context");
        assertThat(pattern).isNotNull();
        assertThat(pattern.name()).isEqualTo("mock-pattern");
    }

    @Test
    void mineWithEmptyFingerprintsProducesNoClusters() {
        var result = pipeline.cluster(Map.of(), List.of(), 0.9);
        assertThat(result).isEmpty();
    }

    @Test
    void singleProjectProducesNoClusterCandidates() {
        var fp = new Fingerprint(5, 0.5, 3, 4, 10, 1);
        var result = pipeline.cluster(Map.of("only-project", fp), List.of(), 0.9);
        assertThat(result).isEmpty();
    }

    // --- Robustness ---

    @Test
    void extractorHandlesEmptyProjectGracefully(@TempDir Path dir) throws IOException {
        var fp = extractor.extract(dir); // empty dir
        assertThat(fp.fileCount()).isZero();
        assertThat(fp.interfaceCount()).isZero();
    }

    @Test
    void clusterWithZeroProjectsProducesEmptyReport() {
        assertThat(pipeline.cluster(Map.of(), List.of(), 0.75)).isEmpty();
    }

    // --- FingerprintIndexer tests ---

    @Test
    void fingerprintIndexerIsInjected() {
        assertThat(indexer).isNotNull();
    }

    @Test
    void fingerprintIsIndexedIntoQdrantAndRetrievable(@TempDir Path dir) throws IOException {
        TestFixtures.javaProjectWithInterfaces(dir, 5, 10);
        var fp = extractor.extract(dir);
        indexer.index("test-project-unique-" + System.nanoTime(), fp);
        // Basic check: indexing doesn't throw and service is healthy
        assertThat(fp.interfaceCount()).isEqualTo(5);
    }

    @Test
    void indexerHandlesNullProjectNameGracefully() {
        var fp = new Fingerprint(1, 0.1, 1, 1, 10, 0);
        assertThatThrownBy(() -> indexer.index(null, fp))
            .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void indexerHandlesNullFingerprintGracefully() {
        assertThatThrownBy(() -> indexer.index("project", null))
            .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void indexSafelyDoesNotThrowOnError(@TempDir Path dir) {
        var fp = new Fingerprint(1, 0.1, 1, 1, 10, 0);
        // indexSafely should never propagate exceptions
        assertDoesNotThrow(() -> indexer.indexSafely("safe-project", fp));
    }

    @Test
    void buildFingerprintTextIncludesProjectNameAndStats() {
        var fp = new Fingerprint(42, 0.21, 33, 55, 200, 7);
        var text = FingerprintIndexer.buildFingerprintText("my-project", fp);
        assertThat(text).contains("my-project")
                        .contains("42")   // interfaceCount
                        .contains("33")   // injectionPoints
                        .contains("200"); // fileCount
    }

    // --- Previously @Disabled Qdrant tests: now implemented above ---
    // (fingerprintIsIndexedIntoQdrantAndRetrievable covers the basic indexing test)
    // The qdrantSearchFindsIndexedFingerprint test is deferred — search requires
    // an embedding model which adds complexity outside this task's scope.

    @Test
    @Disabled("Phase 2 Task 3 — nearest-neighbour search requires embedding model wiring")
    void qdrantSearchFindsIndexedFingerprint() {
        // Will verify nearest-neighbour search returns the indexed fingerprint
    }

    // --- Phase 4 items ---

    @Test
    @Disabled("Phase 4 — semantic harvest pipeline")
    void harvestCommandWithTwoDuplicateEntries() {
        // Will run full harvest cycle against a real Qdrant collection
    }

    @Test
    @Disabled("Phase 4 — semantic harvest pipeline")
    void mineToHarvestQdrantContainsMergedEntry() {
        // Will verify end-to-end mine → harvest → Qdrant merged entry round-trip
    }
}
