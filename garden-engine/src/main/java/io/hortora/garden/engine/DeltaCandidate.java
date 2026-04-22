package io.hortora.garden.engine;

public record DeltaCandidate(
    String file,
    String kind,
    String introducedAt,
    String commit,
    String author,
    String date
) {}
