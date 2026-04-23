package io.hortora.garden.engine;

/**
 * Result of running one task through one model for QE matrix comparison.
 */
public record ModelComparisonResult(
    String modelName,
    String taskType,
    String modelOutput,
    String goldStandardOutput,
    boolean jsonParseSuccess,
    boolean agreesWithGoldStandard,
    long inferenceMs
) {}
