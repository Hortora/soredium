package io.hortora.garden.engine;

import io.hortora.garden.engine.ai.DedupeClassifier;
import io.hortora.garden.engine.ai.DeltaNarrativeService;
import io.hortora.garden.engine.ai.EntryMergeService;
import io.hortora.garden.engine.ai.PatternNamingService;
import jakarta.annotation.Priority;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.enterprise.inject.Alternative;

@Alternative
@Priority(1)
@ApplicationScoped
public class MockReasoningService
    implements PatternNamingService, DeltaNarrativeService, DedupeClassifier, EntryMergeService {

    private PatternCandidate nextPattern = new PatternCandidate("mock-pattern", "mock", "mock", "mock");
    private DeltaNarrative nextNarrative = new DeltaNarrative("mock-decision", "mock", "mock", "v2.0");
    private DedupeDecision nextDecision = new DedupeDecision(DedupeDecision.Classification.DISTINCT, "mock", null, null);
    private String nextMerge = "---\nid: merged\ntitle: merged\nscore: 11\n---\nmerged body";

    public void willReturnPattern(PatternCandidate p) { this.nextPattern = p; }
    public void willReturnNarrative(DeltaNarrative n) { this.nextNarrative = n; }
    public void willReturnDecision(DedupeDecision d) { this.nextDecision = d; }
    public void willReturnMerge(String m) { this.nextMerge = m; }

    @Override public PatternCandidate namePattern(String ctx) { return nextPattern; }
    @Override public DeltaNarrative explainDelta(String ctx) { return nextNarrative; }
    @Override public DedupeDecision classify(String pair) { return nextDecision; }
    @Override public String mergeEntries(String pair) { return nextMerge; }
}
