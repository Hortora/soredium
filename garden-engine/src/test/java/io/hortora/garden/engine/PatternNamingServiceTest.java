package io.hortora.garden.engine;

import io.hortora.garden.engine.ai.PatternNamingServiceImpl;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class PatternNamingServiceTest {

    private PatternNamingServiceImpl service;

    @BeforeEach
    void setUp() {
        service = new PatternNamingServiceImpl();
    }

    @Test
    void validJsonResponseParsedIntoPatternCandidate() {
        var json = """
                {"name":"CDI Strategy Registry","description":"desc","structural_signal":"signal","why_it_exists":"why"}
                """;
        var result = service.namePattern(json);
        assertThat(result.name()).isEqualTo("CDI Strategy Registry");
        assertThat(result.description()).isEqualTo("desc");
        assertThat(result.structuralSignal()).isEqualTo("signal");
        assertThat(result.whyItExists()).isEqualTo("why");
    }

    @Test
    void nullClusterContextReturnsNull() {
        assertThat(service.namePattern(null)).isNull();
    }

    @Test
    void blankClusterContextReturnsNull() {
        assertThat(service.namePattern("  ")).isNull();
    }

    @Test
    void malformedJsonThrowsDescriptiveException() {
        assertThatThrownBy(() -> service.namePattern("{not valid json"))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("parse");
    }

    @Test
    void promptIncludesProjectNamesAndFingerprints() {
        var fp1 = new Fingerprint(5, 1.2, 8, 2, 10, 3);
        var fp2 = new Fingerprint(3, 0.9, 4, 1, 7, 1);

        var ctx = PatternNamingServiceImpl.buildClusterContext(
                List.of("quarkus", "micronaut"),
                List.of(fp1, fp2)
        );

        assertThat(ctx).contains("quarkus").contains("micronaut");
        assertThat(ctx).contains(String.valueOf(fp1.injectionPoints()));
        assertThat(ctx).contains(String.valueOf(fp2.injectionPoints()));
        assertThat(ctx).contains(String.valueOf(fp1.interfaceCount()));
        assertThat(ctx).contains(String.valueOf(fp1.spiPatterns()));
    }
}
