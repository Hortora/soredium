---
name: work-start
description: >
  Use when a task or session is beginning — the opening directive in any
  work-item prompt, or when the user says they are beginning work. Handles
  both new and existing branches. NOT optional, must NOT be skipped.
slash-command: false
---

# work-start

**Routed by `work/SKILL.md`.** The `start` command is handled by
`project/work.py` via the orchestrator loop in the `work` skill.

Invoke `work` to start — it detects state, handles corruption triage,
and calls `work.py start` which runs the mechanical pipeline. Judgment
steps (issue resolution, branch naming, brainstorming) are yielded back
to the LLM via `ACTION=` and dispatched to handler files in
`work/handlers/`.

The step-by-step logic previously in this file now lives in:
- `project/work.py` — pipeline step definitions (START_STEPS)
- `work/handlers/resolve-issue.md` — issue resolution handler
- `work/handlers/branch-name.md` — branch name confirmation
- `work/handlers/platform-coherence.md` — platform doc review
- `work/handlers/check-protocols.md` — protocol review
- `work/handlers/brainstorm-offer.md` — brainstorm offer

## Existing externalized scripts (unchanged)

- `work-start/branch_create.py` — sync-main, create-branches, commit-scaffold
- `work-start/scaffold.py` — .plan and JOURNAL.md creation
- `work-start/flyway_scan.py` — Flyway version scan
