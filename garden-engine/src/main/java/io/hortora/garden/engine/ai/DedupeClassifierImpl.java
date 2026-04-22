package io.hortora.garden.engine.ai;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.hortora.garden.engine.DedupeDecision;
import jakarta.enterprise.context.ApplicationScoped;

@ApplicationScoped
public class DedupeClassifierImpl implements DedupeClassifier {

    private static final ObjectMapper JSON = new ObjectMapper();

    @Override
    public DedupeDecision classify(String entryPair) {
        try {
            var node = JSON.readTree(entryPair);
            var cls = DedupeDecision.Classification.valueOf(
                    node.path("classification").asText("DISTINCT").toUpperCase());
            return new DedupeDecision(cls,
                    node.path("reasoning").asText(),
                    node.path("keep_id").isNull() ? null : node.path("keep_id").asText(),
                    node.path("preserve_from_other").isNull() ? null : node.path("preserve_from_other").asText());
        } catch (IllegalArgumentException e) {
            // Unknown classification value — safe default
            return new DedupeDecision(DedupeDecision.Classification.DISTINCT, "parse error: " + e.getMessage(), null, null);
        } catch (Exception e) {
            // Malformed JSON — safe default
            return new DedupeDecision(DedupeDecision.Classification.DISTINCT, "parse error: " + e.getMessage(), null, null);
        }
    }
}
