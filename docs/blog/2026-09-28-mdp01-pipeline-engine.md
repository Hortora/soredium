---
layout: post
title: "The LLM Stops Reading Instructions"
date: 2026-09-28
entry_type: note
subtype: diary
projects: [hortora/soredium]
tags: [lifecycle, orchestrator, pipeline, architecture]
series: issue-384-pipeline-lifecycle
---

The work lifecycle — start a branch, pause, resume, advance the queue — was orchestrated by having Claude read a SKILL.md file and follow step-by-step instructions. 1763 lines of prose across four files. Every session, the LLM would read the full thing, interpret the branching logic, and decide what to do next.

This worked until it didn't. The LLM would skip steps, misread conditionals, or invent transitions not in the table. A 753-line work-start SKILL.md is not an instruction manual — it's a liability. The more text you give an LLM to interpret, the more opportunities it has to take shortcuts.

The work-end orchestrator had already solved this. `work_end_orchestrator.py` drives the close ceremony as a Python step list: mechanical steps run without the LLM, judgment steps yield `ACTION=` and wait. The LLM only acts when genuine reasoning is needed — reviewing code, writing content, making triage decisions. Everything else is deterministic.

I extended that pattern to the rest of the lifecycle.

## One file, six commands

`project/work.py` is the unified pipeline engine. Each command maps to a list of `StepDef` objects:

```python
PIPELINES = {
    "start": START_STEPS,      # 15 steps — branch creation, scaffold, context
    "continue": CONTINUE_STEPS, # 5 steps — transient resolve, health, context load
    "pause": PAUSE_STEPS,       # 3 steps — entirely mechanical
    "resume": RESUME_STEPS,     # 6 steps — stack pick, restore, rebase
    "next": NEXT_STEPS,         # 5 steps — advance queue, refresh context
    "find": FIND_STEPS,         # 4 steps — query recommendations, populate queue
}
```

Pause is three mechanical steps. No LLM involvement at all — commit WIP, push to stack, switch to main. The existing `pause_exec.py` already did the work; it just needed a step list wrapping it.

Resume has two judgment points: picking from the pause stack (when multiple branches are paused) and loading context after restore. Everything between — pop stack, checkout, rebase, reset WIP — is mechanical.

Start is the most complex at 15 steps, but most delegate to scripts that already existed: `branch_create.py`, `scaffold.py`, `flyway_scan.py`. The judgment steps — issue resolution, branch naming, brainstorming — yield to the LLM via handler files.

## The handler pattern

Each judgment step maps to a markdown file in `work/handlers/`. When the pipeline yields `ACTION=resolve_issue`, the SKILL.md loads `handlers/resolve-issue.md` — a focused, self-contained instruction for that one step. The LLM sees only what it needs for the current decision, not the full lifecycle flow.

This follows the protocol we captured earlier: SKILL.md files for orchestrated skills must be minimal — loop and dispatch table only. Handler details load lazily.

The four SKILL.md files shrank from 1763 lines to 276. An 84% reduction. `work/SKILL.md` is now routing logic plus a dispatch table. The sub-skills (`work-start`, `work-pause`, `work-resume`) are redirect stubs.

## Shared infrastructure

The engine itself (`orchestrator_engine.py`, `shared_steps.py`, `close_progress.py`) lived in `work-end/` because that's where the pattern was born. With six commands using it, it belongs in `project/` alongside the other lifecycle infrastructure.

The migration was straightforward — copy to `project/`, update imports in the copies, leave thin `importlib` re-export wrappers in `work-end/`. One wrinkle: a wrapper file named `shared_steps.py` that imports from `shared_steps` creates a circular import. Python finds itself before the target module. `importlib.util.spec_from_file_location` with a distinct module name sidesteps this — load from the explicit path, re-export into `globals()`.

Progress tracking generalised similarly. `close_progress.py` became `work_progress.py` — reads `.work-progress` or `.close-progress` (backward compat for in-flight work-end operations), writes `.work-progress` only. One file to check for interrupted state across all commands.

## Conflict resolution

Rebase conflicts are the other barrier to autonomous operation. Most are lifecycle files (`.plan`, `JOURNAL.md`) that the pipeline regenerates — taking ours is always correct. Source file conflicts need the LLM. Structural conflicts need a human.

Three tiers, applied in order:

1. **Auto-resolve** — lifecycle files in `LIFECYCLE_AUTO_RESOLVE` get `checkout --ours`
2. **LLM semantic** — yield `ACTION=resolve_conflict` with the remaining files
3. **Human** — yield `ACTION=user_input` if the LLM can't resolve

The implementation is 41 lines. The `on_mechanical_error` callback in `run_loop` already exists — conflict resolution just classifies the error and routes it.

## What changes

The LLM's role in the lifecycle shifts from orchestrator to service. It still makes judgment calls — which issue to work on, whether to brainstorm, how to resolve a conflict. But it no longer reads 753 lines of instructions and decides which steps to run. Python decides. The LLM executes judgment steps on demand.

This is the pattern from work-end, proven over months of close ceremonies, extended to the full lifecycle. The fragility that prompted this — and the stale `.plan` corruption that kicked off the session — came from the LLM interpreting state transitions instead of Python managing them deterministically.

One observation: the corruption detection that flagged the stale plan on session start was itself fragile. Two checks (S5 branch mismatch and S7 stale plan on main) fired for the same underlying condition, and the generic check blocked auto-recovery because it didn't consider context. The fix was six lines — suppress S5 when S7 fires. The system designed to prevent problems was creating one. Worth remembering when adding diagnostic layers: each new check can interact with existing checks in ways that are obvious in hindsight.
