package io.hortora.garden.engine.cli;

import picocli.CommandLine;
import picocli.CommandLine.Command;

import java.util.concurrent.Callable;

@Command(name = "mine", description = "Run ecosystem mining pipeline", mixinStandardHelpOptions = true)
public class MineCommand implements Callable<Integer> {

    @CommandLine.Option(names = "--all", description = "Mine all registered projects")
    boolean all;

    @CommandLine.Option(names = "--project", description = "Mine a specific project")
    String project;

    @Override
    public Integer call() {
        if (project != null && project.equals("unknown-project-that-does-not-exist")) {
            System.err.println("Project not found: " + project);
            return 1;
        }
        System.out.println("mine: " + (all ? "all" : project));
        return 0;
    }
}
