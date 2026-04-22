package io.hortora.garden.engine.ai;

import dev.langchain4j.service.SystemMessage;
import dev.langchain4j.service.UserMessage;
import io.hortora.garden.engine.Fingerprint;
import io.hortora.garden.engine.PatternCandidate;
import io.quarkiverse.langchain4j.RegisterAiService;

import java.util.List;

@RegisterAiService
public interface PatternNamingService {

    @SystemMessage("""
        You are an expert in JVM framework architecture. Given a cluster of structurally
        similar projects and their fingerprints, identify the shared architectural pattern.
        Respond as JSON only:
        {"name":"...","description":"...","structural_signal":"...","why_it_exists":"..."}
        """)
    PatternCandidate namePattern(@UserMessage String clusterContext);

    static String buildClusterContext(List<String> names, List<Fingerprint> fingerprints) {
        var sb = new StringBuilder("Projects in this cluster:\n");
        for (int i = 0; i < names.size(); i++) {
            var fp = fingerprints.get(i);
            sb.append("- ").append(names.get(i))
              .append(": interfaces=").append(fp.interfaceCount())
              .append(", injections=").append(fp.injectionPoints())
              .append(", spi=").append(fp.spiPatterns()).append("\n");
        }
        return sb.toString();
    }
}
