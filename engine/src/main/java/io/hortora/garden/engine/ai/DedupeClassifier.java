package io.hortora.garden.engine.ai;

import dev.langchain4j.service.SystemMessage;
import dev.langchain4j.service.UserMessage;
import io.hortora.garden.engine.DedupeDecision;
import io.quarkiverse.langchain4j.RegisterAiService;

@RegisterAiService
public interface DedupeClassifier {

    @SystemMessage("""
        You are reviewing two knowledge garden entries for duplication.
        Classify as DISTINCT (different topics), RELATED (same area, worth cross-referencing),
        or DUPLICATE (same knowledge — one should absorb the other).
        Respond as JSON only:
        {"classification":"DISTINCT|RELATED|DUPLICATE","reasoning":"...","keep_id":null,"preserve_from_other":null}
        """)
    DedupeDecision classify(@UserMessage String entryPair);
}
