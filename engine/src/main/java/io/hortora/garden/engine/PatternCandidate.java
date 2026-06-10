package io.hortora.garden.engine;

public record PatternCandidate(
    String name,
    String description,
    String structuralSignal,
    String whyItExists
) {}
