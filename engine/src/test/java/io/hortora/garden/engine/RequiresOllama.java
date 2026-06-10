package io.hortora.garden.engine;

import org.junit.jupiter.api.extension.ExtendWith;
import java.lang.annotation.*;

@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
@ExtendWith(OllamaAvailabilityCondition.class)
public @interface RequiresOllama {}
