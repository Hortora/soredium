package io.hortora.garden.engine;

import org.junit.jupiter.api.Test;
import java.util.List;
import static org.assertj.core.api.Assertions.*;

class ModelComparisonResultTest {

    @Test
    void modelComparisonResultHasAllRequiredFields() {
        var result = new ModelComparisonResult(
            "JLama Qwen2.5-3B", "dedup", "DISTINCT", "DISTINCT", true, true, 1234L
        );
        assertThat(result.modelName()).isEqualTo("JLama Qwen2.5-3B");
        assertThat(result.taskType()).isEqualTo("dedup");
        assertThat(result.modelOutput()).isEqualTo("DISTINCT");
        assertThat(result.goldStandardOutput()).isEqualTo("DISTINCT");
        assertThat(result.jsonParseSuccess()).isTrue();
        assertThat(result.agreesWithGoldStandard()).isTrue();
        assertThat(result.inferenceMs()).isEqualTo(1234L);
    }

    @Test
    void matrixReportAggregatesAverageInferenceMs() {
        var results = List.of(
            new ModelComparisonResult("Model-A", "dedup", "DISTINCT", "DISTINCT", true, true, 1000L),
            new ModelComparisonResult("Model-A", "dedup", "RELATED", "RELATED", true, true, 2000L),
            new ModelComparisonResult("Model-A", "dedup", "DISTINCT", "DUPLICATE", true, false, 3000L)
        );
        var report = QEMatrixReport.from(results);
        var row = report.rowFor("Model-A", "dedup");
        assertThat(row.avgInferenceMs()).isEqualTo(2000L);
        assertThat(row.jsonParseSuccessRate()).isCloseTo(1.0, offset(0.001));
        assertThat(row.agreementRate()).isCloseTo(0.667, offset(0.001));
    }

    @Test
    void matrixReportAgreementRateIsZeroForNoMatches() {
        var results = List.of(
            new ModelComparisonResult("M", "dedup", "DISTINCT", "DUPLICATE", true, false, 100L),
            new ModelComparisonResult("M", "dedup", "RELATED", "DUPLICATE", true, false, 200L)
        );
        var row = QEMatrixReport.from(results).rowFor("M", "dedup");
        assertThat(row.agreementRate()).isCloseTo(0.0, offset(0.001));
    }

    @Test
    void matrixReportRendersTableWithRequiredHeaders() {
        var results = List.of(
            new ModelComparisonResult("JLama-3B", "dedup", "DISTINCT", "DISTINCT", true, true, 500L)
        );
        var table = QEMatrixReport.from(results).renderTable();
        assertThat(table)
            .contains("Model")
            .contains("Task")
            .contains("Avg ms")
            .contains("JSON ok")
            .contains("Sonnet agree");
    }

    @Test
    void matrixReportIncludesModelNameInTable() {
        var results = List.of(
            new ModelComparisonResult("JLama-Qwen2.5", "dedup", "DISTINCT", "DISTINCT", true, true, 750L)
        );
        var table = QEMatrixReport.from(results).renderTable();
        assertThat(table).contains("JLama-Qwen2.5");
    }

    @Test
    void matrixReportHandlesMultipleModels() {
        var results = List.of(
            new ModelComparisonResult("Model-A", "dedup", "DISTINCT", "DISTINCT", true, true, 100L),
            new ModelComparisonResult("Model-B", "dedup", "DUPLICATE", "DISTINCT", false, false, 200L)
        );
        var report = QEMatrixReport.from(results);
        assertThat(report.rowFor("Model-A", "dedup").agreementRate()).isCloseTo(1.0, offset(0.001));
        assertThat(report.rowFor("Model-B", "dedup").agreementRate()).isCloseTo(0.0, offset(0.001));
        var table = report.renderTable();
        assertThat(table).contains("Model-A").contains("Model-B");
    }
}
