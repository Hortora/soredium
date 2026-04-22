package io.hortora.garden.engine;

import io.hortora.garden.engine.ai.EntryMergeServiceImpl;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class EntryMergeServiceTest {

    private EntryMergeServiceImpl service;

    @BeforeEach
    void setUp() {
        service = new EntryMergeServiceImpl();
    }

    @Test
    void mergedOutputContainsYamlFrontmatter() {
        var merged = "---\nid: GE-merged\ntitle: merged\nscore: 11\n---\nbody";
        assertThat(service.mergeEntries(merged)).contains("---");
    }

    @Test
    void mergedOutputContainsRequiredSections() {
        var merged = "---\nid: GE-x\ntitle: My Title\nstack: Java\nscore: 11\n---\n## body text here";
        var result = service.mergeEntries(merged);
        assertThat(result).contains("title").contains("score");
    }

    @Test
    void nullResponseThrowsIllegalStateException() {
        assertThatThrownBy(() -> service.mergeEntries(null))
                .isInstanceOf(IllegalStateException.class);
    }

    @Test
    void responseWithoutFrontmatterThrowsException() {
        assertThatThrownBy(() -> service.mergeEntries("just plain text, no yaml"))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("frontmatter");
    }
}
