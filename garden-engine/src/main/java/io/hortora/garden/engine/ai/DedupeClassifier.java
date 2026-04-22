package io.hortora.garden.engine.ai;

import io.hortora.garden.engine.DedupeDecision;

public interface DedupeClassifier {
    DedupeDecision classify(String entryPair);
}
