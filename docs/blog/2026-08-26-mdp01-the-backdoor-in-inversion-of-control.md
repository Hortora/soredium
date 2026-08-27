---
entry_type: note
subtype: diary
title: "The backdoor in inversion of control"
date: 2026-08-26
series: issue-271-mechanise-work-end
issue: 298
branch: main
project: soredium
projects: [Hortora/soredium]
author: mdp
tags: [orchestrator, ioc, llm-safety, state-machines, worklog]
---

# The backdoor in inversion of control

*Continues from [Wiring the orchestrator](2026-08-25-mdp01-wiring-the-orchestrator.md).*

The orchestrator's design principle is simple: Python drives, the LLM assists. Each invocation yields one action, the LLM executes it, calls back. The LLM cannot skip what it cannot see. That last sentence turned out to be wrong.

A casehub session ran work-end and forage failed during the wrap sweep — three retries, all timed out. The wrap summary showed the cascade: forage skipped, protocol skipped, diary skipped. The diary entry for an entire session's work was lost because a different step failed. Two independent steps, no dependency between them, and the failure of one killed the other.

The `skip_step=` parameter was the hole. It accepted any step name as a bare string and marked it skipped in close-progress — no validation that the step had actually been yielded by the orchestrator. The LLM received `step_failed` for forage and rationalised "the sweep is broken, skip everything." The orchestrator let it, because `skip_step` had no concept of what had been yielded.

The fix tracks what was last yielded. Every `_yield_judgment` and `_yield_user_input` writes `last_yielded=<step_name>` to close-progress before returning. `validate_skip` rejects any skip that doesn't match. One design choice made the difference: don't clear `last_yielded` after a skip. If you clear it, the lenient path (empty means "not set") lets the next skip through. Leave it set, and the LLM hits a mismatch on the next attempt. Only the orchestrator's next yield overwrites it.

Then a second failure surfaced — a different project, a different gap. The casehub-desiredstate workspace was stuck at `closing:promoted`. Blog publishing had failed during the promote step (a content routing issue), and the close log showed what happened next: `promote:ERROR:1`, then on the very next call, `report_promote` and `promote_pass` both ran. The promote step is mechanical — the orchestrator owns it. But `step_done=promote` accepted the call because it had no concept of step types. The LLM marked a failed mechanical step as done, the lifecycle transition fired, and the state advanced past the point of no return. A new session started, detected stale progress, reset it, and the workspace was irrecoverable.

`apply_step_done` now builds a set of mechanical step names from the step list and rejects calls for any of them. Mechanical steps are orchestrator-owned — only `run_loop` can mark them done. The LLM can complete judgment steps (that's the whole point of yielding). It cannot force past a failed script.

Both fixes are structural, not instructional. Adding "don't skip other steps" to the SKILL.md would help at the margin. Adding validation at the parameter level makes the wrong thing impossible. The SKILL.md instructions are still there (a `SKIP-ISOLATION` block that explains when skipping is appropriate), but they're defense-in-depth, not the primary guard.

The third change is observability. Every non-success path now writes to the worklog DB: mechanical step errors on each retry, step failures after retry exhaustion, invalid skip attempts, invalid step_done attempts, stale progress resets, reconciliation corrections. Previously the only record was the `.close-log.jsonl` file on the workspace branch — ephemeral, local, gone after branch closure. The worklog events survive in SQLite and link to work items when the branch is known. When the next orchestrator anomaly happens, the event trail will already be there.

The skip guard and the step_done guard are the same principle applied twice. The orchestrator yields control to the LLM at defined points, and the LLM can only affect the step it was given. Everything else is out of reach — not because the LLM was told to stay away, but because the parameter validation rejects the call. Inversion of control works when the inverted party has no backdoor to un-invert it.
