package io.hortora.garden.engine;

public record HarvestResult(
    DedupeDecision.Classification classification,
    String reasoning,
    String mergedEntry  // null unless DUPLICATE
) {}
