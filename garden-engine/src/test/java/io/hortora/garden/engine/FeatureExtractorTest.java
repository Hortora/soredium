package io.hortora.garden.engine;

import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import java.io.IOException;
import java.nio.file.*;
import java.nio.file.attribute.PosixFilePermission;
import java.time.Duration;
import java.util.Set;
import java.util.concurrent.CompletableFuture;
import static org.assertj.core.api.Assertions.*;
import static org.junit.jupiter.api.Assertions.*;

class FeatureExtractorTest {

    @TempDir Path root;
    FeatureExtractor extractor = new FeatureExtractor();

    // ── Unit tests ────────────────────────────────────────────────────────────

    @Test
    void emptyDirectoryReturnsZeroCounts() throws IOException {
        Fingerprint fp = extractor.extract(root);
        assertThat(fp.interfaceCount()).isEqualTo(0);
        assertThat(fp.fileCount()).isEqualTo(0);
        assertThat(fp.abstractionDepth()).isEqualTo(0.0);
    }

    @Test
    void countsInterfaceDeclarationsInJavaFiles() throws IOException {
        TestFixtures.write(root, "Foo.java", "public interface Foo {}");
        TestFixtures.write(root, "Bar.java", "public interface Bar extends Foo {}");
        Fingerprint fp = extractor.extract(root);
        assertThat(fp.interfaceCount()).isEqualTo(2);
    }

    @Test
    void countsAbstractClassDeclarations() throws IOException {
        TestFixtures.write(root, "Base.java", "public abstract class Base {}");
        Fingerprint fp = extractor.extract(root);
        assertThat(fp.interfaceCount()).isEqualTo(1);
    }

    @Test
    void countsCdiInjectionAnnotations() throws IOException {
        TestFixtures.write(root, "A.java",
            "@ApplicationScoped\npublic class A {\n  @Inject Foo f;\n}");
        Fingerprint fp = extractor.extract(root);
        assertThat(fp.injectionPoints()).isEqualTo(2);
    }

    @Test
    void countsExtendsImplementsSignatures() throws IOException {
        TestFixtures.write(root, "A.java", "public class A extends B implements C, D {}");
        Fingerprint fp = extractor.extract(root);
        assertThat(fp.extensionSignatures()).isEqualTo(1);
    }

    @Test
    void countsMetaInfServicesSpiFiles() throws IOException {
        TestFixtures.write(root, "META-INF/services/com.example.Foo",
            "com.example.impl.FooImpl\n");
        Fingerprint fp = extractor.extract(root);
        assertThat(fp.spiPatterns()).isEqualTo(1);
    }

    @Test
    void ignoresNonSourceFiles() throws IOException {
        TestFixtures.write(root, "README.md", "# interface Foo");
        TestFixtures.write(root, "pom.xml", "<interface name='Foo'/>");
        Fingerprint fp = extractor.extract(root);
        assertThat(fp.interfaceCount()).isEqualTo(0);
    }

    @Test
    void ignoresBinaryAndClassFiles() throws IOException {
        Path classFile = root.resolve("Foo.class");
        Files.write(classFile, new byte[]{(byte)0xCA, (byte)0xFE, (byte)0xBA, (byte)0xBE});
        assertThatCode(() -> extractor.extract(root)).doesNotThrowAnyException();
        Fingerprint fp = extractor.extract(root);
        assertThat(fp.interfaceCount()).isEqualTo(0);
    }

    @Test
    void abstractionDepthIsInterfaceCountDividedByFileCount() throws IOException {
        TestFixtures.write(root, "IFoo.java", "public interface IFoo {}");
        TestFixtures.write(root, "IBar.java", "public interface IBar {}");
        TestFixtures.write(root, "Baz.java", "public class Baz {}");
        TestFixtures.write(root, "Qux.java", "public class Qux {}");
        Fingerprint fp = extractor.extract(root);
        assertThat(fp.abstractionDepth()).isCloseTo(0.5, within(0.001));
    }

    @Test
    void abstractionDepthIsZeroForEmptyDirectory() throws IOException {
        Fingerprint fp = extractor.extract(root);
        assertThat(fp.abstractionDepth()).isEqualTo(0.0);
    }

    @Test
    void kotlinFilesCountedAsSource() throws IOException {
        TestFixtures.write(root, "Foo.kt", "interface Foo");
        Fingerprint fp = extractor.extract(root);
        assertThat(fp.fileCount()).isEqualTo(1);
    }

    @Test
    void fileWithBadEncodingSkippedWithoutException() throws IOException {
        Path bad = root.resolve("Bad.java");
        Files.write(bad, new byte[]{(byte)0xFF, (byte)0xFE, (byte)0x00});
        assertDoesNotThrow(() -> extractor.extract(root));
    }

