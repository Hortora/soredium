package io.hortora.garden.engine;

import jakarta.enterprise.context.ApplicationScoped;
import java.util.List;
import java.util.Map;

@ApplicationScoped
public class ClusterPipeline {

    public List<ClusterCandidate> cluster(Map<String, Fingerprint> fingerprints,
                                           List<KnownPattern> knownPatterns,
                                           double threshold) {
        throw new UnsupportedOperationException("not yet implemented");
    }
}
