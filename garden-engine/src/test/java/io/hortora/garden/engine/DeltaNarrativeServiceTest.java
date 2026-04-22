package io.hortora.garden.engine;

import io.hortora.garden.engine.ai.DeltaNarrativeService;
import io.quarkus.test.junit.QuarkusTest;
import jakarta.inject.Inject;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

@QuarkusTest
class DeltaNarrativeServiceTest {

    @Inject DeltaNarrativeService service;
    @Inject MockReasoningService mock;

    @Test
    void defaultMockNarrativeHasNonBlankDecision() {
        var result = service.explainDelta("any diff");
        assertThat(result.decision()).isNotBlank();
    }

    @Test
    void configuringNarrativeIsReflected() {
        mock.willReturnNarrative(new DeltaNarrative("added evaluator abstraction", "Pluggable Evaluator", "runtime extensibility", "v2.0"));
        var result = service.explainDelta("diff context");
        assertThat(result.decision()).isEqualTo("added evaluator abstraction");
        assertThat(result.patternName()).isEqualTo("Pluggable Evaluator");
        assertThat(result.motivation()).isEqualTo("runtime extensibility");
        assertThat(result.introducedAt()).isEqualTo("v2.0");
        mock.willReturnNarrative(new DeltaNarrative("mock-decision", "mock", "mock", "v2.0"));
    }

    @Test
    void introducedAtIsAvailableOnNarrative() {
        mock.willReturnNarrative(new DeltaNarrative("d", "p", "m", "v3.5"));
        assertThat(service.explainDelta("diff").introducedAt()).isEqualTo("v3.5");
        mock.willReturnNarrative(new DeltaNarrative("mock-decision", "mock", "mock", "v2.0"));
    }
}