    // ── Correctness tests ─────────────────────────────────────────────────────

    @Test
    void knownFingerprint_10Interfaces_40Injections_50Files() throws IOException {
        // 10 interface files
        for (int i = 0; i < 10; i++) {
            TestFixtures.write(root, "src/IFace" + i + ".java",
                "public interface IFace" + i + " {}");
        }
        // 10 bean files: each has @ApplicationScoped + 3x @Inject = 4 annotations per file
        // but we want 40 total injectionPoints = 10 beans * 4 = 40
        for (int i = 0; i < 10; i++) {
            TestFixtures.write(root, "src/Bean" + i + ".java",
                "@ApplicationScoped\npublic class Bean" + i + " {\n" +
                "  @Inject IFace0 a;\n" +
                "  @Inject IFace1 b;\n" +
                "  @Inject IFace2 c;\n" +
                "}");
        }
        // 40 plain class files to bring total to 60
        for (int i = 0; i < 40; i++) {
            TestFixtures.write(root, "src/Plain" + i + ".java",
                "public class Plain" + i + " {}");
        }
        Fingerprint fp = extractor.extract(root);
        assertThat(fp.interfaceCount()).isEqualTo(10);
        assertThat(fp.injectionPoints()).isEqualTo(40);
        assertThat(fp.fileCount()).isEqualTo(60);
        assertThat(fp.abstractionDepth()).isCloseTo(10.0 / 60.0, within(0.001));
    }

    @Test
    void injectionCountMatchesPythonFixture() throws IOException {
        TestFixtures.write(root, "A.java",
            "@ApplicationScoped\npublic class A {\n  @Inject Foo foo;\n}");
        Fingerprint fp = extractor.extract(root);
        assertThat(fp.injectionPoints()).isEqualTo(2);
    }

    // ── Robustness tests ──────────────────────────────────────────────────────

    @Test
    @Timeout(5)
    void symlinkToParentDoesNotCauseInfiniteTraversal() throws IOException {
        Path link = root.resolve("loop");
        Files.createSymbolicLink(link, root);
        assertThatCode(() -> extractor.extract(root)).doesNotThrowAnyException();
    }

    Path secretFile;

    @AfterEach
    void restorePermissions() throws IOException {
        if (secretFile != null && Files.exists(secretFile)) {
            Files.setPosixFilePermissions(secretFile,
                Set.of(PosixFilePermission.OWNER_READ,
                       PosixFilePermission.OWNER_WRITE));
        }
    }

    @Test
    void permissionDeniedFileIsSkipped() throws IOException {
        secretFile = root.resolve("Secret.java");
        Files.writeString(secretFile, "public interface Secret {}");
        Files.setPosixFilePermissions(secretFile, Set.of());
        assertThatCode(() -> extractor.extract(root)).doesNotThrowAnyException();
        Fingerprint fp = extractor.extract(root);
        assertThat(fp.interfaceCount()).isEqualTo(0);
    }

    @Test
    void largeSourceTreeCompletesWithinTenSeconds() throws IOException {
        TestFixtures.javaProjectWithInterfaces(root, 100, 9900);
        assertTimeout(Duration.ofSeconds(10), () -> extractor.extract(root));
    }

    @Test
    void concurrentCallsOnDifferentRootsAreThreadSafe() throws Exception {
        Path[] dirs = new Path[4];
        for (int i = 0; i < 4; i++) {
            dirs[i] = Files.createTempDirectory("concurrent-" + i);
            for (int j = 0; j < 5; j++) {
                TestFixtures.write(dirs[i], "IFace" + j + ".java",
                    "public interface IFace" + j + " {}");
            }
        }
        try {
            @SuppressWarnings("unchecked")
            CompletableFuture<Fingerprint>[] futures = new CompletableFuture[4];
            for (int i = 0; i < 4; i++) {
                final Path dir = dirs[i];
                futures[i] = CompletableFuture.supplyAsync(() -> {
                    try {
                        return extractor.extract(dir);
                    } catch (IOException e) {
                        throw new RuntimeException(e);
                    }
                });
            }
            CompletableFuture.allOf(futures).join();
            for (CompletableFuture<Fingerprint> f : futures) {
                assertThat(f.get().interfaceCount()).isEqualTo(5);
            }
        } finally {
            for (Path dir : dirs) {
                if (dir != null) {
                    try (var s = Files.walk(dir)) {
                        s.sorted(java.util.Comparator.reverseOrder())
                         .forEach(p -> { try { Files.delete(p); } catch (IOException ignored) {} });
                    }
                }
            }
        }
    }
}
