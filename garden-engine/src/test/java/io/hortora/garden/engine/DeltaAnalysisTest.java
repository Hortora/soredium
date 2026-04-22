package io.hortora.garden.engine;

import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.nio.file.*;
import java.time.Duration;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * TDD tests for DeltaAnalysis — 15 tests covering unit, correctness, and robustness.
 */
class DeltaAnalysisTest {

    static DeltaAnalysis delta;

    @TempDir
    static Path root;

    static Path repo;

    @BeforeAll
    static void setup() throws IOException, InterruptedException {
        delta = new DeltaAnalysis();
        repo = TestFixtures.gitRepoWithTwoVersions(root);
    }

    // ─────────────────────────────────────────────
    // Unit tests (1–9)
    // ─────────────────────────────────────────────

    @Test
    @DisplayName("Test 1: no tags returns empty list from getMajorVersionTags")
    void noTagsReturnsEmptyList() throws IOException, InterruptedException {
        Path fresh = root.resolve("fresh-repo");
        Files.createDirectories(fresh);
        git(fresh, "init");
        git(fresh, "config", "user.email", "test@example.com");
        git(fresh, "config", "user.name", "Test");

        List<String> tags = delta.getMajorVersionTags(fresh);
        assertTrue(tags.isEmpty(), "Expected no tags but got: " + tags);
    }

    @Test
    @DisplayName("Test 2: single tag returns list of size 1 — not enough for a diff")
    void singleTagReturnsEmptyListFromGetMajorVersionTags() throws IOException, InterruptedException {
        Path r = root.resolve("single-tag-repo");
        Files.createDirectories(r.resolve("src"));
        git(r, "init");
        git(r, "config", "user.email", "test@example.com");
        git(r, "config", "user.name", "Test");
        TestFixtures.write(r, "src/Foo.java", "public class Foo {}");
        git(r, "add", ".");
        git(r, "commit", "-m", "init");
        git(r, "tag", "v1.0");

        List<String> tags = delta.getMajorVersionTags(r);
        assertEquals(1, tags.size(), "Expected 1 tag");
        // With only 1 tag there's no pair to diff — confirm analyze with same ref returns empty
        List<DeltaCandidate> result = delta.analyze(r, "v1.0", "v1.0");
        assertTrue(result.isEmpty(), "Self-diff should be empty");
    }

    @Test
    @DisplayName("Test 3: new interface file between versions is detected")
    void newInterfaceFileBetweenVersionsIsDetected() {
        List<DeltaCandidate> candidates = delta.analyze(repo, "v1.0", "v2.0");
        assertTrue(
            candidates.stream().anyMatch(c -> "interface".equals(c.kind())),
            "Expected at least one candidate with kind='interface'"
        );
    }

    @Test
    @DisplayName("Test 4: new abstract class between versions is detected")
    void newAbstractClassBetweenVersionsIsDetected() {
        List<DeltaCandidate> candidates = delta.analyze(repo, "v1.0", "v2.0");
        assertTrue(
            candidates.stream().anyMatch(c -> "abstract_class".equals(c.kind())),
            "Expected at least one candidate with kind='abstract_class'"
        );
    }

    @Test
    @DisplayName("Test 5: pre-existing files not in delta are excluded")
    void preExistingFilesNotInDeltaAreExcluded() {
        List<DeltaCandidate> candidates = delta.analyze(repo, "v1.0", "v2.0");
        assertTrue(
            candidates.stream().noneMatch(c -> c.file().contains("Service")),
            "Service.java existed in v1.0 — must not appear in delta"
        );
    }

    @Test
    @DisplayName("Test 6: all candidates have required non-blank fields")
    void candidateHasAllRequiredFields() {
        List<DeltaCandidate> candidates = delta.analyze(repo, "v1.0", "v2.0");
        assertFalse(candidates.isEmpty(), "Need candidates for this test");
        for (DeltaCandidate c : candidates) {
            assertNotNull(c.file(),         "file must not be null");
            assertFalse(c.file().isBlank(), "file must not be blank");
            assertNotNull(c.kind(),         "kind must not be null");
            assertFalse(c.kind().isBlank(), "kind must not be blank");
            assertNotNull(c.introducedAt(),         "introducedAt must not be null");
            assertFalse(c.introducedAt().isBlank(), "introducedAt must not be blank");
            assertNotNull(c.commit(),         "commit must not be null");
            assertFalse(c.commit().isBlank(), "commit must not be blank");
            assertNotNull(c.author(),         "author must not be null");
            assertFalse(c.author().isBlank(), "author must not be blank");
            assertNotNull(c.date(),         "date must not be null");
            assertFalse(c.date().isBlank(), "date must not be blank");
        }
    }

