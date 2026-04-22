package io.hortora.garden.engine;

import org.junit.jupiter.api.extension.*;

public class OllamaAvailabilityCondition implements ExecutionCondition {

    @Override
    public ConditionEvaluationResult evaluateExecutionCondition(ExtensionContext ctx) {
        try {
            var checker = new OllamaHealthChecker();
            // Use default URL since no config injection in JUnit extensions
            if (checker.isAvailable()) {
                return ConditionEvaluationResult.enabled("Ollama is available");
            }
            return ConditionEvaluationResult.disabled(checker.unavailabilityReason());
        } catch (Exception e) {
            return ConditionEvaluationResult.disabled("Ollama check failed: " + e.getMessage());
        }
    }
}
