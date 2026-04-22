package io.hortora.garden.engine;

import io.hortora.garden.engine.ai.DedupeClassifierImpl;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class DedupeClassifierTest {

    private DedupeClassifierImpl classifier;

    @BeforeEach
    void setUp() {
        classifier = new DedupeClassifierImpl();
    }

    @Test
    void distinctClassificationParsedCorrectly() {
        var json = """
                {"classification":"DISTINCT","reasoning":"different topics","keep_id":null,"preserve_from_other":null}
                """;
        var result = classifier.classify(json);
        assertThat(result.classification()).isEqualTo(DedupeDecision.Classification.DISTINCT);
        assertThat(result.reasoning()).isEqualTo("different topics");
        assertThat(result.keepId()).isNull();
        assertThat(result.preserveFromOther()).isNull();
    }

    @Test
    void relatedClassificationParsedCorrectly() {
        var json = """
                {"classification":"RELATED","reasoning":"same area","keep_id":null,"preserve_from_other":null}
                """;
        assertThat(classifier.classify(json).classification()).isEqualTo(DedupeDecision.Classification.RELATED);
    }

    @Test
    void duplicateClassificationWithKeepIdParsedCorrectly() {
        var json = """
                {"classification":"DUPLICATE","reasoning":"same fix","keep_id":"GE-001","preserve_from_other":"alternative approach"}
                """;
        var result = classifier.classify(json);
        assertThat(result.classification()).isEqualTo(DedupeDecision.Classification.DUPLICATE);
        assertThat(result.keepId()).isEqualTo("GE-001");
        assertThat(result.preserveFromOther()).isEqualTo("alternative approach");
    }

    @Test
    void malformedJsonDefaultsToDistinct() {
        var result = classifier.classify("{broken json{{");
        assertThat(result.classification()).isEqualTo(DedupeDecision.Classification.DISTINCT);
    }

    @Test
    void unknownClassificationValueDefaultsToDistinct() {
        var json = """
                {"classification":"MAYBE","reasoning":"unsure","keep_id":null,"preserve_from_other":null}
                """;
        var result = classifier.classify(json);
        assertThat(result.classification()).isEqualTo(DedupeDecision.Classification.DISTINCT);
    }
}
