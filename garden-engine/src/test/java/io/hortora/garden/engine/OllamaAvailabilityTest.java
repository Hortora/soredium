package io.hortora.garden.engine;

import io.quarkus.test.junit.QuarkusTest;
import jakarta.inject.Inject;
import org.junit.jupiter.api.*;
import static org.assertj.core.api.Assertions.*;

@QuarkusTest
class OllamaAvailabilityTest {

    @Inject OllamaHealthChecker healthChecker;

    @Test
    void healthCheckerIsInjectable() {
        assertThat(healthChecker).isNotNull();
    }

    @Test
    void healthCheckerReturnsFalseWhenOllamaNotRunning() {
        // Ollama is not installed in this environment
        assertThat(healthChecker.isAvailable()).isFalse();
    }

    @Test
    void healthCheckerReturnsReasonWhenUnavailable() {
        var reason = healthChecker.unavailabilityReason();
        assertThat(reason).isNotBlank()
            .contains("localhost:11434");
    }
}
