package io.hortora.garden.engine;

import io.quarkus.test.junit.QuarkusTest;
import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.*;

/**
 * Real AI inference tests — automatically skipped when Ollama is not running.
 * To run: install Ollama, pull qwen3.6:35b-a3b, then run with -Dtest=RealAiSmokeTest.
 */
@QuarkusTest
class RealAiSmokeTest {

    // Uses real AI service, not MockReasoningService
    // Note: MockReasoningService @Alternative @Priority(1) will still intercept!
    // Real inference tests need a test profile that disables the mock.
    // For Phase 2, we just verify @RequiresOllama skips correctly.

    @Test
    @RequiresOllama
    void patternNamingSkipsWhenOllamaNotRunning() {
        // This test only runs when Ollama is available
        // If we reach this point, Ollama IS running — test the basic API
        fail("Ollama is running — implement real inference test here");
    }

    @Test
    @RequiresOllama
    void dedupeClassifierSkipsWhenOllamaNotRunning() {
        fail("Ollama is running — implement real inference test here");
    }

    @Test
    @RequiresOllama
    void entryMergeSkipsWhenOllamaNotRunning() {
        fail("Ollama is running — implement real inference test here");
    }
}
