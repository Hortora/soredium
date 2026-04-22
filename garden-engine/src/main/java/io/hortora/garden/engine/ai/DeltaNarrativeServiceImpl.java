package io.hortora.garden.engine.ai;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.hortora.garden.engine.DeltaNarrative;
import jakarta.enterprise.context.ApplicationScoped;

@ApplicationScoped
public class DeltaNarrativeServiceImpl implements DeltaNarrativeService {

    private static final ObjectMapper JSON = new ObjectMapper();

    @Override
    public DeltaNarrative explainDelta(String diffContext) {
        try {
            var node = JSON.readTree(diffContext);
            return new DeltaNarrative(
                    node.path("decision").asText(),
                    node.path("pattern_name").asText(),
                    node.path("motivation").asText(),
                    node.path("introduced_at").asText()
            );
        } catch (Exception e) {
            throw new IllegalStateException("Failed to parse delta narrative response: " + e.getMessage(), e);
        }
    }
}
