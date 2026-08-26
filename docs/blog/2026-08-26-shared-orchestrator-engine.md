---
title: "One engine, two lifecycles"
date: 2026-08-26
entry_type: note
subtype: diary
projects: [Hortora/soredium]
series: soredium-lifecycle
author: mdp
tags: [orchestrator, wrap, close, shared-engine, session-boundary]
---

# One engine, two lifecycles

The work-end orchestrator proved the yield-based pattern — Python drives the sequence, the LLM executes one action at a time, progress survives session crashes. But wrap (the mid-session handover) was still fully LLM-driven: a SKILL.md checklist that the LLM followed as instructions. Same failure modes as before mechanisation — steps get skipped, the LLM rationalises "this is a small session, nothing to sweep," session-bound knowledge evaporates.

The fix wasn't to copy the work-end orchestrator and edit it. The fix was to split the orchestrator into what's shared and what isn't.

`orchestrator_engine.py` owns the loop: iterate steps, check progress, execute mechanical steps, yield judgment points, handle errors and retries. Both orchestrators call `run_loop()` with their step list and optional callbacks. Work-end passes five callbacks for its slot per-repo fan-out, lifecycle transitions, and main-mode handlers. Wrap passes zero — it's the simple case.

`shared_steps.py` owns the step definitions that both lifecycles use: forage, protocol, update-claude-md, write-content, garden feedback, notes. The step factories (`make_forage_step`, `make_garden_feedback_step`) accept a phase name and sweep key, so the same step definition works in both contexts. A bug fix in the yield logic or sweep deselection fixes both orchestrators.

The session also added three observability features that apply to both lifecycles:

**Session boundary events** — a `session_boundaries` table in the worklog DB. Both orchestrators record which steps ran, which produced artifacts, and which were skipped. Over time this shows patterns: branches where forage consistently produces zero entries, sessions where diary is always skipped, garden feedback that never downgrades anything.

**Diary accumulation** — the write-content step now detects existing diary entries for the current branch and passes `DIARY_MODE=revise` in the action context. Multi-session branches should build one evolving narrative, not fragment across standalone entries.

**Step production metrics** — each judgment step can report `produced=N` when the LLM marks it done. The count persists to the progress file and flows into the session boundary event. "Forage ran but produced zero" is a different signal from "forage was skipped."

The wrap orchestrator is smaller than the close orchestrator by a factor of five. That's the point — most of the complexity is in close-specific steps (review, promote, rebase, squash, land, verify, archive). The shared engine and steps are the common core that both need. When we add a new shared step — or strengthen an existing one like garden feedback — it shows up in both lifecycles automatically.
