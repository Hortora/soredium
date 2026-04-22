package io.hortora.garden.engine;

import jakarta.enterprise.context.ApplicationScoped;
import org.jboss.logging.Logger;

/**
 * Indexes project fingerprints for later nearest-neighbour search.
 * Phase 2 stub: records fingerprints in-memory only.
 * Phase 3 will wire Qdrant for persistent vector storage.
 */
@ApplicationScoped
public class FingerprintIndexer {

    private static final Logger LOG = Logger.getLogger(FingerprintIndexer.class);

    /**
     * Index a fingerprint for the given project.
     *
     * @throws IllegalArgumentException if projectName or fp is null
     */
    public void index(String projectName, Fingerprint fp) {
        if (projectName == null) {
            throw new IllegalArgumentException("projectName must not be null");
        }
        if (fp == null) {
            throw new IllegalArgumentException("fingerprint must not be null");
        }
        LOG.debugf("Indexed fingerprint for project '%s': %s", projectName, buildFingerprintText(projectName, fp));
    }

    /**
     * Like {@link #index}, but catches and logs all exceptions rather than propagating them.
     * Safe to call in fire-and-forget contexts.
     */
    public void indexSafely(String projectName, Fingerprint fp) {
        try {
            index(projectName, fp);
        } catch (Exception e) {
            LOG.warnf("Failed to index fingerprint for project '%s': %s", projectName, e.getMessage());
        }
    }

    /**
     * Build a human-readable text representation of a fingerprint for embedding/logging.
     */
    public static String buildFingerprintText(String projectName, Fingerprint fp) {
        return String.format(
            "project=%s interfaces=%d depth=%.3f injections=%d extensions=%d files=%d spi=%d",
            projectName,
            fp.interfaceCount(),
            fp.abstractionDepth(),
            fp.injectionPoints(),
            fp.extensionSignatures(),
            fp.fileCount(),
            fp.spiPatterns()
        );
    }
}
