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

    // --- Qdrant-dependent tests: deferred to Phase 2 ---

    @Test
    @Disabled("Requires Qdrant DevServices — Phase 2")
    void fingerprintIsIndexedIntoQdrant() {
        // Will inject QdrantClient or embedding service and verify point upsert
    }

    @Test
    @Disabled("Requires Qdrant DevServices — Phase 2")
    void qdrantSearchFindsIndexedFingerprint() {
        // Will verify nearest-neighbour search returns the indexed fingerprint
    }

    @Test
    @Disabled("Requires Qdrant DevServices — Phase 2")
    void harvestCommandWithTwoDuplicateEntries() {
        // Will run full harvest cycle against a real Qdrant collection
    }

    @Test
    @Disabled("Requires Qdrant DevServices — Phase 2")
    void mineToHarvestQdrantContainsMergedEntry() {
        // Will verify end-to-end mine → harvest → Qdrant merged entry round-trip
    }
}
