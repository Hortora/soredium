package io.hortora.garden.engine;

public record DedupeDecision(
    Classification classification,
    String reasoning,
    String keepId,
    String preserveFromOther
) {
    public enum Classification {
        DISTINCT,
        RELATED,
        DUPLICATE
    }
}
