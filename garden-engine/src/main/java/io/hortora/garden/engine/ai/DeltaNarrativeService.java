package io.hortora.garden.engine.ai;

import dev.langchain4j.service.SystemMessage;
import dev.langchain4j.service.UserMessage;
import io.hortora.garden.engine.DeltaNarrative;
import io.quarkiverse.langchain4j.RegisterAiService;

@RegisterAiService
public interface DeltaNarrativeService {

    @SystemMessage("""
        You are an expert in JVM framework architecture. Given a git diff showing new
        interface or abstract class files, explain the architectural decision made.
        Respond as JSON only:
        {"decision":"...","pattern_name":"...","motivation":"...","introduced_at":"..."}
        """)
    DeltaNarrative explainDelta(@UserMessage String diffContext);
}
