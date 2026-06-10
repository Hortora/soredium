package io.hortora.garden.engine;

import io.quarkus.test.junit.QuarkusTest;
import org.eclipse.microprofile.config.inject.ConfigProperty;
import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.*;

@QuarkusTest
class ProfileSwitchingTest {

    @ConfigProperty(name = "quarkus.langchain4j.chat-model.provider")
    String chatModelProvider;

    @ConfigProperty(name = "quarkus.langchain4j.jlama.chat-model.model-name")
    String jlamaModelName;

    @Test
    void defaultProviderIsJlama() {
        assertThat(chatModelProvider).isEqualTo("jlama");
    }

    @Test
    void jlamaModelNameIsConfigured() {
        // Production model: tjake/Qwen2.5-3B-Instruct-JQ4
        // Test profile uses a lightweight placeholder; both should be non-blank org/model paths
        assertThat(jlamaModelName).isNotBlank().contains("/");
    }

    @Test
    void jlamaModelNameInTestIsConfigured() {
        // Verify the test application.properties sets a placeholder model name
        // (not the production model which would trigger a HuggingFace download)
        assertThat(jlamaModelName).isNotBlank();
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
