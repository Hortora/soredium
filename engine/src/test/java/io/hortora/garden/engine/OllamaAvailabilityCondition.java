package io.hortora.garden.engine;

import org.junit.jupiter.api.extension.*;

public class OllamaAvailabilityCondition implements ExecutionCondition {

    private static final String OLLAMA_URL = "http://localhost:11434";

    @Override
    public ConditionEvaluationResult evaluateExecutionCondition(ExtensionContext ctx) {
        // Cannot use CDI injection here — probe the default URL directly
        try {
            var http = java.net.http.HttpClient.newBuilder()
                .connectTimeout(java.time.Duration.ofSeconds(2))
                .build();
            var request = java.net.http.HttpRequest.newBuilder()
                .uri(java.net.URI.create(OLLAMA_URL + "/api/tags"))
                .timeout(java.time.Duration.ofSeconds(2))
                .GET().build();
            var response = http.send(request, java.net.http.HttpResponse.BodyHandlers.discarding());
            if (response.statusCode() == 200) {
                return ConditionEvaluationResult.enabled("Ollama is available at " + OLLAMA_URL);
            }
            return ConditionEvaluationResult.disabled(
                "Ollama returned " + response.statusCode() + " — install and start Ollama");
        } catch (Exception e) {
            return ConditionEvaluationResult.disabled(
                "Ollama not reachable at " + OLLAMA_URL + " — " + e.getMessage());
        }
    }
}
