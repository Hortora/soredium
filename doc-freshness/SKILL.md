---
name: doc-freshness
description: >
  Documentation freshness detection — structural anchor check for CI
  enforcement. Run by hand or in CI; no skill currently invokes it.
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

No skill currently invokes this. The `doc_freshness_gate` step existed in the
work-end orchestrator deleted in #499; `project/work_progress.py` still lists it
but nothing calls the gate. See Hortora/soredium#547 for disposition.
