package io.hortora.garden.engine;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.time.Duration;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Random;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertTimeout;

class ClusterPipelineTest {

    private ClusterPipeline pipeline;

    @BeforeEach
    void setUp() {
        pipeline = new ClusterPipeline();
    }

    // -----------------------------------------------------------------------
    // Unit tests (8)
    // -----------------------------------------------------------------------

    @Test
    void fewerThanTwoProjectsReturnsEmptyList() {
        var fp = new Fingerprint(10, 0.5, 5, 3, 20, 1);
        var result = pipeline.cluster(Map.of("only", fp), List.of(), 0.9);
        assertThat(result).isEmpty();
    }

    @Test
    void identicalFingerprintsFormACluster() {
        var fp = new Fingerprint(10, 0.5, 5, 3, 20, 1);
        var result = pipeline.cluster(Map.of("alpha", fp, "beta", fp), List.of(), 0.9);
        assertThat(result).hasSize(1);
        assertThat(result.get(0).projects()).containsExactlyInAnyOrder("alpha", "beta");
    }

    @Test
    void dissimilarFingerprintsDoNotCluster() {
        // fp1: injection-heavy (high injectionPoints/fileCount ratio)
        // fp2: pure-library (near-zero injection ratio, high interface ratio)
        var fp1 = new Fingerprint(5, 0.1, 800, 10, 1000, 2);   // injection ratio 0.8, interface ratio 0.005
        var fp2 = new Fingerprint(900, 0.9, 2, 20, 1000, 1);   // injection ratio 0.002, interface ratio 0.9
        var result = pipeline.cluster(Map.of("injection-heavy", fp1, "interface-heavy", fp2), List.of(), 0.85);
        assertThat(result).isEmpty();
    }

    @Test
    void allClustersHaveAtLeastTwoMembers() {
        var identical = new Fingerprint(10, 0.5, 5, 3, 20, 1);
        var outlier = new Fingerprint(1, 0.01, 1, 1, 100, 0);
        var result = pipeline.cluster(
                Map.of("a", identical, "b", identical, "c", outlier),
                List.of(), 0.9);
        assertThat(result).allSatisfy(c -> assertThat(c.projects()).hasSizeGreaterThanOrEqualTo(2));
    }

    @Test
    void centroidValuesAreMeanOfRawFingerprints() {
        var fp1 = new Fingerprint(10, 0.4, 4, 2, 40, 2);
        var fp2 = new Fingerprint(20, 0.6, 8, 6, 60, 4);
        var result = pipeline.cluster(Map.of("p1", fp1, "p2", fp2), List.of(), 0.5);
        assertThat(result).hasSize(1);
        var centroid = result.get(0).centroid();
        assertThat(centroid.interfaceCount()).isEqualTo(15);
        assertThat(centroid.abstractionDepth()).isCloseTo(0.5, org.assertj.core.data.Offset.offset(0.001));
        assertThat(centroid.injectionPoints()).isEqualTo(6);
        assertThat(centroid.extensionSignatures()).isEqualTo(4);
        assertThat(centroid.fileCount()).isEqualTo(50);
        assertThat(centroid.spiPatterns()).isEqualTo(3);
    }

    @Test
    void similarityScoreIsBetweenZeroAndOne() {
        var fp = new Fingerprint(10, 0.5, 5, 3, 20, 1);
        var result = pipeline.cluster(Map.of("a", fp, "b", fp), List.of(), 0.9);
        assertThat(result).isNotEmpty();
        assertThat(result.get(0).similarityScore()).isBetween(0.0, 1.0);
    }

    @Test
    void knownPatternMatchIsTaggedWhenCentroidCosineAboveThreshold() {
        var fp = new Fingerprint(10, 0.5, 5, 3, 20, 1);
        var pattern = new KnownPattern("framework-pattern", new Fingerprint(10, 0.5, 5, 3, 20, 1));
        var result = pipeline.cluster(Map.of("p1", fp, "p2", fp), List.of(pattern), 0.9);
        assertThat(result).hasSize(1);
        assertThat(result.get(0).matchesKnownPattern()).isEqualTo("framework-pattern");
    }

