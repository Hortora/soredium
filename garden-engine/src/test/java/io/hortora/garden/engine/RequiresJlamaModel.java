package io.hortora.garden.engine;

import org.junit.jupiter.api.extension.ExtendWith;
import java.lang.annotation.*;

@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
@ExtendWith(JlamaModelAvailabilityCondition.class)
public @interface RequiresJlamaModel {
    /** HuggingFace model name, e.g. "tjake/Qwen2.5-3B-Instruct-JQ4" */
    String value() default "tjake/Qwen2.5-3B-Instruct-JQ4";
}
