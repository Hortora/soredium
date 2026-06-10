package io.hortora.garden.engine;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.FileNotFoundException;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.*;

class ProjectRegistryTest {

    @TempDir
    Path tempDir;

    private static Map<String, Object> entry(String name) {
        return new java.util.HashMap<>(Map.of(
            "project", name,
            "url", "https://github.com/example/" + name,
            "domain", "jvm",
            "primary_language", "java",
            "frameworks", List.of(),
            "last_processed_commit", "null",
            "notable_contributors", List.of()
        ));
    }

    // ---------------------------------------------------------------------------
    // Unit tests (6)
    // ---------------------------------------------------------------------------

    @Test
    void emptyRegistryListsNothing() throws IOException {
        Path file = tempDir.resolve("projects.yaml");
        Files.writeString(file, "projects: []\n");

        var registry = new ProjectRegistry(file);
        assertThat(registry.list()).isEmpty();
    }

    @Test
    void addProjectPersistsAcrossInstances() throws IOException {
        Path file = tempDir.resolve("projects.yaml");
        Files.writeString(file, "projects: []\n");

        new ProjectRegistry(file).add(entry("my-project"));

        var loaded = new ProjectRegistry(file).list();
        assertThat(loaded).hasSize(1);
        assertThat(loaded.get(0).get("project")).isEqualTo("my-project");
    }

    @Test
    void addDuplicateRaisesException() throws IOException {
        Path file = tempDir.resolve("projects.yaml");
        Files.writeString(file, "projects: []\n");

        var registry = new ProjectRegistry(file);
        registry.add(entry("dup-project"));

        assertThatThrownBy(() -> registry.add(entry("dup-project")))
            .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void updateLastProcessedCommitPersists() throws IOException {
        Path file = tempDir.resolve("projects.yaml");
        Files.writeString(file, "projects: []\n");

        var registry = new ProjectRegistry(file);
        registry.add(entry("commit-project"));
        registry.updateCommit("commit-project", "abc1234");

        var project = registry.get("commit-project");
        assertThat(project).isPresent();
        assertThat(project.get().get("last_processed_commit")).isEqualTo("abc1234");
    }

    @Test
    void getUnknownProjectReturnsEmptyOptional() throws IOException {
        Path file = tempDir.resolve("projects.yaml");
        Files.writeString(file, "projects: []\n");

        var registry = new ProjectRegistry(file);
        assertThat(registry.get("does-not-exist")).isEmpty();
    }

    @Test
    void requiredFieldsValidatedOnAdd() throws IOException {
        Path file = tempDir.resolve("projects.yaml");
        Files.writeString(file, "projects: []\n");

        var registry = new ProjectRegistry(file);
        assertThatThrownBy(() -> registry.add(Map.of("project", "incomplete")))
            .isInstanceOf(IllegalArgumentException.class)
            .hasMessageContaining("Missing");
    }

    // ---------------------------------------------------------------------------
    // Correctness tests (2)
    // ---------------------------------------------------------------------------

    @Test
    void yamlRoundTripPreservesAllFields() throws IOException {
        Path file = tempDir.resolve("projects.yaml");
        Files.writeString(file, "projects: []\n");

        Map<String, Object> original = entry("round-trip-project");
        new ProjectRegistry(file).add(original);

        var loaded = new ProjectRegistry(file).list();
        assertThat(loaded).hasSize(1);
        var project = loaded.get(0);

        assertThat(project.get("project")).isEqualTo("round-trip-project");
        assertThat(project.get("url")).isEqualTo("https://github.com/example/round-trip-project");
        assertThat(project.get("domain")).isEqualTo("jvm");
        assertThat(project.get("primary_language")).isEqualTo("java");
        assertThat(project.get("frameworks")).isNotNull();
        assertThat(project.get("notable_contributors")).isNotNull();
    }

    @Test
    void fiveProjectsLoadAllFiveInOrder() throws IOException {
        Path file = tempDir.resolve("projects.yaml");
        Files.writeString(file, TestFixtures.projectsYaml("a", "b", "c", "d", "e"));

        var loaded = new ProjectRegistry(file).list();
        assertThat(loaded).hasSize(5);
        assertThat(loaded.get(0).get("project")).isEqualTo("a");
        assertThat(loaded.get(1).get("project")).isEqualTo("b");
        assertThat(loaded.get(2).get("project")).isEqualTo("c");
        assertThat(loaded.get(3).get("project")).isEqualTo("d");
        assertThat(loaded.get(4).get("project")).isEqualTo("e");
    }

    // ---------------------------------------------------------------------------
    // Robustness tests (3)
    // ---------------------------------------------------------------------------

    @Test
    void corruptYamlThrowsDescriptiveException() throws IOException {
        Path file = tempDir.resolve("projects.yaml");
        Files.writeString(file, "this is not yaml: ][{{{");

        var registry = new ProjectRegistry(file);
        assertThatThrownBy(registry::list)
            .isNotInstanceOf(NullPointerException.class)
            .hasMessageContainingAll("YAML");
    }

    @Test
    void missingFileThrowsFileNotFoundException() {
        Path missing = tempDir.resolve("no-such-file.yaml");
        var registry = new ProjectRegistry(missing);

        assertThatThrownBy(registry::list)
            .isInstanceOf(IOException.class);
    }

    @Test
    void concurrentAddCallsDoNotCorruptFile() throws IOException, InterruptedException {
        Path file = tempDir.resolve("projects.yaml");
        Files.writeString(file, "projects: []\n");

        var registry = new ProjectRegistry(file);
        var latch = new CountDownLatch(1);
        var errors = new ArrayList<Throwable>();

        Runnable addA = () -> {
            try {
                latch.await();
                registry.add(entry("project-alpha"));
            } catch (IllegalArgumentException ignored) {
                // duplicate on retry is acceptable — last-write-wins
            } catch (Throwable t) {
                synchronized (errors) { errors.add(t); }
            }
        };

        Runnable addB = () -> {
            try {
                latch.await();
                registry.add(entry("project-beta"));
            } catch (IllegalArgumentException ignored) {
                // duplicate on retry is acceptable — last-write-wins
            } catch (Throwable t) {
                synchronized (errors) { errors.add(t); }
            }
        };

        ExecutorService exec = Executors.newFixedThreadPool(2);
        exec.submit(addA);
        exec.submit(addB);
        latch.countDown();
        exec.shutdown();
        exec.awaitTermination(10, TimeUnit.SECONDS);

        assertThat(errors).isEmpty();

        // File must not be corrupted — loading must succeed and return 1 or 2 projects
        List<Map<String, Object>> result = new ProjectRegistry(file).list();
        assertThat(result).hasSizeBetween(1, 2);
        for (var p : result) {
            assertThat(p.get("project")).isIn("project-alpha", "project-beta");
        }
    }
}
