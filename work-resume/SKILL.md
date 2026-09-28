---
name: work-resume
description: >
  Use when returning to a paused branch from the pause stack — user says
  "work resume", "resume", or "go back to that branch". Pause-stack
  restoration only, not general branch continuation (use "work continue"
  for that). Invoked from main to restore a previously paused work session.
  Handles multiple paused branches via stack.
---

# work-resume

**Routed by `work/SKILL.md`.** The `resume` command is handled by
`project/work.py` via the orchestrator loop in the `work` skill.

Six steps: stack_pick (judgment), pop_stack, checkout_branches,
rebase, reset_wip, context_resume (judgment).

The step-by-step logic previously in this file now lives in:
- `project/work.py` — pipeline step definitions (RESUME_STEPS)
- `work/handlers/stack-pick.md` — stack picker handler
- `work/handlers/load-context.md` — context resume handler

## Existing externalized scripts (unchanged)

- `work-resume/resume_exec.py` — checkout-branches, rebase, reset-wip, intent tracking
