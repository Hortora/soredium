---
name: work-pause
description: >
  Use when interrupting current branch work to switch to something else — user
  says "work pause", "pause this work", or "switch to a different issue".
  Supports a stack of paused branches. Pair with work-resume to restore.
---

# work-pause

**Routed by `work/SKILL.md`.** The `pause` command is handled by
`project/work.py` via the orchestrator loop in the `work` skill.

The pause pipeline is entirely mechanical — no judgment steps.
Three steps: WIP commit project, WIP commit workspace, push-and-stack.

The step-by-step logic previously in this file now lives in:
- `project/work.py` — pipeline step definitions (PAUSE_STEPS)

## Existing externalized scripts (unchanged)

- `work-pause/pause_exec.py` — commit-wip, push-and-stack, intent tracking
