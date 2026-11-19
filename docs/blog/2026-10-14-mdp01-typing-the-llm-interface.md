---
layout: post
title: "Typing the orchestrator's LLM interface"
date: 2026-10-14
entry_type: note
subtype: diary
projects: [Hortora/soredium]
tags: [orchestrator, typing, protocol, architecture]
series: issue-451-typed-llm-interface
---

The orchestrator engine has driven 39 judgment steps across three orchestrators for months now. The protocol was stringly-typed from the start: `ACTION=step_name` on the way out, `step_done=X produced=N` on the way back. It worked. The bugs we've been fixing — stale attempt counters (#454), non-idempotent step handling (#450), issue closure state (#453) — were all in the mechanical step logic, not in the judgment protocol.

So when I sat down to implement the typed interface from the Phase 4 spec, Claude pushed back. The analysis was honest: the LLM-orchestrator communication channel stays the same regardless (KEY=VALUE on stdout, command-line args back). Adding `JudgmentRequest` and `JudgmentResponse` dataclasses types the Python side, but the actual wire format doesn't change. The recent bugs were all mechanical. Was this premature abstraction?

I decided it wasn't, but the tension was real. The stringly-typed protocol had a specific failure mode we hadn't hit yet: 31 of 39 judgment steps had no `verify_fn` at all. Responses were accepted without validation. The `step_type` field was a plain string — a typo like `"judgement"` (British spelling) would silently create a step that never yields and never executes. These are latent risks, not active bugs. The typing prevents them from ever becoming active.

The design had one genuine tension worth recording. The spec said `action_context_fn` should return `JudgmentRequest`. But `JudgmentRequest` contains both step metadata (handler path, response schema, skippable flag, timeout hint) and invocation-specific context (diff range, branch name). These have different owners: metadata is fixed at step definition time; context varies per invocation. We resolved this cleanly — `run_loop` assembles the `JudgmentRequest` from `StepDef` fields plus `action_context_fn` output. The context function stays focused on context.

The implementation landed in six commits, each independently testable. `StepType` enum replaced 97 string literals across all three orchestrators. `_yield_judgment` now takes a `JudgmentRequest` and serializes it — the output includes `HANDLER=`, `SKIPPABLE=`, `TIMEOUT_HINT=`, `SCHEMA=`. Response parsing constructs `JudgmentResponse` from CLI args and validates against the step's schema. Invalid outcomes get specific errors instead of silent acceptance.

One consequence I didn't anticipate: merging `_yield_user_input` into `_yield_judgment`. The old code had separate functions for judgment steps and user-input steps (arc42_scan, session_rename, garden_feedback, notes). With `JudgmentRequest`, the distinction collapses — user-input steps are just judgment steps with `USER_INPUT=yes` in their context. The output changes from `ACTION=user_input` to `ACTION=arc42_scan` with the step's own name. Cleaner, and it means the LLM can distinguish "this step needs user input" from "this step failed and needs help" — which were previously both `ACTION=user_input`.

The `skip_step=X` arg was supposed to be fully replaced by `step_done=X outcome=skipped`, but the existing SKILL.md handlers still send `skip_step=X`. I kept the fallback rather than updating all handler files in this branch. The unified protocol works; the old path is a compatibility shim until the handlers catch up.

The branch is +1000/-239 lines across 10 files. Most of the additions are tests (492 lines) and the new `judgment.py` module (126 lines). The conversion itself — string literals to enum values, ad-hoc dicts to typed requests — was mechanical. The interesting part was how little the existing tests needed to change. Five test assertions that compared `step_type == "lifecycle"` switched to `step_type == StepType.LIFECYCLE`. Zero new regressions against the pre-existing test suite.

What this opens up: per-step response schemas can now require specific evidence. A squash step could require `evidence.verified=true`. A code review could require `evidence.findings` as a list. The infrastructure is there; the schemas are currently all identical (DEFAULT_JUDGMENT_SCHEMA). Tightening them step by step is incremental work that doesn't require another protocol change.
