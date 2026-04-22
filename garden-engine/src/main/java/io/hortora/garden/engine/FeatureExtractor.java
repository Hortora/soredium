package io.hortora.garden.engine;

import jakarta.enterprise.context.ApplicationScoped;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.BasicFileAttributes;
import java.util.HashSet;
import java.util.Set;
import java.util.regex.Pattern;

@ApplicationScoped
public class FeatureExtractor {

    private static final Pattern INTERFACE_OR_ABSTRACT =
        Pattern.compile("\\b(?:interface|abstract\\s+class)\\b");

    private static final Pattern INJECTION =
        Pattern.compile("@(?:Inject|Autowired|ApplicationScoped|RequestScoped|SessionScoped|Singleton|Dependent)\\b");

    private static final Pattern EXTENDS_IMPLEMENTS =
        Pattern.compile("\\bclass\\s+\\w+(?:\\s*<[^>]*>)?\\s+(?:extends|implements)\\b");

    public Fingerprint extract(Path root) throws IOException {
        Counter counter = new Counter();
        Set<Path> visitedDirs = new HashSet<>();

        Files.walkFileTree(root, Set.of(FileVisitOption.FOLLOW_LINKS), Integer.MAX_VALUE,
            new SimpleFileVisitor<>() {

                @Override
                public FileVisitResult preVisitDirectory(Path dir, BasicFileAttributes attrs)
                        throws IOException {
                    Path real;
                    try {
                        real = dir.toRealPath();
                    } catch (IOException e) {
                        return FileVisitResult.SKIP_SUBTREE;
                    }
                    if (!visitedDirs.add(real)) {
                        return FileVisitResult.SKIP_SUBTREE;
                    }
                    return FileVisitResult.CONTINUE;
                }

                @Override
                public FileVisitResult visitFile(Path file, BasicFileAttributes attrs)
                        throws IOException {
                    processFile(file, counter);
                    return FileVisitResult.CONTINUE;
                }

                @Override
                public FileVisitResult visitFileFailed(Path file, IOException exc) {
                    // permission denied, unreadable — skip silently
                    return FileVisitResult.CONTINUE;
                }
            });

        double abstractionDepth = counter.fileCount > 0
            ? (double) counter.interfaceCount / counter.fileCount : 0.0;

        return new Fingerprint(counter.interfaceCount, abstractionDepth, counter.injectionPoints,
                               counter.extensionSignatures, counter.fileCount, counter.spiPatterns);
    }

    private static void processFile(Path path, Counter c) {
        String name = path.getFileName().toString();

        // SPI: under META-INF/services, no Java/Kotlin extension check needed —
        // file sits directly under the services dir, its name is the FQN (may contain dots)
        if (isSpiFile(path)) {
            c.spiPatterns++;
            return;
        }

        // Only process .java and .kt source files
        if (!name.endsWith(".java") && !name.endsWith(".kt")) {
            return;
        }

        c.fileCount++;

        String text;
        try {
            text = Files.readString(path, StandardCharsets.UTF_8);
        } catch (Exception e) {
            return; // bad encoding or unreadable — skip silently
        }

        c.interfaceCount     += countMatches(INTERFACE_OR_ABSTRACT, text);
        c.injectionPoints    += countMatches(INJECTION, text);
        c.extensionSignatures += countMatches(EXTENDS_IMPLEMENTS, text);
    }

    /**
     * A file is an SPI descriptor if it lives directly under META-INF/services/
     * somewhere in the path. The filename itself may contain dots (it's a FQN).
     */
    private static boolean isSpiFile(Path path) {
        int nameCount = path.getNameCount();
        // Need at least: META-INF / services / <filename>  (3 levels from root)
        if (nameCount < 3) return false;
        for (int i = 0; i < nameCount - 2; i++) {
            if ("META-INF".equals(path.getName(i).toString()) &&
                "services".equals(path.getName(i + 1).toString())) {
                return true;
            }
        }
        return false;
    }

    private static int countMatches(Pattern p, String text) {
        int count = 0;
        var m = p.matcher(text);
        while (m.find()) count++;
        return count;
    }

    private static final class Counter {
        int interfaceCount;
        int injectionPoints;
        int extensionSignatures;
        int fileCount;
        int spiPatterns;
    }
}
