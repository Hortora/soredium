package io.hortora.garden.engine;

import jakarta.enterprise.context.ApplicationScoped;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.Optional;

@ApplicationScoped
public class ProjectRegistry {

    private final Path registryPath;

    public ProjectRegistry(Path registryPath) {
        this.registryPath = registryPath;
    }

    public List<Map<String, Object>> list() {
        throw new UnsupportedOperationException("not yet implemented");
    }

    public Optional<Map<String, Object>> get(String name) {
        throw new UnsupportedOperationException("not yet implemented");
    }

    public void add(Map<String, Object> entry) {
        throw new UnsupportedOperationException("not yet implemented");
    }

    public void updateCommit(String name, String commit) {
        throw new UnsupportedOperationException("not yet implemented");
    }
}
