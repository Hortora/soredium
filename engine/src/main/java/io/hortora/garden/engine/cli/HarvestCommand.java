package io.hortora.garden.engine.cli;

import io.hortora.garden.engine.SemanticDeduplicator;
import jakarta.inject.Inject;
import picocli.CommandLine.Command;
import picocli.CommandLine.Option;

import java.nio.file.Path;
import java.util.concurrent.Callable;

@Command(name = "harvest", description = "Run semantic deduplication harvest", mixinStandardHelpOptions = true)
public class HarvestCommand implements Callable<Integer> {

    @Option(names = "--sweep", description = "Sweep all entries for deduplication candidates")
    boolean sweep;

    @Option(names = "--dry-run", description = "Preview changes without writing")
    boolean dryRun;

    @Inject SemanticDeduplicator deduplicator;

    @Override
    public Integer call() {
        if (sweep) {
            var gardenRoot = Path.of(
                System.getProperty("hortora.garden", System.getProperty("user.home") + "/.hortora/garden"));
            var summary = deduplicator.sweep(gardenRoot, dryRun);
            System.out.println("harvest: checked=" + summary.checked() +
                               " related=" + summary.related() +
                               " merged=" + summary.merged() +
                               " dry-run=" + dryRun);
        } else {
            System.out.println("harvest: no --sweep flag provided");
        }
        return 0;
    }
}
