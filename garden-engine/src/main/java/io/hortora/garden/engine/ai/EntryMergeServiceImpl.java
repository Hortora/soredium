package io.hortora.garden.engine.ai;

import jakarta.enterprise.context.ApplicationScoped;

@ApplicationScoped
public class EntryMergeServiceImpl implements EntryMergeService {

    @Override
    public String mergeEntries(String entryPair) {
        // Validates that the response contains required sections
        if (entryPair == null || !entryPair.contains("---"))
            throw new IllegalStateException("Merge response must contain YAML frontmatter");
        return entryPair;
    }
}
