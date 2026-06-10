package io.hortora.garden.engine;

public record KnownPattern(
    String name,
    Fingerprint signature
) {}
