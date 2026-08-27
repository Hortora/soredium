---
id: PP-20260827-727cb8
title: "SKILL.md files for orchestrated skills must be minimal — loop + dispatch table only"
type: rule
scope: repo
applies_to: "any skill driven by a Python orchestrator (work-end, handover, future orchestrated skills)"
severity: important
refs:
  - work-end/SKILL.md
  - handover/SKILL.md
  - work-end/handlers/
  - handover/handlers/
violation_hint: "SKILL.md over 200 lines with inline handler details — LLM reads concrete handlers and skips the abstract orchestrator loop"
created: 2026-08-27
---

Orchestrator-driven SKILL.md files contain only: context resolution, the orchestrator call, and a dispatch table mapping ACTIONs to handler files. Handler details live in `handlers/*.md` files loaded lazily when the orchestrator yields that action. The LLM reads handler content only when it needs to execute a specific step — never upfront.

When a SKILL.md has both abstract machinery (orchestrator loop) and concrete handlers (write HANDOFF.md, run code-review) inline, the LLM reads everything upfront, latches onto the most actionable instruction, and skips the orchestrator loop entirely. Extracting handlers to separate files eliminates this shortcutting path — the LLM has one instruction ("call the orchestrator and follow its output") and reads handler details on demand.
