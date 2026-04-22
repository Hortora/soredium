package io.hortora.garden.engine;

import io.hortora.garden.engine.ai.*;
import io.quarkus.test.junit.QuarkusTest;
import jakarta.inject.Inject;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

@QuarkusTest
class LangchainWiringTest {

    @Inject PatternNamingService namingService;
    @Inject DedupeClassifier classifier;
    @Inject EntryMergeService mergeService;
    @Inject DeltaNarrativeService narrativeService;
    @Inject MockReasoningService mock;

    @Test
    void mockReasoningServiceResolvesAsPatternNamingService() {
        assertThat(namingService).isNotNull();
        var result = namingService.namePattern("any context");
        assertThat(result.name()).isEqualTo("mock-pattern");
    }

    @Test
    void allAiServicesInjectableWithMock() {
        assertThat(classifier.classify("any pair").classification())
            .isEqualTo(DedupeDecision.Classification.DISTINCT);
        assertThat(mergeService.mergeEntries("any pair")).contains("---");
        assertThat(narrativeService.explainDelta("any diff").decision()).isNotBlank();
    }

    @Test
    void mockReasoningServiceConfigurableValues() {
        mock.willReturnPattern(new PatternCandidate("custom", "d", "s", "w"));
        assertThat(namingService.namePattern("ctx").name()).isEqualTo("custom");
        // Reset to default
        mock.willReturnPattern(new PatternCandidate("mock-pattern", "mock", "mock", "mock"));
    }
}
