---
name: doc-freshness
description: >
  Documentation freshness detection — structural anchor check for work-end
  gate and CI enforcement. Not invoked directly; called by work-end
  orchestrator's doc_freshness_gate step.
slash-command: false
---

# Doc Freshness Check

Internal skill — not user-invoked. Called by work-end orchestrator.

## Usage

```bash
python3 ~/.claude/skills/doc-freshness/doc_freshness_check.py \
    --diff <changed-files-list> --docs <docs-dir> [--graph <dep-graph>]
```

Output: JSON with candidate-stale sections. Exit code 1 if candidates found, 0 if clean.
