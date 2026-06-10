package io.hortora.garden.engine;

import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;

public class JlamaModelChecker {

    private final Path cacheDir;

    public JlamaModelChecker() {
        this(Path.of(System.getProperty("jlama.cache",
            System.getProperty("user.home") + "/.jlama")));
    }

    public JlamaModelChecker(Path cacheDir) {
        this.cacheDir = cacheDir;
    }

    public Path cacheDir() {
        return cacheDir;
    }

    public boolean isModelCached(String modelName) {
        if (!Files.isDirectory(cacheDir)) return false;
        // Model name format: "org/ModelName" → cached as "org/ModelName/" directory
        var modelPath = cacheDir.resolve(modelName.replace("/", File.separator));
        return Files.isDirectory(modelPath);
    }
}
