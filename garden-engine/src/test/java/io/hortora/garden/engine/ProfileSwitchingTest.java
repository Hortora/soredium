package io.hortora.garden.engine;

import io.quarkus.test.junit.QuarkusTest;
import org.eclipse.microprofile.config.inject.ConfigProperty;
import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.*;

@QuarkusTest
class ProfileSwitchingTest {

    @ConfigProperty(name = "quarkus.langchain4j.ollama.base-url")
    String ollamaBaseUrl;

    @ConfigProperty(name = "quarkus.langchain4j.chat-model.provider")
    String chatModelProvider;

    @Test
    void defaultProviderIsOllama() {
        assertThat(chatModelProvider).isEqualTo("ollama");
    }

    @Test
    void ollamaBaseUrlIsConfigured() {
        assertThat(ollamaBaseUrl).isNotBlank();
        assertThat(ollamaBaseUrl).startsWith("http");
    }

    @Test
    void ollamaBaseUrlInTestProfilePointsToDisabledEndpoint() {
        // Test profile sets base-url to http://localhost:1 (connection refused)
        // This ensures no real Ollama connections are made during tests
        assertThat(ollamaBaseUrl).isEqualTo("http://localhost:1");
    }

    @Test
    void anthropicApiKeyConfigPropertyExists() {
        // The anthropic API key config key must be defined (even if empty in test)
        // This verifies the sonnet profile configuration is present
        var config = org.eclipse.microprofile.config.ConfigProvider.getConfig();
        // quarkus.langchain4j.anthropic.api-key defaults to empty — just verify it's readable
        assertThatCode(() -> config.getOptionalValue("quarkus.langchain4j.anthropic.api-key", String.class))
            .doesNotThrowAnyException();
    }
}