    @Test
    @DisplayName("Test 7: kind is exactly 'interface' or 'abstract_class' — no other values")
    void kindIsExactlyInterfaceOrAbstractClass() {
        List<DeltaCandidate> candidates = delta.analyze(repo, "v1.0", "v2.0");
        assertFalse(candidates.isEmpty(), "Need candidates for this test");
        for (DeltaCandidate c : candidates) {
            assertTrue(
                "interface".equals(c.kind()) || "abstract_class".equals(c.kind()),
                "Unexpected kind value: " + c.kind()
            );
        }
    }

    @Test
    @DisplayName("Test 8: fromRef equals toRef returns empty list")
    void fromRefEqualsToRefReturnsEmptyList() {
        List<DeltaCandidate> result = delta.analyze(repo, "v1.0", "v1.0");
        assertTrue(result.isEmpty(), "Self-diff must return empty");
    }

    @Test
    @DisplayName("Test 9: getMajorVersionTags returns tags in version order")
    void getMajorVersionTagsReturnsTagsInVersionOrder() {
        List<String> tags = delta.getMajorVersionTags(repo);
        assertTrue(tags.contains("v1.0"), "Expected v1.0 tag");
        assertTrue(tags.contains("v2.0"), "Expected v2.0 tag");
        int idx1 = tags.indexOf("v1.0");
        int idx2 = tags.indexOf("v2.0");
        assertTrue(idx1 < idx2, "v1.0 must come before v2.0, got: " + tags);
    }

    // ─────────────────────────────────────────────
    // Correctness tests (10–11)
    // ─────────────────────────────────────────────

    @Test
    @DisplayName("Test 10: v1.0→v2.0 produces exactly 2 candidates with correct files and kinds")
    void syntheticRepoV1ToV2ProducesExactlyTwoCandidates() {
        List<DeltaCandidate> candidates = delta.analyze(repo, "v1.0", "v2.0");
        assertEquals(2, candidates.size(), "Expected exactly 2 candidates, got: " + candidates);

        DeltaCandidate evaluator = candidates.stream()
            .filter(c -> c.file().contains("Evaluator"))
            .findFirst()
            .orElseThrow(() -> new AssertionError("No Evaluator candidate"));
        assertEquals("interface", evaluator.kind());

        DeltaCandidate abstractBase = candidates.stream()
            .filter(c -> c.file().contains("AbstractBase"))
            .findFirst()
            .orElseThrow(() -> new AssertionError("No AbstractBase candidate"));
        assertEquals("abstract_class", abstractBase.kind());
    }

    @Test
    @DisplayName("Test 11: git blame info matches commit that added the file")
    void gitBlameInfoMatchesCommitThatAddedTheFile() {
        List<DeltaCandidate> candidates = delta.analyze(repo, "v1.0", "v2.0");
        DeltaCandidate evaluator = candidates.stream()
            .filter(c -> c.file().contains("Evaluator"))
            .findFirst()
            .orElseThrow(() -> new AssertionError("No Evaluator candidate"));

        // commit should be a valid 7-char hex
        String commit = evaluator.commit();
        assertEquals(7, commit.length(), "commit should be 7 chars, got: " + commit);
        assertTrue(commit.matches("[0-9a-f]{7}"), "commit should be hex, got: " + commit);

        // author should be non-blank
        assertFalse(evaluator.author().isBlank(), "author must not be blank");

        // date should match ISO date format YYYY-MM-DD
        assertTrue(evaluator.date().matches("\\d{4}-\\d{2}-\\d{2}"),
            "date should match YYYY-MM-DD, got: " + evaluator.date());
    }

    // ─────────────────────────────────────────────
    // Robustness tests (12–15)
    // ─────────────────────────────────────────────

    @Test
    @DisplayName("Test 12: shallow clone detected — returns empty without throwing")
    void shallowCloneDetectedAndReturnsEmptyWithNoException() throws IOException, InterruptedException {
        Path source = TestFixtures.gitRepoWithTwoVersions(root.resolve("shallow-source"));
        Path shallow = root.resolve("shallow");

        var pb = new ProcessBuilder("git", "clone", "--depth=1",
            source.toUri().toString(), shallow.toString())
            .redirectErrorStream(true);
        int exit = pb.start().waitFor();
        assertEquals(0, exit, "git clone --depth=1 should succeed");

        assertDoesNotThrow(
            () -> delta.analyze(shallow, "HEAD", "HEAD"),
            "analyze on shallow clone must not throw"
        );

        List<DeltaCandidate> result = delta.analyze(shallow, "HEAD", "HEAD");
        assertTrue(result.isEmpty(), "Shallow clone should return empty list");
    }

