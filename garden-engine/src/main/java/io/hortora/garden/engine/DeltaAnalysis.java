package io.hortora.garden.engine;

import jakarta.enterprise.context.ApplicationScoped;
import java.nio.file.Path;
import java.util.List;

@ApplicationScoped
public class DeltaAnalysis {

    public List<DeltaCandidate> analyze(Path repo, String fromRef, String toRef) {
        throw new UnsupportedOperationException("not yet implemented");
    }

    public List<String> getMajorVersionTags(Path repo) {
        throw new UnsupportedOperationException("not yet implemented");
    }
}
