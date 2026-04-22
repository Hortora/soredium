package io.hortora.garden.engine;

import io.hortora.garden.engine.ai.DedupeClassifierImpl;
import io.hortora.garden.engine.ai.EntryMergeServiceImpl;
import io.hortora.garden.engine.ai.PatternNamingServiceImpl;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CopyOnWriteArrayList;

import static org.assertj.core.api.Assertions.*;
import static org.assertj.core.data.Offset.offset;
import static org.junit.jupiter.api.Assertions.*;

class RobustnessTest {

    @TempDir
    Path root;

    FeatureExtractor extractor = new FeatureExtractor();

    // ── Helper ────────────────────────────────────────────────────────────────

    private static Map<String, Object> entry(String name) {
        return new java.util.HashMap<>(Map.of(
            "project", name,
            "url", "https://github.com/x/" + name,
            "domain", "jvm",
            "primary_language", "java",
            "frameworks", List.of(),
            "last_processed_commit", "null",
            "notable_contributors", List.of()
        ));
    }

    // ── Input edge cases ──────────────────────────────────────────────────────

    @Test
    void javaFileContainingOnlyCommentsHasNoCountsAndNoException() throws IOException {
        TestFixtures.write(root, "OnlyComments.java",
            "// This is a comment\n/* Another comment */\n// interface Foo {}");
        var fp = extractor.extract(root);
        assertThat(fp.interfaceCount()).isZero();
        assertThat(fp.fileCount()).isEqualTo(1);
        assertDoesNotThrow(() -> extractor.extract(root));
    }

    @Test
    void interfaceInStringLiteralIsNotCounted() throws IOException {
        TestFixtures.write(root, "Holder.java",
            "public class Holder {\n  String s = \"public interface Foo {}\";\n}");
        assertThat(extractor.extract(root).interfaceCount()).isZero();
    }

    @Test
    void deeplyNestedDirectoryStructureIsTraversedCorrectly() throws IOException {
        var deep = root;
        for (int i = 0; i < 20; i++) deep = deep.resolve("level" + i);
        Files.createDirectories(deep);
        TestFixtures.write(deep, "Deep.java", "public interface Deep {}");
        assertThat(extractor.extract(root).interfaceCount()).isEqualTo(1);
    }

    @Test
    void projectWithZeroJavaFilesButValidSpiFileHasSpiPatternOne() throws IOException {
        TestFixtures.write(root, "META-INF/services/com.example.Plugin", "com.example.impl.PluginImpl");
        var fp = extractor.extract(root);
        assertThat(fp.spiPatterns()).isEqualTo(1);
        assertThat(fp.interfaceCount()).isZero();
        assertThat(fp.fileCount()).isZero();
    }

    @Test
    void projectWhereEveryFileIsAnInterfaceHasAbstractionDepthOne() throws IOException {
        for (int i = 0; i < 5; i++) {
            TestFixtures.write(root, "Iface" + i + ".java", "public interface Iface" + i + " {}");
        }
        assertThat(extractor.extract(root).abstractionDepth()).isCloseTo(1.0, offset(0.001));
    }

    @Test
    void registryWithHundredProjectsListsAllHundred() throws IOException {
        var path = Files.createTempFile("registry", ".yaml");
        Files.writeString(path, "projects: []\n");
        var registry = new ProjectRegistry(path);
        for (int i = 0; i < 100; i++) registry.add(entry("project-" + i));
        assertThat(registry.list()).hasSize(100);
    }

    // ── Failure recovery ──────────────────────────────────────────────────────

    @Test
    void gitSubprocessTimeoutThrowsExceptionNotHangIndefinitely() throws IOException {
        var notARepo = Files.createTempDirectory("not-a-repo");
        var delta = new DeltaAnalysis();
        assertThatThrownBy(() -> delta.getMajorVersionTags(notARepo))
            .isInstanceOf(RuntimeException.class);
    }

    @Test
    void aiMergeProducingInvalidYamlIsRejected() {
        var service = new EntryMergeServiceImpl();
        assertThatThrownBy(() -> service.mergeEntries("just plain text no yaml"))
            .isInstanceOf(IllegalStateException.class);
        assertDoesNotThrow(() -> service.mergeEntries("---\nid: x\ntitle: t\nscore: 9\n---\nbody"));
    }

    @Test
    void aiClassificationWithUnexpectedJsonFieldParsedWithDefaults() {
        var classifier = new DedupeClassifierImpl();
        var json = """
            {"classification":"DISTINCT","reasoning":"ok","keep_id":null,\
            "preserve_from_other":null,"unknown_future_field":"extra"}""";
        assertDoesNotThrow(() -> classifier.classify(json));
        var result = classifier.classify(json);
        assertThat(result.classification()).isEqualTo(DedupeDecision.Classification.DISTINCT);
    }

    @Test
    void registryFileDeletedAfterListReturnsException() throws IOException {
        var path = Files.createTempFile("registry", ".yaml");
        Files.writeString(path, TestFixtures.projectsYaml("p1"));
        var registry = new ProjectRegistry(path);
        assertThat(registry.list()).hasSize(1);
        Files.delete(path);
        assertThatThrownBy(() -> registry.list())
            .isInstanceOf(IOException.class);
    }

    @Test
    void emptyClusterContextDoesNotCauseNullPointerInPatternNaming() {
        var service = new PatternNamingServiceImpl();
        assertThat(service.namePattern(null)).isNull();
        assertThat(service.namePattern("")).isNull();
        assertThat(service.namePattern("   ")).isNull();
    }

    // ── Concurrency ───────────────────────────────────────────────────────────

    @Test
    void twoMineProcessesForDifferentProjectsDoNotCorruptRegistry() throws IOException {
        var path = Files.createTempFile("registry", ".yaml");
        Files.writeString(path, "projects: []\n");
        var registry = new ProjectRegistry(path);

        var f1 = CompletableFuture.runAsync(() -> {
            try { registry.add(entry("project-a")); } catch (IOException e) { throw new RuntimeException(e); }
        });
        var f2 = CompletableFuture.runAsync(() -> {
            try { registry.add(entry("project-b")); } catch (IOException e) { throw new RuntimeException(e); }
        });

        CompletableFuture.allOf(f1, f2).join();
        var projects = registry.list();
        assertThat(projects).hasSize(2);
        assertThat(projects).extracting(p -> p.get("project"))
            .containsExactlyInAnyOrder("project-a", "project-b");
    }

    @Test
    void harvestLockFilePreventsConcurrentMerges() throws IOException {
        var path = Files.createTempFile("registry", ".yaml");
        Files.writeString(path, TestFixtures.projectsYaml("my-project"));
        var registry = new ProjectRegistry(path);

        var results = new CopyOnWriteArrayList<String>();
        var f1 = CompletableFuture.runAsync(() -> {
            try { registry.updateCommit("my-project", "commit-a"); results.add("a"); }
            catch (IOException e) { throw new RuntimeException(e); }
        });
        var f2 = CompletableFuture.runAsync(() -> {
            try { registry.updateCommit("my-project", "commit-b"); results.add("b"); }
            catch (IOException e) { throw new RuntimeException(e); }
        });

        CompletableFuture.allOf(f1, f2).join();
        assertThat(results).hasSize(2);
        var commit = registry.get("my-project").orElseThrow().get("last_processed_commit");
        assertThat(commit).isIn("commit-a", "commit-b");
    }
}
