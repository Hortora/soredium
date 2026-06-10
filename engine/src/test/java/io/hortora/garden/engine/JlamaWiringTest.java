package io.hortora.garden.engine;

import io.hortora.garden.engine.ai.PatternNamingService;
import io.quarkus.test.junit.QuarkusTest;
import jakarta.inject.Inject;
import org.eclipse.microprofile.config.inject.ConfigProperty;
import org.junit.jupiter.api.Test;
import java.nio.file.Files;
import java.nio.file.Path;
import static org.assertj.core.api.Assertions.*;

@QuarkusTest
class JlamaWiringTest {

    @ConfigProperty(name = "quarkus.langchain4j.chat-model.provider")
    String provider;

    @ConfigProperty(name = "quarkus.langchain4j.jlama.chat-model.model-name")
    String modelName;

    @Inject PatternNamingService service;
    @Inject MockReasoningService mock;

    @Test
    void jlamaProviderIsConfiguredAsDefault() {
        assertThat(provider).isEqualTo("jlama");
    }

    @Test
    void jlamaModelNameIsConfigured() {
        // In tests, application.properties uses a lightweight placeholder model.
        // Assert the property is set to a valid JLama model path (org/ModelName format).
        assertThat(modelName).isNotBlank().contains("/");
    }

    @Test
    void mockReasoningServiceStillInterceptsInTests() {
        mock.willReturnPattern(new PatternCandidate("JLama-test", "d", "s", "w"));
        assertThat(service.namePattern("ctx").name()).isEqualTo("JLama-test");
        // Reset
        mock.willReturnPattern(new PatternCandidate("mock-pattern", "mock", "mock", "mock"));
    }

    @Test
    void ollamaProfileConfigFileExists() throws Exception {
        var path = Path.of("src/main/resources/application-ollama.properties");
        assertThat(path).exists();
        assertThat(Files.readString(path)).contains("ollama");
    }
}
