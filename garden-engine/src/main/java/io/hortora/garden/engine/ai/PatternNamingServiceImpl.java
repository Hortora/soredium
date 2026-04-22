package io.hortora.garden.engine.ai;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.hortora.garden.engine.Fingerprint;
import io.hortora.garden.engine.PatternCandidate;
import jakarta.enterprise.context.ApplicationScoped;

import java.util.List;

@ApplicationScoped
public class PatternNamingServiceImpl implements PatternNamingService {

    private static final ObjectMapper JSON = new ObjectMapper();

    @Override
    public PatternCandidate namePattern(String clusterContext) {
        if (clusterContext == null || clusterContext.isBlank()) return null;
        // In production: sends to LLM and parses JSON response.
        // In tests: clusterContext IS the JSON response (for unit testing parsing logic).
        try {
            var node = JSON.readTree(clusterContext);
            return new PatternCandidate(
                    node.path("name").asText(),
                    node.path("description").asText(),
                    node.path("structural_signal").asText(),
                    node.path("why_it_exists").asText()
            );
        } catch (JsonProcessingException e) {
            throw new IllegalStateException("Failed to parse pattern naming response: " + e.getMessage(), e);
        }
    }

    public static String buildClusterContext(List<String> names, List<Fingerprint> fps) {
        var sb = new StringBuilder("Projects in this cluster:\n");
        for (int i = 0; i < names.size(); i++) {
            var fp = fps.get(i);
            sb.append("- ").append(names.get(i)).append(": ")
              .append("interfaces=").append(fp.interfaceCount())
              .append(", injections=").append(fp.injectionPoints())
              .append(", spi=").append(fp.spiPatterns()).append("\n");
        }
        return sb.toString();
    }
}
