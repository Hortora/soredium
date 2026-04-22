package io.hortora.garden.engine;

import io.hortora.garden.engine.ai.EntryMergeService;
import io.quarkus.test.junit.QuarkusTest;
import jakarta.inject.Inject;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

@QuarkusTest
class EntryMergeServiceTest {

    @Inject EntryMergeService service;
    @Inject MockReasoningService mock;

    @Test
    void defaultMockMergeContainsYamlFrontmatter() {
        assertThat(service.mergeEntries("any pair")).contains("---");
    }

    @Test
    void mergedOutputContainsRequiredSections() {
        mock.willReturnMerge("---\nid: GE-x\ntitle: My Title\nstack: Java\nscore: 11\n---\n## body text here");
        var result = service.mergeEntries("pair");
        assertThat(result).contains("title").contains("score");
        mock.willReturnMerge("---\nid: merged\ntitle: merged\nscore: 11\n---\nmerged body");
    }

    @Test
    void customMergeResultIsReturned() {
        mock.willReturnMerge("---\nid: GE-merged\ntitle: merged\nscore: 11\n---\nbody");
        assertThat(service.mergeEntries("pair")).contains("GE-merged");
        mock.willReturnMerge("---\nid: merged\ntitle: merged\nscore: 11\n---\nmerged body");
    }

    @Test
    void mergeResultIsNonNull() {
        assertThat(service.mergeEntries("entry1\nentry2")).isNotNull();
    }
}
