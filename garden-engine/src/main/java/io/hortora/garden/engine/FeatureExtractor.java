package io.hortora.garden.engine;

import jakarta.enterprise.context.ApplicationScoped;
import java.io.IOException;
import java.nio.file.Path;

@ApplicationScoped
public class FeatureExtractor {

    public Fingerprint extract(Path root) throws IOException {
        throw new UnsupportedOperationException("not yet implemented");
    }
}