    @Test
    void noKnownPatternMatchReturnsNullMatchesKnownPattern() {
        var fp = new Fingerprint(10, 0.5, 5, 3, 20, 1);
        var dissimilarPattern = new KnownPattern("other", new Fingerprint(1, 0.01, 0, 0, 500, 0));
        var result = pipeline.cluster(Map.of("p1", fp, "p2", fp), List.of(dissimilarPattern), 0.9);
        assertThat(result).hasSize(1);
        assertThat(result.get(0).matchesKnownPattern()).isNull();
    }

    // -----------------------------------------------------------------------
    // Correctness tests — ratio normalisation (3)
    // -----------------------------------------------------------------------

    @Test
    void smallAndLargeProjectDoNotClusterAtHighThreshold() {
        // Regression test for issue #36: without ratio conversion, cosine ~ 0.999
        var fpSmall = new Fingerprint(1, 0.167, 0, 0, 6, 0);
        var fpLarge = new Fingerprint(5457, 0.253, 8696, 10106, 21570, 192);
        var result = pipeline.cluster(Map.of("small", fpSmall, "large", fpLarge), List.of(), 0.9);
        assertThat(result).isEmpty();
    }

    @Test
    void projectsWithIdenticalRatiosClusterRegardlessOfRawCounts() {
        // fp1: interfaceCount/fileCount=0.1, injectionPoints/fileCount=0.2
        var fp1 = new Fingerprint(10, 0.3, 20, 15, 100, 5);
        // fp2: same ratios but 100x bigger
        var fp2 = new Fingerprint(1000, 0.3, 2000, 1500, 10000, 500);
        var result = pipeline.cluster(Map.of("small", fp1, "big", fp2), List.of(), 0.85);
        assertThat(result).hasSize(1);
        assertThat(result.get(0).projects()).containsExactlyInAnyOrder("small", "big");
    }

    @Test
    void quarkusLikeAndHibernateLikeDoNotCluster() {
        // quarkus injection ratio ~0.40, hibernate injection ratio ~0.009
        var quarkusLike = new Fingerprint(5457, 0.253, 8696, 10106, 21570, 192);
        var hibernateLike = new Fingerprint(3658, 0.216, 34, 9569, 16924, 41);
        var result = pipeline.cluster(Map.of("quarkus", quarkusLike, "hibernate", hibernateLike), List.of(), 0.85);
        assertThat(result).isEmpty();
    }

    // -----------------------------------------------------------------------
    // Robustness tests (3)
    // -----------------------------------------------------------------------

    @Test
    void allZeroFingerprintDoesNotCauseDivisionByZero() {
        var fpZero = new Fingerprint(0, 0.0, 0, 0, 0, 0);
        assertDoesNotThrow(() -> pipeline.cluster(Map.of("z1", fpZero, "z2", fpZero), List.of(), 0.9));
    }

    @Test
    void singleProjectReturnsEmptyListWithoutException() {
        var fp = new Fingerprint(5, 0.3, 2, 1, 10, 0);
        var result = pipeline.cluster(Map.of("solo", fp), List.of(), 0.9);
        assertThat(result).isEmpty();
    }

    @Test
    void hundredProjectSetCompletesInUnderOneSecond() {
        var rng = new Random(42L);
        Map<String, Fingerprint> fingerprints = new HashMap<>();
        for (int i = 0; i < 100; i++) {
            fingerprints.put("proj-" + i, new Fingerprint(
                    rng.nextInt(200) + 1,
                    rng.nextDouble(),
                    rng.nextInt(500),
                    rng.nextInt(300),
                    rng.nextInt(1000) + 1,
                    rng.nextInt(50)));
        }
        assertTimeout(Duration.ofSeconds(1), () -> pipeline.cluster(fingerprints, List.of(), 0.75));
    }
}
