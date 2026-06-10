package io.hortora.garden.engine;

import io.hortora.garden.engine.ai.PatternNamingService;
import io.quarkus.test.junit.QuarkusTest;
import jakarta.inject.Inject;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

@QuarkusTest
class PatternNamingServiceTest {

    @Inject PatternNamingService service;
    @Inject MockReasoningService mock;

    @Test
    void validPatternCandidateReturnedFromMock() {
        mock.willReturnPattern(new PatternCandidate("CDI Strategy", "desc", "signal", "why"));
        assertThat(service.namePattern("any context").name()).isEqualTo("CDI Strategy");
    }

    @Test
    void nullClusterContextReturnsMockDefault() {
        // MockReasoningService ignores context and returns configured response
        var result = service.namePattern(null);
        assertThat(result).isNotNull(); // mock always returns something
    }

    @Test
    void blankContextReturnsMockDefault() {
        assertThat(service.namePattern("")).isNotNull();
    }

    @Test
    void promptBuilderIncludesProjectNamesAndFingerprints() {
        var ctx = PatternNamingService.buildClusterContext(
            List.of("quarkus", "micronaut"),
            List.of(new Fingerprint(100, 0.2, 80, 90, 500, 10),
                    new Fingerprint(80, 0.18, 70, 85, 450, 8))
        );
        assertThat(ctx).contains("quarkus").contains("micronaut");
        assertThat(ctx).contains("100"); // interface count
    }

    @Test
    void configuredPatternNameIsReturned() {
        mock.willReturnPattern(new PatternCandidate("Custom Pattern", "d", "s", "w"));
        assertThat(service.namePattern("ctx").name()).isEqualTo("Custom Pattern");
        mock.willReturnPattern(new PatternCandidate("mock-pattern", "mock", "mock", "mock"));
    }
}
