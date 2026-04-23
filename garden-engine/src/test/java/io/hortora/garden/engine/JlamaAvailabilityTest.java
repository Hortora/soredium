package io.hortora.garden.engine;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import java.io.IOException;
import java.nio.file.*;
import static org.assertj.core.api.Assertions.*;

class JlamaAvailabilityTest {

    @Test
    void requiresJlamaModelAnnotationExists() {
        assertThat(RequiresJlamaModel.class).isNotNull();
        assertThat(RequiresJlamaModel.class.isAnnotation()).isTrue();
    }

    @Test
    void jlamaModelCheckerUsesHomeDirByDefault() {
        var checker = new JlamaModelChecker();
        assertThat(checker.cacheDir().toString()).contains(".jlama");
    }

    @Test
    void checkerReturnsFalseForNonExistentModel() {
        var checker = new JlamaModelChecker();
        assertThat(checker.isModelCached("nonexistent/model-that-does-not-exist-xyz123"))
            .isFalse();
    }

    @Test
    void checkerReturnsTrueWhenModelDirExists(@TempDir Path cacheDir) throws IOException {
        Files.createDirectories(cacheDir.resolve("myorg").resolve("MyModel-JQ4"));
        var checker = new JlamaModelChecker(cacheDir);
        assertThat(checker.isModelCached("myorg/MyModel-JQ4")).isTrue();
    }

    @Test
    void checkerReturnsFalseWhenCacheDirMissing(@TempDir Path cacheDir) {
        var emptyCache = cacheDir.resolve("nonexistent");
        var checker = new JlamaModelChecker(emptyCache);
        assertThat(checker.isModelCached("any/Model")).isFalse();
    }
}
