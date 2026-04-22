package io.hortora.garden.engine.ai;

import dev.langchain4j.service.SystemMessage;
import dev.langchain4j.service.UserMessage;
import io.quarkiverse.langchain4j.RegisterAiService;

@RegisterAiService
public interface EntryMergeService {

    @SystemMessage("""
        Merge two duplicate knowledge garden entries into one enriched entry.
        Preserve the best title, most complete body, all code examples, highest score.
        Output the full merged entry as YAML frontmatter (starting with ---) followed by body.
        """)
    String mergeEntries(@UserMessage String entryPair);
}
