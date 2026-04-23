package io.hortora.garden.engine;

import org.junit.jupiter.api.extension.*;
import java.util.Optional;

public class JlamaModelAvailabilityCondition implements ExecutionCondition {

    @Override
    public ConditionEvaluationResult evaluateExecutionCondition(ExtensionContext ctx) {
        var annotation = ctx.getElement()
            .flatMap(e -> Optional.ofNullable(e.getAnnotation(RequiresJlamaModel.class)))
            .orElse(null);
        var modelName = annotation != null ? annotation.value()
            : "tjake/Qwen2.5-3B-Instruct-JQ4";
        var checker = new JlamaModelChecker();
        if (checker.isModelCached(modelName)) {
            return ConditionEvaluationResult.enabled("JLama model cached: " + modelName);
        }
        return ConditionEvaluationResult.disabled(
            "JLama model not cached: " + modelName +
            " — download first: ollama is not needed; JLama downloads automatically on first inference");
    }
}
