package io.hortora.garden.engine;

import io.hortora.garden.engine.ai.DedupeClassifier;
import io.quarkus.test.junit.QuarkusTest;
import jakarta.inject.Inject;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

@QuarkusTest
class DedupeClassifierTest {

    @Inject DedupeClassifier classifier;
    @Inject MockReasoningService mock;

    @Test
    void defaultMockDecisionIsDistinct() {
        var result = classifier.classify("any entry pair");
        assertThat(result.classification()).isEqualTo(DedupeDecision.Classification.DISTINCT);
    }

    @Test
    void configuringRelatedDecisionIsReflected() {
        mock.willReturnDecision(new DedupeDecision(DedupeDecision.Classification.RELATED, "same area", null, null));
        assertThat(classifier.classify("pair").classification()).isEqualTo(DedupeDecision.Classification.RELATED);
        mock.willReturnDecision(new DedupeDecision(DedupeDecision.Classification.DISTINCT, "mock", null, null));
    }

    @Test
    void configuringDuplicateDecisionWithKeepIdIsReflected() {
        mock.willReturnDecision(new DedupeDecision(DedupeDecision.Classification.DUPLICATE, "same fix", "GE-001", "alternative approach"));
        var result = classifier.classify("pair");
        assertThat(result.classification()).isEqualTo(DedupeDecision.Classification.DUPLICATE);
        assertThat(result.keepId()).isEqualTo("GE-001");
        assertThat(result.preserveFromOther()).isEqualTo("alternative approach");
        mock.willReturnDecision(new DedupeDecision(DedupeDecision.Classification.DISTINCT, "mock", null, null));
    }

    @Test
    void mockReasoningIsNotNull() {
        assertThat(classifier.classify("any")).isNotNull();
    }

    @Test
    void reasoningFieldIsAvailableOnDecision() {
        mock.willReturnDecision(new DedupeDecision(DedupeDecision.Classification.DISTINCT, "different topics", null, null));
        assertThat(classifier.classify("pair").reasoning()).isEqualTo("different topics");
        mock.willReturnDecision(new DedupeDecision(DedupeDecision.Classification.DISTINCT, "mock", null, null));
    }
}
