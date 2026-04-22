package io.hortora.garden.engine;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.dataformat.yaml.YAMLFactory;

import java.io.FileNotFoundException;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.*;

/**
 * Persistent YAML-backed registry of projects to process.
 *
 * NOTE: @ApplicationScoped removed for Task 4 — tests use {@code new} directly.
 * CDI wiring is added back in Task 6.
 */
public class ProjectRegistry {

    private static final ObjectMapper YAML = new ObjectMapper(new YAMLFactory())
        .configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, false);

    private static final Set<String> REQUIRED = Set.of(
        "project", "url", "domain", "primary_language", "frameworks",
        "last_processed_commit", "notable_contributors"
    );

    private final Path path;

    public ProjectRegistry(Path path) {
        this.path = path;
    }

    @SuppressWarnings("unchecked")
    public List<Map<String, Object>> list() throws IOException {
        if (!Files.exists(path)) {
            throw new FileNotFoundException("Registry file not found: " + path);
        }
        Map<String, Object> data;
        try {
            data = YAML.readValue(path.toFile(), Map.class);
        } catch (Exception e) {
            throw new IOException("YAML parse failure reading registry: " + path + " — " + e.getMessage(), e);
        }
        if (data == null) {
            return List.of();
        }
        var projects = (List<Map<String, Object>>) data.getOrDefault("projects", List.of());
        return projects != null ? projects : List.of();
    }

    public Optional<Map<String, Object>> get(String name) throws IOException {
        return list().stream()
            .filter(p -> name.equals(p.get("project")))
            .findFirst();
    }

    public synchronized void add(Map<String, Object> entry) throws IOException {
        var missing = new HashSet<>(REQUIRED);
        missing.removeAll(entry.keySet());
        if (!missing.isEmpty()) {
            throw new IllegalArgumentException("Missing required fields: " + missing);
        }
        var current = new ArrayList<>(list());
        boolean duplicate = current.stream()
            .anyMatch(p -> entry.get("project").equals(p.get("project")));
        if (duplicate) {
            throw new IllegalArgumentException("Project already exists: " + entry.get("project"));
        }
        current.add(entry);
        save(current);
    }

    public synchronized void updateCommit(String name, String commit) throws IOException {
        var projects = new ArrayList<>(list());
        projects.stream()
            .filter(p -> name.equals(p.get("project")))
            .findFirst()
            .orElseThrow(() -> new IllegalArgumentException("Project not found: " + name))
            .put("last_processed_commit", commit);
        save(projects);
    }

    private void save(List<Map<String, Object>> projects) throws IOException {
        YAML.writeValue(path.toFile(), Map.of("projects", projects));
    }
}
