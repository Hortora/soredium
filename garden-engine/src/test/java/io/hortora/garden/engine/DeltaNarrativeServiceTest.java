package io.hortora.garden.engine;

import io.hortora.garden.engine.ai.DeltaNarrativeServiceImpl;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class DeltaNarrativeServiceTest {

    private DeltaNarrativeServiceImpl service;

    @BeforeEach
    void setUp() {
        service = new DeltaNarrativeServiceImpl();
    }

    @Test
    void validJsonResponseParsedIntoDeltaNarrative() {
        var json = """
                {"decision":"added evaluator abstraction","pattern_name":"Pluggable Evaluator","motivation":"runtime extensibility","introduced_at":"v2.0"}
                """;
        var result = service.explainDelta(json);
        assertThat(result.decision()).isEqualTo("added evaluator abstraction");
        assertThat(result.patternName()).isEqualTo("Pluggable Evaluator");
        assertThat(result.motivation()).isEqualTo("runtime extensibility");
        assertThat(result.introducedAt()).isEqualTo("v2.0");
    }

    @Test
    void malformedJsonThrowsDescriptiveException() {
        assertThatThrownBy(() -> service.explainDelta("{{invalid"))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("parse");
    }

    @Test
    void introducedAtMatchesContextPassedIn() {
        var json = """
                {"decision":"d","pattern_name":"p","motivation":"m","introduced_at":"v3.5"}
                """;
        assertThat(service.explainDelta(json).introducedAt()).isEqualTo("v3.5");
    }
}
