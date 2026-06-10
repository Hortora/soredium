package io.hortora.garden.engine;

import io.hortora.garden.engine.ai.PatternNamingService;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.List;

import static org.assertj.core.api.Assertions.*;

/**
 * Real AI inference tests — automatically skipped when the JLama model is not cached locally.
 * Calls Ollama directly via HTTP (no Quarkus CDI) to avoid MockReasoningService interception.
 *
 * JLama model auto-downloads on first inference; tests skip if model not in ~/.jlama/
 * To cache: run any inference once (JLama downloads automatically on first use).
 *
 * These tests are excluded from the default mvn test run (they require real LLM
 * inference which is too slow for CI). Run manually when validating AI integration:
 *   mvn test -Dgroups=ai-smoke -Dtest=RealAiSmokeTest
 */
@Tag("ai-smoke")
class RealAiSmokeTest {

    private static final String OLLAMA_URL = "http://localhost:11434";
    // Use fastest available model for framework smoke test.
    // Override with -Dollama.smoke.model=qwen3.6:35b-a3b for quality testing.
    private static final String MODEL = System.getProperty("ollama.smoke.model", "llama3.2:latest");

    private final HttpClient http = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(5))
        .build();

    @Test
    @RequiresJlamaModel
    void qwenRespondsToPatternNamingPrompt() throws Exception {
        var context = PatternNamingService.buildClusterContext(
            List.of("quarkus", "hibernate-orm"),
            List.of(
                new Fingerprint(5457, 0.253, 8696, 10106, 21570, 192),
                new Fingerprint(3658, 0.216, 34, 9569, 16924, 41)
            )
        );

        var prompt = """
            You are an expert in JVM framework architecture. Given a cluster of structurally
            similar projects and their fingerprints, identify the shared architectural pattern.
            Respond as JSON only:
            {"name":"...","description":"...","structural_signal":"...","why_it_exists":"..."}
            """ + context;

        var response = callOllama(prompt);

        assertThat(response.statusCode()).isEqualTo(200);
        var body = response.body();
        assertThat(body).contains("response");

        // Extract the model's response text
        var responseText = extractResponseField(body);
        assertThat(responseText).isNotBlank();
        assertThat(responseText.length()).isGreaterThan(20);

        // Response should mention something about the structural difference
        // (CDI/injection vs service-loader architecture)
        System.out.println("=== Pattern Naming Response ===\n" + responseText);
    }

    @Test
    @RequiresJlamaModel
    void qwenClassifiesDuplicateEntriesCorrectly() throws Exception {
        var entries = TestFixtures.duplicateEntryPair();
        var prompt = """
            You are reviewing two knowledge garden entries for duplication.
            Classify as DISTINCT, RELATED, or DUPLICATE.
            Respond as JSON only:
            {"classification":"DISTINCT|RELATED|DUPLICATE","reasoning":"...","keep_id":null,"preserve_from_other":null}

            Entry 1:
            """ + entries[0] + "\n\nEntry 2:\n" + entries[1];

        var response = callOllama(prompt);
        assertThat(response.statusCode()).isEqualTo(200);

        var responseText = extractResponseField(response.body());
        assertThat(responseText).isNotBlank();

        // Should classify as DUPLICATE — both entries describe the same CDI null issue
        System.out.println("=== Dedup Classification Response ===\n" + responseText);
        assertThat(responseText.toUpperCase()).contains("DUPLICATE");
    }

    @Test
    @RequiresJlamaModel
    void qwenClassifiesDistinctEntriesCorrectly() throws Exception {
        var entries = TestFixtures.distinctEntryPair();
        var prompt = """
            You are reviewing two knowledge garden entries for duplication.
            Classify as DISTINCT, RELATED, or DUPLICATE.
            Respond as JSON only:
            {"classification":"DISTINCT|RELATED|DUPLICATE","reasoning":"...","keep_id":null,"preserve_from_other":null}

            Entry 1:
            """ + entries[0] + "\n\nEntry 2:\n" + entries[1];

        var response = callOllama(prompt);
        assertThat(response.statusCode()).isEqualTo(200);

        var responseText = extractResponseField(response.body());
        assertThat(responseText).isNotBlank();

        System.out.println("=== Distinct Classification Response ===\n" + responseText);
        // Maven -q vs Git symlinks — should be DISTINCT
        assertThat(responseText.toUpperCase()).contains("DISTINCT");
    }

    private HttpResponse<String> callOllama(String prompt) throws Exception {
        var body = """
            {"model":"%s","prompt":%s,"stream":false,"options":{"temperature":0.2}}
            """.formatted(MODEL, jsonString(prompt));

        return http.send(
            HttpRequest.newBuilder()
                .uri(URI.create(OLLAMA_URL + "/api/generate"))
                .timeout(Duration.ofMinutes(5))
                .POST(HttpRequest.BodyPublishers.ofString(body))
                .header("Content-Type", "application/json")
                .build(),
            HttpResponse.BodyHandlers.ofString()
        );
    }

    private String jsonString(String text) {
        // Minimal JSON string escaping
        return "\"" + text.replace("\\", "\\\\").replace("\"", "\\\"")
                          .replace("\n", "\\n").replace("\r", "\\r") + "\"";
    }

    private String extractResponseField(String json) {
        // Extract "response":"..." from Ollama's generate response
        var marker = "\"response\":\"";
        var start = json.indexOf(marker);
        if (start < 0) return json;
        start += marker.length();
        var end = json.indexOf("\",\"", start);
        if (end < 0) end = json.lastIndexOf("\"");
        return json.substring(start, end)
                   .replace("\\n", "\n").replace("\\\"", "\"");
    }
}
