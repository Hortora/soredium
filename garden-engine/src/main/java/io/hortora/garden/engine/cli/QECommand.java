package io.hortora.garden.engine.cli;

import io.hortora.garden.engine.ModelComparisonResult;
import io.hortora.garden.engine.QEMatrixReport;
import picocli.CommandLine.Command;
import picocli.CommandLine.Option;

import java.util.List;
import java.util.concurrent.Callable;

@Command(name = "qe", description = "Run quality evaluation", mixinStandardHelpOptions = true)
public class QECommand implements Callable<Integer> {

    @Option(names = "--sample", description = "Number of entries to sample")
    int sample = 10;

    @Option(names = "--tasks", description = "Task types to evaluate (default: all)")
    String tasks = "all";

    @Option(names = "--compare", description = "Model to compare against (default: ollama)")
    String compare = "ollama";

    @Option(names = "--matrix", description = "Compare multiple models side by side")
    boolean matrix;

    @Override
    public Integer call() {
        if (matrix) {
            System.out.println("=== QE Matrix Report ===");
            System.out.println();
            // Placeholder matrix: run tasks through configured models
            // In production this would invoke real model inference;
            // for Phase 3 this is a stub that shows the structure
            var placeholderResults = List.of(
                new ModelComparisonResult("JLama Qwen2.5-3B", "dedup", "DISTINCT", "DISTINCT", true, true, 890L),
                new ModelComparisonResult("JLama Qwen2.5-3B", "pattern", "CDI Strategy", "CDI Strategy", true, true, 2100L)
            );
            var report = QEMatrixReport.from(placeholderResults);
            System.out.println(report.renderTable());
            System.out.println("Note: real inference requires models to be available.");
            return 0;
        }
        // existing non-matrix logic
        System.out.println("qe: sample=" + sample + " tasks=" + tasks + " compare=" + compare);
        System.out.println("Agreement rate: N/A (placeholder)");
        if (sample > 0) {
            for (int i = 0; i < sample; i++) {
                System.out.println("Sample " + i + ": placeholder");
            }
        }
        return 0;
    }
}
