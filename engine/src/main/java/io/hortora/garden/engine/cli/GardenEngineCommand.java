package io.hortora.garden.engine.cli;

import io.quarkus.picocli.runtime.annotations.TopCommand;
import picocli.CommandLine;
import picocli.CommandLine.Command;

@TopCommand
@Command(
    name = "garden-engine",
    mixinStandardHelpOptions = true,
    subcommands = {MineCommand.class, HarvestCommand.class, QECommand.class},
    description = "Garden Engine — deduplication and pattern-detection pipeline"
)
public class GardenEngineCommand implements Runnable {

    @CommandLine.Spec
    CommandLine.Model.CommandSpec spec;

    @Override
    public void run() {
        spec.commandLine().usage(System.out);
    }
}
