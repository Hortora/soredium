package io.hortora.garden.engine;

import jakarta.enterprise.context.ApplicationScoped;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

@ApplicationScoped
public class ClusterPipeline {

    public List<ClusterCandidate> cluster(Map<String, Fingerprint> fingerprints,
                                           List<KnownPattern> knownPatterns,
                                           double threshold) {
        if (fingerprints.size() < 2) return List.of();

        var names = new ArrayList<>(fingerprints.keySet());
        // Convert to ratio fingerprints for size-independent comparison
        var ratioVectors = names.stream()
                .collect(Collectors.toMap(n -> n, n -> toRatioVector(fingerprints.get(n))));

        // Greedy complete-linkage clustering
        var assigned = new HashSet<String>();
        var clusters = new ArrayList<List<String>>();

        for (int i = 0; i < names.size(); i++) {
            var name = names.get(i);
            if (assigned.contains(name)) continue;
            var cluster = new ArrayList<String>();
            cluster.add(name);
            for (int j = i + 1; j < names.size(); j++) {
                var other = names.get(j);
                if (assigned.contains(other)) continue;
                // Complete-linkage: other must be similar to ALL existing members
                if (cluster.stream().allMatch(m ->
                        cosineSimilarity(ratioVectors.get(m), ratioVectors.get(other)) >= threshold)) {
                    cluster.add(other);
                    assigned.add(other);
                }
            }
            if (cluster.size() >= 2) {
                assigned.add(name);
                clusters.add(cluster);
            }
        }

        return clusters.stream().map(c -> {
            var fps = c.stream().map(fingerprints::get).toList();
            var centroid = computeCentroid(fps);
            var simScore = computeSimilarity(c, ratioVectors);
            var match = matchKnownPattern(ratioVectors.get(c.get(0)), knownPatterns);
            return new ClusterCandidate(c, centroid, simScore, match);
        }).toList();
    }

    private double[] toRatioVector(Fingerprint fp) {
        double fc = Math.max(fp.fileCount(), 1);
        return new double[]{
            fp.interfaceCount() / fc,
            fp.abstractionDepth(),
            fp.injectionPoints() / fc,
            fp.extensionSignatures() / fc,
            fp.spiPatterns() / fc
        };
    }

    private double cosineSimilarity(double[] a, double[] b) {
        double dot = 0, magA = 0, magB = 0;
        for (int i = 0; i < a.length; i++) {
            dot += a[i] * b[i];
            magA += a[i] * a[i];
            magB += b[i] * b[i];
        }
        if (magA == 0 || magB == 0) return 0.0;
        return dot / (Math.sqrt(magA) * Math.sqrt(magB));
    }

    private Fingerprint computeCentroid(List<Fingerprint> fps) {
        return new Fingerprint(
                (int) fps.stream().mapToInt(Fingerprint::interfaceCount).average().orElse(0),
                fps.stream().mapToDouble(Fingerprint::abstractionDepth).average().orElse(0),
                (int) fps.stream().mapToInt(Fingerprint::injectionPoints).average().orElse(0),
                (int) fps.stream().mapToInt(Fingerprint::extensionSignatures).average().orElse(0),
                (int) fps.stream().mapToInt(Fingerprint::fileCount).average().orElse(0),
                (int) fps.stream().mapToInt(Fingerprint::spiPatterns).average().orElse(0)
        );
    }

    private double computeSimilarity(List<String> cluster, Map<String, double[]> vectors) {
        if (cluster.size() == 1) return 1.0;
        double total = 0;
        int pairs = 0;
        for (int i = 0; i < cluster.size(); i++) {
            for (int j = i + 1; j < cluster.size(); j++) {
                total += cosineSimilarity(vectors.get(cluster.get(i)), vectors.get(cluster.get(j)));
                pairs++;
            }
        }
        return pairs > 0 ? total / pairs : 0.0;
    }

    private String matchKnownPattern(double[] centroidVec, List<KnownPattern> patterns) {
        for (var p : patterns) {
            if (cosineSimilarity(centroidVec, toRatioVector(p.signature())) >= 0.9)
                return p.name();
        }
        return null;
    }
}
