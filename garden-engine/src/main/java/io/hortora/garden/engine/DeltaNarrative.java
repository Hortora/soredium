package io.hortora.garden.engine;

public record DeltaNarrative(
    String decision,
    String patternName,
    String motivation,
    String introducedAt
) {}