    @Test
    @DisplayName("Test 13: non-Java files added between versions are not returned")
    void nonJavaFilesAddedBetweenVersionsAreNotReturned() throws IOException, InterruptedException {
        Path r = root.resolve("non-java-repo");
        Files.createDirectories(r.resolve("src"));
        git(r, "init");
        git(r, "config", "user.email", "test@example.com");
        git(r, "config", "user.name", "Test");

        // v1.0
        TestFixtures.write(r, "src/Service.java", "public class Service {}");
        git(r, "add", ".");
        git(r, "commit", "-m", "initial");
        git(r, "tag", "v1.0");

        // v2.0 — add non-Java files
        TestFixtures.write(r, "README.md", "# Readme");
        TestFixtures.write(r, "config.yaml", "key: value");
        git(r, "add", ".");
        git(r, "commit", "-m", "add docs");
        git(r, "tag", "v2.0");

        List<DeltaCandidate> candidates = delta.analyze(r, "v1.0", "v2.0");
        assertTrue(candidates.isEmpty(), "Non-Java files must not produce candidates");
    }

    @Test
    @DisplayName("Test 14: deleted files between versions do not appear as candidates")
    void deletedFilesBetweenVersionsDoNotAppearAsCandidates() throws IOException, InterruptedException {
        Path r = root.resolve("deleted-file-repo");
        Files.createDirectories(r.resolve("src"));
        git(r, "init");
        git(r, "config", "user.email", "test@example.com");
        git(r, "config", "user.name", "Test");

        // v1.0
        TestFixtures.write(r, "src/Service.java", "public class Service {}");
        TestFixtures.write(r, "src/Evaluator.java", "public interface Evaluator {}");
        git(r, "add", ".");
        git(r, "commit", "-m", "initial");
        git(r, "tag", "v1.0");

        // v2.0 — adds abstract class
        TestFixtures.write(r, "src/AbstractBase.java", "public abstract class AbstractBase {}");
        git(r, "add", ".");
        git(r, "commit", "-m", "add abstract");
        git(r, "tag", "v2.0");

        // v3.0 — delete Service.java
        Files.delete(r.resolve("src/Service.java"));
        git(r, "add", ".");
        git(r, "commit", "-m", "remove service");
        git(r, "tag", "v3.0");

        List<DeltaCandidate> candidates = delta.analyze(r, "v2.0", "v3.0");
        assertTrue(
            candidates.stream().noneMatch(c -> c.file().contains("Service")),
            "Deleted Service.java must not appear as a candidate"
        );
        assertTrue(candidates.isEmpty(),
            "No files were added in v2.0→v3.0, expected empty list");
    }

    @Test
    @DisplayName("Test 15: repo with 50 tags completes in under 5 seconds")
    void repoWithFiftyTagsCompletesInUnderFiveSeconds() throws IOException, InterruptedException {
        Path r = root.resolve("fifty-tag-repo");
        Files.createDirectories(r.resolve("src"));
        git(r, "init");
        git(r, "config", "user.email", "test@example.com");
        git(r, "config", "user.name", "Test");

        for (int i = 1; i <= 50; i++) {
            TestFixtures.write(r, "src/Class" + i + ".java", "public class Class" + i + " {}");
            git(r, "add", ".");
            git(r, "commit", "-m", "add class " + i);
            git(r, "tag", "v" + i + ".0");
        }

        assertTimeout(Duration.ofSeconds(5), () -> {
            List<String> tags = delta.getMajorVersionTags(r);
            assertEquals(50, tags.size());
            // Run analyze on a few consecutive tag pairs
            for (int i = 0; i < Math.min(tags.size() - 1, 10); i++) {
                delta.analyze(r, tags.get(i), tags.get(i + 1));
            }
        }, "getMajorVersionTags + analyze should complete in under 5 seconds");
    }

    // ─────────────────────────────────────────────
    // Helpers
    // ─────────────────────────────────────────────

    private static void git(Path repo, String... args) throws IOException, InterruptedException {
        var cmd = new java.util.ArrayList<String>();
        cmd.add("git");
        cmd.addAll(List.of(args));
        var pb = new ProcessBuilder(cmd).directory(repo.toFile()).redirectErrorStream(true);
        int exit = pb.start().waitFor();
        if (exit != 0) throw new RuntimeException("git " + String.join(" ", args) + " failed: " + exit);
    }
}
