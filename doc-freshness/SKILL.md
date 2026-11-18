---
name: doc-freshness
description: >
  Documentation freshness detection — structural anchor check for CI
  enforcement. Run by hand or in CI; no skill currently invokes it.
  Advisory item in work-end pre-close checklist.
slash-command: false
---

# Doc Freshness Check

Standalone script — run by hand or in CI. No skill currently invokes it
(the work-end orchestrator gate was removed in #499).

## Usage

```bash
python3 ~/.claude/skills/doc-freshness/doc_freshness_check.py \
    --diff <changed-files-list> --docs <docs-dir> [--graph <dep-graph>]
```

Output: JSON with candidate-stale sections. Exit code 1 if candidates found, 0 if clean.

## Skill Chaining

**Invoked by:** `work-end` — advisory item in the pre-close checklist (Step 2)
