package io.hortora.garden.engine;

import java.util.List;

public record ClusterCandidate(
    List<String> projects,
    Fingerprint centroid,
    double similarityScore,
    String matchesKnownPattern
) {}
