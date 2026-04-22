package io.hortora.garden.engine.ai;

import io.hortora.garden.engine.PatternCandidate;

public interface PatternNamingService {
    PatternCandidate namePattern(String clusterContext);
}
