# Work-End Redesign — Decisions

## D1: Scope — strip to essential close ceremony

**Choice:** Work-end owns only: land content, stamp branch, advance queue, checkout main. Everything else (review, blog, artifact promotion, issue closure) becomes pre-close or post-close phases that run independently.
**Alternatives:**
- Keep current scope — same ~12 responsibilities with better architecture underneath. Rejected because the scope itself is the problem — 53 steps in one pipeline means any step can corrupt any other step's state.
- Hybrid core + optional hooks — conceptually similar to chosen approach but frames hooks as optional; the chosen approach makes the phase separation structural.
**Rationale:** Failure isolation. Pre-close failures must not corrupt close-ceremony state. Close-ceremony failures must not destroy the issue queue. This is impossible when all 12 concerns share one pipeline, one progress file, and one mutable context.
**Trade-offs:** Pre-close steps need their own coordination mechanism; they can no longer rely on the orchestrator to sequence them.
**Sources:** 80 work-end issues in 70 days; architecture analysis showing 7 independent .plan deletion paths
**Exploration:** quick
**Status:** captured

## D2: Plan split — separate queue from ceremony state

**Choice:** Queue file holds the issue list and survives across many branch close cycles. Close-ceremony state is ephemeral and deleted when the ceremony completes. The queue is never touched by close logic.
**Alternatives:**
- Keep unified .plan with guard abstraction — single function gates all deletion/mutation. Simpler change but the coupling remains; adding a new deletion path without the guard is still possible.
**Rationale:** ADR-0013 merged .meta into .plan for "one file, no sync." But coupling lifecycle state to the issue queue means deleting ceremony state destroys the queue. This is the root cause of 12 plan-destruction bugs (7 independent deletion paths, only 3 guarded).
**Trade-offs:** Reverses ADR-0013's "one file" benefit. Two files to manage, but with fundamentally different lifecycles this is correct — they were never the same thing.
**Sources:** ADR-0013; issues #358, #364, #442, #466, #485, #496, #498; fork analysis showing 7 deletion paths
**Exploration:** quick
**Depends on:** D1 (scope determines what ceremony state contains)
**Status:** captured

## D3: Modes — one ceremony, different inputs

**Choice:** The close ceremony is always the same steps. What varies is the input: which repo(s), which branch(es), which queue. Mode logic moves to a "resolve what to close" phase that runs BEFORE the ceremony, not inside it.
**Alternatives:**
- Separate pipelines per mode — branch/slot/main are distinct operations with different step lists. Cleaner but duplicates ceremony logic.
- Keep filtered pipeline — single step list with mode flags but reduced step count. Preserves the combinatorial explosion.
**Rationale:** 5 modes × 5 dispositions = 25 theoretical execution paths. Each bug fix touches one path and can break others. Moving mode resolution outside the ceremony eliminates the combinatorial matrix.
**Trade-offs:** The resolve phase needs to produce a clean, uniform input for the ceremony. Complex slot topologies still need classification — but that happens once, upfront, not threaded through 53 steps.
**Sources:** 14 multi-repo coordination issues; fork analysis showing mutable shared context pattern
**Exploration:** quick
**Depends on:** D1 (reduced scope means fewer steps to vary by mode)
**Status:** captured

## D4: Execution — fully mechanical

**Choice:** The close ceremony runs as a single Python invocation that either succeeds or fails with a clear error. No LLM loop, no progress file, no reconciliation.
**Alternatives:**
- Checkpoint + resume — mechanical with checkpoints for crash recovery. Adds complexity for an edge case (session crash mid-ceremony).
- Keep LLM-in-the-loop — some steps need judgment (conflict resolution, manual merge). But with a stripped scope, no judgment calls remain in the ceremony itself.
**Rationale:** The LLM-in-the-loop model with .close-progress is the source of 13 loop/stall bugs. Reconciliation code resets progress, phase-skip fills gaps, lifecycle transitions can fail on concurrent modification — each recovery mechanism creates new failure modes.
**Trade-offs:** No crash recovery within the ceremony. If it fails partway, the user re-runs from scratch. Acceptable because the ceremony is now 4 short steps, not 53.
**Sources:** 13 orchestrator loop issues; .close-progress reconciliation as loop source
**Exploration:** quick
**Depends on:** D1 (stripped scope makes fully mechanical feasible)
**Status:** captured

## D5: Recovery — eliminate most corruption triage

**Choice:** If the ceremony is atomic (succeeds or rolls back), most corruption scenarios vanish. Keep only checks for genuinely external corruption: branch deleted by another user, plan file edited by hand, network failure during push. The 620-line corruption.py shrinks to ~50 lines.
**Alternatives:**
- Keep current corruption triage — even clean ceremonies can be interrupted. But the full 17+ scenario matrix exists because the current system leaves inconsistent state; a clean system shouldn't need it.
- Replace with pre-flight checks — refuse to run if preconditions fail. This is partly incorporated (resolve phase checks preconditions) but isn't sufficient alone.
**Rationale:** The corruption triage system exists to recover from inconsistent state left by the current work-end. A system that doesn't leave inconsistent state doesn't need most of that recovery.
**Trade-offs:** Rare edge cases (kill -9 during push) may need manual recovery. Acceptable — manual recovery of a 4-step ceremony is simple vs. automated recovery of a 53-step pipeline that creates new bugs.
**Sources:** corruption.py (620 lines, 17+ scenarios); S7_STALE_PLAN_ON_MAIN auto-deleting plans
**Exploration:** quick
**Depends on:** D4 (fully mechanical enables clean failure)
**Status:** captured

## D6: Lifecycle — replace state machine with simple status field

**Choice:** The queue file has a status field (active, paused, drained, idle). The close ceremony reads it on entry, writes it on exit. No state machine, no transition table, no concurrent modification errors. 776 lines → ~30 lines.
**Alternatives:**
- Keep state machine, decouple from plan — the 12 states model real invariants (can't stamp before landing). But with a mechanical ceremony, ordering is enforced by code sequence, not by a state machine.
- Simplify to fewer states — reduce 12 to 4-5. Better but still adds machinery for something that code sequencing handles.
**Rationale:** The state machine's complexity exists to enforce ordering in an LLM-driven loop where steps can execute in any order. In a sequential mechanical ceremony, the code itself is the ordering constraint.
**Trade-offs:** No formal invariant enforcement. If someone adds a step out of order, there's no machine to catch it. Mitigated by tests and the ceremony being short enough to review by eye.
**Sources:** lifecycle.py (776 lines, 12 states); lifecycle.commit_transition() deleting .plan on idle transition
**Exploration:** quick
**Depends on:** D4 (mechanical execution eliminates need for state machine ordering)
**Status:** captured
