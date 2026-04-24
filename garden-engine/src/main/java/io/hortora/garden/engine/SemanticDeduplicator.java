package io.hortora.garden.engine;

import io.hortora.garden.engine.ai.DedupeClassifier;
import io.hortora.garden.engine.ai.EntryMergeService;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.inject.Inject;
import java.util.logging.Logger;

@ApplicationScoped
public class SemanticDeduplicator {

    private static final Logger LOG = Logger.getLogger(SemanticDeduplicator.class.getName());

    @Inject DedupeClassifier classifier;
    @Inject EntryMergeService mergeService;

    /**
     * Process a pair of garden entries: classify and merge if duplicate.
     */
    public HarvestResult process(String entry1, String entry2) {
        var pair = entry1 + "\n\n---separator---\n\n" + entry2;
        var decision = classifier.classify(pair);

        String merged = null;
        if (decision.classification() == DedupeDecision.Classification.DUPLICATE) {
            try {
                merged = mergeService.mergeEntries(pair);
                if (merged == null || !merged.contains("---")) {
                    LOG.warning("Merge produced invalid YAML — discarding merge result");
                    merged = null;
                }
            } catch (Exception e) {
                LOG.warning("Entry merge failed: " + e.getMessage());
            }
        }

        return new HarvestResult(decision.classification(), decision.reasoning(), merged);
    }

    /**
     * Process all pending entry pairs from a garden path.
     * Returns summary: pairs checked, related, duplicates merged.
     */
    public HarvestSummary sweep(java.nio.file.Path gardenRoot, boolean dryRun) {
        LOG.info("harvest sweep — garden: " + gardenRoot + " dry-run: " + dryRun);
        // Phase 4 stub: returns empty summary
        // Full implementation: scan garden files, find candidates, classify, merge
        return new HarvestSummary(0, 0, 0);
    }

    public record HarvestSummary(int checked, int related, int merged) {}
}
