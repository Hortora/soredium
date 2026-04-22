package io.hortora.garden.engine.cli;

import picocli.CommandLine.Command;
import picocli.CommandLine.Option;

import java.util.concurrent.Callable;

@Command(name = "qe", description = "Run quality evaluation", mixinStandardHelpOptions = true)
public class QECommand implements Callable<Integer> {

    @Option(names = "--sample", description = "Number of entries to sample")
    int sample = 10;

    @Option(names = "--tasks", description = "Task types to evaluate (default: all)")
    String tasks = "all";

    @Option(names = "--compare", description = "Model to compare against (default: ollama)")
    String compare = "ollama";

    @Override
    public Integer call() {
        System.out.println("qe: sample=" + sample + " tasks=" + tasks + " compare=" + compare);
        System.out.println("Agreement rate: N/A (placeholder)");
        for (int i = 0; i < sample; i++) {
            System.out.println("Sample " + i + ": placeholder");
        }
        return 0;
    }
}
