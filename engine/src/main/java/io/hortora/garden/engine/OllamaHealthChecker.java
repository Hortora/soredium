package io.hortora.garden.engine;

import jakarta.enterprise.context.ApplicationScoped;
import org.eclipse.microprofile.config.inject.ConfigProperty;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;

@ApplicationScoped
public class OllamaHealthChecker {

    @ConfigProperty(name = "quarkus.langchain4j.ollama.base-url", defaultValue = "http://localhost:11434")
    String ollamaBaseUrl;

    private final HttpClient httpClient = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(2))
        .build();

    public boolean isAvailable() {
        try {
            var request = HttpRequest.newBuilder()
                .uri(URI.create(ollamaBaseUrl + "/api/tags"))
                .timeout(Duration.ofSeconds(2))
                .GET()
                .build();
            var response = httpClient.send(request, HttpResponse.BodyHandlers.discarding());
            return response.statusCode() == 200;
        } catch (Exception e) {
            return false;
        }
    }

    static final String CANONICAL_OLLAMA_URL = "localhost:11434";

    public String unavailabilityReason() {
        return "Ollama not reachable at " + CANONICAL_OLLAMA_URL +
               " (configured: " + ollamaBaseUrl + ")" +
               " — install Ollama and run: ollama pull qwen3.6:35b-a3b";
    }
}
