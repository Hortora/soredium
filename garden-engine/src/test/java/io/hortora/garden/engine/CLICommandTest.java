package io.hortora.garden.engine;

import io.quarkus.test.junit.main.Launch;
import io.quarkus.test.junit.main.LaunchResult;
import io.quarkus.test.junit.main.QuarkusMainTest;
import org.junit.jupiter.api.Disabled;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

@QuarkusMainTest
class CLICommandTest {

    // --- mine command ---

    @Test
    @Launch({"mine", "--all"})
    void mineAllRunsWithoutError(LaunchResult result) {
        assertThat(result.exitCode()).isEqualTo(0);
        assertThat(result.getOutput()).contains("mine");
    }

    @Test
    @Launch(value = {"mine", "--project", "unknown-project-that-does-not-exist"}, exitCode = 1)
    void mineUnknownProjectExitsOne(LaunchResult result) {
        assertThat(result.getErrorOutput()).contains("not found");
    }

    @Test
    @Launch({"mine", "--all"})
    void mineAllProducesOutput(LaunchResult result) {
        assertThat(result.exitCode()).isEqualTo(0);
        assertThat(result.getOutput()).isNotBlank();
    }

    @Test
    @Launch({"mine", "--help"})
    void mineHelpShowsUsage(LaunchResult result) {
        assertThat(result.getOutput()).contains("mine");
    }

    // --- harvest command ---

    @Test
    @Launch({"harvest", "--sweep"})
    void harvestSweepRunsWithoutError(LaunchResult result) {
        assertThat(result.exitCode()).isEqualTo(0);
    }

    @Test
    @Launch({"harvest", "--sweep", "--dry-run"})
    void harvestDryRunProducesOutput(LaunchResult result) {
        assertThat(result.exitCode()).isEqualTo(0);
        assertThat(result.getOutput()).contains("dry-run=true");
    }

    // --- qe command ---

    @Test
    @Launch({"qe", "--sample=5", "--tasks=pattern_naming"})
    void qeSampleProducesReport(LaunchResult result) {
        assertThat(result.exitCode()).isEqualTo(0);
        assertThat(result.getOutput()).contains("sample=5");
    }

    @Test
    @Launch({"qe", "--sample=3"})
    void qeReportShowsAgreementRate(LaunchResult result) {
        assertThat(result.exitCode()).isEqualTo(0);
        assertThat(result.getOutput()).contains("Agreement rate");
    }

    @Test
    @Launch({"qe", "--matrix", "--tasks=dedup", "--sample=1"})
    void qeMatrixFlagProducesComparisonReport(LaunchResult result) {
        assertThat(result.exitCode()).isEqualTo(0);
        assertThat(result.getOutput()).contains("Matrix").contains("Model");
    }

    @Test
    @Launch({"qe", "--matrix"})
    void qeMatrixWithDefaultsRunsCleanly(LaunchResult result) {
        assertThat(result.exitCode()).isEqualTo(0);
    }

    // --- deferred tests ---

    @Test
    @Disabled("Requires real QE logic — Phase 3")
    void qeAboveThresholdMarkedAsPromote() {
        // Will verify that entries scoring above the promotion threshold are flagged
    }

    @Test
    @Disabled("Requires Anthropic extension — Phase 2")
    void qeCompareSonnetUsesAnthropicQualityEvaluator() {
        // Will verify that --compare=sonnet routes to the Anthropic quality evaluator
    }
}
