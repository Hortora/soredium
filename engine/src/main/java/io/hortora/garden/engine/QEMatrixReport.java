package io.hortora.garden.engine;

import java.util.*;
import java.util.stream.*;

public class QEMatrixReport {

    public record Row(
        String modelName,
        String taskType,
        long avgInferenceMs,
        double jsonParseSuccessRate,
        double agreementRate,
        int sampleCount
    ) {}

    private final List<Row> rows;

    private QEMatrixReport(List<Row> rows) {
        this.rows = rows;
    }

    public static QEMatrixReport from(List<ModelComparisonResult> results) {
        // Group by (modelName, taskType) and aggregate
        var groups = results.stream()
            .collect(Collectors.groupingBy(r -> r.modelName() + "||" + r.taskType()));

        var rows = groups.entrySet().stream().map(e -> {
            var parts = e.getKey().split("\\|\\|", 2);
            var modelName = parts[0];
            var taskType = parts[1];
            var group = e.getValue();
            var avgMs = (long) group.stream().mapToLong(ModelComparisonResult::inferenceMs).average().orElse(0);
            var jsonRate = group.stream().filter(ModelComparisonResult::jsonParseSuccess).count() / (double) group.size();
            var agreeRate = group.stream().filter(ModelComparisonResult::agreesWithGoldStandard).count() / (double) group.size();
            return new Row(modelName, taskType, avgMs, jsonRate, agreeRate, group.size());
        }).sorted(Comparator.comparing(Row::modelName).thenComparing(Row::taskType))
          .toList();

        return new QEMatrixReport(rows);
    }

    public Row rowFor(String modelName, String taskType) {
        return rows.stream()
            .filter(r -> r.modelName().equals(modelName) && r.taskType().equals(taskType))
            .findFirst()
            .orElseThrow(() -> new NoSuchElementException("No row for " + modelName + "/" + taskType));
    }

    public String renderTable() {
        if (rows.isEmpty()) return "No results.\n";
        var sb = new StringBuilder();
        sb.append(String.format("%-30s %-12s %8s %8s %12s%n",
            "Model", "Task", "Avg ms", "JSON ok", "Sonnet agree"));
        sb.append("-".repeat(74)).append("\n");
        for (var row : rows) {
            sb.append(String.format("%-30s %-12s %8d %7.0f%% %11.0f%%%n",
                row.modelName(), row.taskType(), row.avgInferenceMs(),
                row.jsonParseSuccessRate() * 100, row.agreementRate() * 100));
        }
        return sb.toString();
    }
}
