package io.hortora.garden.engine.cli;

import picocli.CommandLine.Command;
import picocli.CommandLine.Option;

import java.util.concurrent.Callable;

@Command(name = "harvest", description = "Run deduplication harvest", mixinStandardHelpOptions = true)
public class HarvestCommand implements Callable<Integer> {

    @Option(names = "--sweep", description = "Sweep all entries for deduplication candidates")
    boolean sweep;

    @Option(names = "--dry-run", description = "Preview changes without writing")
    boolean dryRun;

    @Override
    public Integer call() {
        System.out.println("harvest: sweep=" + sweep + " dry-run=" + dryRun);
        return 0;
    }
}
