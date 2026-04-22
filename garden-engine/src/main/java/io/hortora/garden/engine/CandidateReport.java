package io.hortora.garden.engine;

import java.util.List;

public record CandidateReport(
    List<ClusterCandidate> clusterCandidates,
    List<DeltaCandidate> deltaCandidates
) {}
