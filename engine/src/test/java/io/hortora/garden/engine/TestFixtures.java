package io.hortora.garden.engine;

import java.io.IOException;
import java.nio.file.*;
import java.util.List;

public final class TestFixtures {

    private TestFixtures() {}

    /** Write a file relative to root, creating parent dirs. */
    public static void write(Path root, String rel, String content) throws IOException {
        Path target = root.resolve(rel);
        Files.createDirectories(target.getParent());
        Files.writeString(target, content);
    }

    /** A Java source tree with N interfaces and M CDI beans. */
    public static void javaProjectWithInterfaces(Path root, int interfaces, int beans) throws IOException {
        for (int i = 0; i < interfaces; i++) {
            write(root, "src/Iface" + i + ".java", "public interface Iface" + i + " {}");
        }
        for (int i = 0; i < beans; i++) {
            write(root, "src/Bean" + i + ".java",
                  "@ApplicationScoped\npublic class Bean" + i + " {\n  @Inject Iface0 dep;\n}");
        }
    }

    /** Create a git repo with v1.0 (plain class) and v2.0 (adds interface + abstract class). */
    public static Path gitRepoWithTwoVersions(Path root) throws IOException, InterruptedException {
        Path repo = root.resolve("repo");
        Files.createDirectories(repo.resolve("src"));

        git(repo, "init");
        git(repo, "config", "user.email", "test@example.com");
        git(repo, "config", "user.name", "Test");

        // v1.0
        write(repo, "src/Service.java", "public class Service {}");
        git(repo, "add", ".");
        git(repo, "commit", "-m", "initial");
        git(repo, "tag", "v1.0");

        // v2.0
        write(repo, "src/Evaluator.java", "public interface Evaluator { void eval(); }");
        write(repo, "src/AbstractBase.java", "public abstract class AbstractBase {}");
        git(repo, "add", ".");
        git(repo, "commit", "-m", "add abstractions");
        git(repo, "tag", "v2.0");

        return repo;
    }

    private static void git(Path repo, String... args) throws IOException, InterruptedException {
        var cmd = new java.util.ArrayList<String>();
        cmd.add("git");
        cmd.addAll(List.of(args));
        var pb = new ProcessBuilder(cmd).directory(repo.toFile()).inheritIO();
        int exit = pb.start().waitFor();
        if (exit != 0) throw new RuntimeException("git " + String.join(" ", args) + " failed: " + exit);
    }

    /** Minimal valid projects.yaml string for N named projects. */
    public static String projectsYaml(String... names) {
        var sb = new StringBuilder("projects:\n");
        for (var name : names) {
            sb.append("- project: ").append(name).append("\n")
              .append("  url: https://github.com/example/").append(name).append("\n")
              .append("  domain: jvm\n")
              .append("  primary_language: java\n")
              .append("  frameworks: []\n")
              .append("  last_processed_commit: null\n")
              .append("  notable_contributors: []\n");
        }
        return sb.toString();
    }

    /** Two entries that cover the same concept — semantic duplicates. */
    public static String[] duplicateEntryPair() {
        return new String[]{
            "---\nid: GE-20260101-aaaaaa\ntitle: \"@Inject null in @QuarkusTest\"\nscore: 10\n---\n## Symptom\nCDI bean is null in test.",
            "---\nid: GE-20260101-bbbbbb\ntitle: \"CDI singleton null during Quarkus test\"\nscore: 9\n---\n## Symptom\nBean injected via CDI returns null in @QuarkusTest."
        };
    }

    /** Two entries on related but distinct topics. */
    public static String[] relatedEntryPair() {
        return new String[]{
            "---\nid: GE-20260101-cccccc\ntitle: \"@PostConstruct order in Quarkus\"\nscore: 10\n---\n## Context\nBean lifecycle init order.",
            "---\nid: GE-20260101-dddddd\ntitle: \"StartupEvent fires after all PostConstruct\"\nscore: 11\n---\n## Context\nStartupEvent ordering."
        };
    }

    /** Two entries with no semantic overlap. */
    public static String[] distinctEntryPair() {
        return new String[]{
            "---\nid: GE-20260101-eeeeee\ntitle: \"Maven -q suppresses compiler errors\"\nscore: 10\n---\n## Symptom\nNo output on compile failure.",
            "---\nid: GE-20260101-ffffff\ntitle: \"Git symlink traversal in Files.walk\"\nscore: 9\n---\n## Symptom\nInfinite loop on symlinked dirs."
        };
    }
}
