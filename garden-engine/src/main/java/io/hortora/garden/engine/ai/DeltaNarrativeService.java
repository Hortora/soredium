package io.hortora.garden.engine.ai;

import io.hortora.garden.engine.DeltaNarrative;

public interface DeltaNarrativeService {
    DeltaNarrative explainDelta(String diffContext);
}
