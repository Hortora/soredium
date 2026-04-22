package io.hortora.garden.engine;

import jakarta.enterprise.context.ApplicationScoped;
import java.nio.file.Path;
import java.util.*;
import java.util.regex.Pattern;

@ApplicationScoped
public class DeltaAnalysis {

    private static final Pattern RE_INTERFACE = Pattern.compile("\\binterface\\s+\\w+");
    private static final Pattern RE_ABSTRACT  = Pattern.compile("\\babstract\\s+class\\s+\\w+");
    private static final Set<String> SOURCE_EXTS = Set.of(".java", ".kt");

    public List<DeltaCandidate> analyze(Path repo, String fromRef, String toRef) {
        if (fromRef.equals(toRef)) return List.of();
        if (isShallow(repo)) return List.of();  // fix #37

        var addedFiles = getAddedFiles(repo, fromRef, toRef);
        var result = new ArrayList<DeltaCandidate>();
        for (var file : addedFiles) {
            var ext = getExtension(file);
            if (!SOURCE_EXTS.contains(ext)) continue;
            var content = showFile(repo, toRef, file);
            if (content.isBlank()) continue;
            String kind = null;
            if (RE_INTERFACE.matcher(content).find()) kind = "interface";
            else if (RE_ABSTRACT.matcher(content).find()) kind = "abstract_class";
            if (kind == null) continue;
            var blame = getBlame(repo, toRef, file);
            result.add(new DeltaCandidate(file, kind, toRef, blame[0], blame[1], blame[2]));
        }
        return result;
    }

    public List<String> getMajorVersionTags(Path repo) {
        return git(repo, "tag", "--sort=version:refname").lines()
            .filter(t -> !t.isBlank())
            .toList();
    }

    private boolean isShallow(Path repo) {
        return git(repo, "rev-parse", "--is-shallow-repository").strip().equals("true");
    }

    private List<String> getAddedFiles(Path repo, String from, String to) {
        return git(repo, "diff", "--name-status", from, to).lines()
            .filter(l -> l.startsWith("A\t"))
            .map(l -> l.substring(2).strip())
            .toList();
    }

    private String showFile(Path repo, String ref, String file) {
        try { return git(repo, "show", ref + ":" + file); }
        catch (RuntimeException e) { return ""; }
    }

    private String[] getBlame(Path repo, String ref, String file) {
        var out = git(repo, "log", "-1", "--format=%H|%ae|%ad", "--date=short",
                      ref, "--", file).strip();
        var parts = out.split("\\|", -1);
        if (parts.length < 3) return new String[]{"unknown", "unknown", "unknown"};
        return new String[]{
            parts[0].length() >= 7 ? parts[0].substring(0, 7) : parts[0],
            parts[1],
            parts[2]
        };
    }

    private String getExtension(String file) {
        int dot = file.lastIndexOf('.');
        return dot < 0 ? "" : file.substring(dot);
    }

    private String git(Path repo, String... args) {
        try {
            var cmd = new ArrayList<String>();
            cmd.add("git");
            cmd.addAll(List.of(args));
            var pb = new ProcessBuilder(cmd).directory(repo.toFile()).redirectErrorStream(true);
            var proc = pb.start();
            var out = new String(proc.getInputStream().readAllBytes());
            proc.waitFor();
            return out;
        } catch (Exception e) {
            throw new RuntimeException("git failed: " + e.getMessage(), e);
        }
    }
}
