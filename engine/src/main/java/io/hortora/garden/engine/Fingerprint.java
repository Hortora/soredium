package io.hortora.garden.engine;

public record Fingerprint(
    int interfaceCount,
    double abstractionDepth,
    int injectionPoints,
    int extensionSignatures,
    int fileCount,
    int spiPatterns
) {}
